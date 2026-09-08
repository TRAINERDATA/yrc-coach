"""Strava 연동. 사용자가 한 번 OAuth 로 연결하면 매일 브리핑 전에 최근 러닝을 자동으로 가져온다.

- 연결:   GET /strava/connect/{token}  → Strava 동의 화면 → /strava/callback 으로 돌아와 토큰 저장
- 동기화: pipeline.run_for_user 가 브리핑 직전에 sync() 호출 (또는 POST /strava/sync/{token})
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import requests

from . import config, db

log = logging.getLogger(__name__)

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API = "https://www.strava.com/api/v3"
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def enabled() -> bool:
    return bool(config.STRAVA_CLIENT_ID and config.STRAVA_CLIENT_SECRET)


def authorize_url(user: dict) -> str:
    return (f"{AUTH_URL}?client_id={config.STRAVA_CLIENT_ID}&response_type=code"
            f"&redirect_uri={config.PUBLIC_BASE_URL}/strava/callback&approval_prompt=auto"
            f"&scope=read,activity:read_all&state={user['token']}")


def exchange_code(code: str) -> dict:
    r = requests.post(TOKEN_URL, data={"client_id": config.STRAVA_CLIENT_ID, "client_secret": config.STRAVA_CLIENT_SECRET,
                                       "code": code, "grant_type": "authorization_code"}, timeout=20)
    r.raise_for_status()
    return r.json()


def save_tokens(user: dict, tok: dict):
    db.update_user(user["id"], strava_athlete_id=str((tok.get("athlete") or {}).get("id") or user.get("strava_athlete_id") or ""),
                   strava_access_token=tok["access_token"], strava_refresh_token=tok["refresh_token"],
                   strava_expires_at=int(tok.get("expires_at") or 0))


def access_token(user: dict) -> str:
    if user.get("strava_access_token") and (user.get("strava_expires_at") or 0) > time.time() + 60:
        return user["strava_access_token"]
    r = requests.post(TOKEN_URL, data={"client_id": config.STRAVA_CLIENT_ID, "client_secret": config.STRAVA_CLIENT_SECRET,
                                       "grant_type": "refresh_token", "refresh_token": user["strava_refresh_token"]}, timeout=20)
    r.raise_for_status()
    tok = r.json()
    save_tokens(user, tok)
    user.update(strava_access_token=tok["access_token"], strava_refresh_token=tok["refresh_token"], strava_expires_at=tok["expires_at"])
    return tok["access_token"]


def _to_workout(a: dict) -> dict | None:
    if (a.get("sport_type") or a.get("type")) not in RUN_TYPES:
        return None
    dist_km = (a.get("distance") or 0) / 1000
    if dist_km < 0.3:
        return None
    start = datetime.fromisoformat(a["start_date_local"].replace("Z", ""))  # 로컬 시각 (Z 는 무시)
    dur = a.get("moving_time") or a.get("elapsed_time") or 0
    return {
        "start": start.isoformat(timespec="seconds"),
        "end": (start + timedelta(seconds=a.get("elapsed_time") or dur)).isoformat(timespec="seconds"),
        "duration_s": float(dur), "distance_km": round(dist_km, 3),
        "avg_hr": a.get("average_heartrate"), "max_hr": a.get("max_heartrate"),
        "energy_kcal": a.get("kilojoules"), "elev_gain_m": a.get("total_elevation_gain"),
        "source": "strava",
        "raw": {"id": a.get("id"), "name": a.get("name"), "sport_type": a.get("sport_type"),
                "average_speed": a.get("average_speed"), "device": a.get("device_name")},
    }


def sync(user: dict, days: int = 56) -> int:
    """최근 days 일의 러닝을 가져와 저장. 저장한 개수 반환."""
    if not enabled() or not user.get("strava_refresh_token"):
        return 0
    tok = access_token(user)
    after = int((datetime.now() - timedelta(days=days)).timestamp())
    rows, page = [], 1
    while True:
        r = requests.get(f"{API}/athlete/activities", headers={"Authorization": f"Bearer {tok}"},
                         params={"after": after, "per_page": 200, "page": page}, timeout=30)
        if r.status_code == 401:
            raise RuntimeError("Strava 인증 만료. /strava/connect 로 다시 연결하세요")
        r.raise_for_status()
        batch = r.json()
        rows += [w for w in (_to_workout(a) for a in batch) if w]
        if len(batch) < 200:
            break
        page += 1
    n = db.upsert_workouts(user["id"], rows)
    log.info("strava sync %s: %d runs", user["name"], n)
    return n
