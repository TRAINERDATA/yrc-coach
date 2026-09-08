"""SQLite 저장소. 사용자(크루원) / 러닝 기록 / 일일 건강지표 / 브리핑 이력."""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterable

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  channel TEXT NOT NULL DEFAULT 'telegram',
  telegram_chat_id TEXT,
  kakao_access_token TEXT,
  kakao_refresh_token TEXT,
  ntfy_topic TEXT,
  age INTEGER,
  max_hr INTEGER,
  goal TEXT,
  weekly_days INTEGER DEFAULT 4,
  notes TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  start TEXT NOT NULL,
  end TEXT,
  duration_s REAL,
  distance_km REAL,
  avg_hr REAL,
  max_hr REAL,
  energy_kcal REAL,
  elev_gain_m REAL,
  source TEXT,
  raw TEXT,
  UNIQUE(user_id, start)
);
CREATE TABLE IF NOT EXISTS daily_metrics (
  user_id INTEGER NOT NULL,
  date TEXT NOT NULL,
  resting_hr REAL,
  hrv REAL,
  sleep_h REAL,
  steps REAL,
  weight_kg REAL,
  vo2max REAL,
  PRIMARY KEY(user_id, date)
);
CREATE TABLE IF NOT EXISTS briefings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  date TEXT NOT NULL,
  summary TEXT NOT NULL,
  text TEXT NOT NULL,
  channel TEXT,
  delivered INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, date)
);
"""

# users 컬럼 설명
#   token        : 폰에서 데이터를 보낼 때 / 브리핑 페이지를 볼 때 쓰는 개인 키
#   channel      : telegram | kakao | ntfy | none
#   goal         : 예) "11월 마라톤 서브4", "10km 50분"
#   weekly_days  : 주당 러닝 가능 일수
#   notes        : 부상 이력, 선호 시간대 등 자유 메모


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
    try:
        n = seed_users_from_env()
        if n:
            import logging
            logging.getLogger(__name__).info("seeded %d users from SEED_USERS", n)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error("SEED_USERS parse failed: %s", e)


# ---------- users ----------
def add_user(name: str, channel: str = "telegram", token: str = None, **fields) -> dict:
    token = token or secrets.token_urlsafe(18)
    cols = ["name", "token", "channel", "created_at"] + list(fields)
    vals = [name, token, channel, datetime.now().isoformat(timespec="seconds")] + list(fields.values())
    placeholders = ",".join(["?"] * len(cols))
    with conn() as c:
        cur = c.execute(f"INSERT INTO users ({','.join(cols)}) VALUES ({placeholders})", vals)
        new_id = cur.lastrowid
    return get_user(new_id)


def upsert_user_by_token(spec: dict) -> dict:
    """token 기준으로 있으면 갱신, 없으면 생성. (Render 무료 플랜처럼 DB가 초기화되는 환경에서 SEED_USERS 로 복구)"""
    spec = {k: v for k, v in spec.items() if k in USER_FIELDS and v is not None}
    token = spec.pop("token", None)
    name = spec.pop("name", None) or "러너"
    channel = spec.pop("channel", None) or "telegram"
    if not token:
        raise ValueError("token required")
    existing = get_user_by_token(token)
    if existing:
        update_user(existing["id"], name=name, channel=channel, **spec)
        return get_user(existing["id"])
    return add_user(name, channel, token=token, **spec)


USER_FIELDS = {"name", "token", "channel", "telegram_chat_id", "kakao_access_token", "kakao_refresh_token",
               "ntfy_topic", "age", "max_hr", "goal", "weekly_days", "notes", "active"}


def seed_users_from_env():
    """SEED_USERS='[{"name":"...","token":"...","telegram_chat_id":"..."}]' 환경변수로 사용자 복구."""
    import json
    import os
    raw = os.getenv("SEED_USERS", "").strip()
    if not raw:
        return 0
    n = 0
    for spec in json.loads(raw):
        upsert_user_by_token(spec)
        n += 1
    return n


def update_user(user_id: int, **fields):
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE users SET {sets} WHERE id=?", [*fields.values(), user_id])


def get_user(user_id: int):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(r) if r else None


def get_user_by_token(token: str):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
        return dict(r) if r else None


def list_users(active_only: bool = True) -> list:
    with conn() as c:
        q = "SELECT * FROM users" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
        return [dict(r) for r in c.execute(q)]


# ---------- workouts ----------
def upsert_workouts(user_id: int, rows: Iterable[dict]) -> int:
    n = 0
    with conn() as c:
        for w in rows:
            c.execute(
                """INSERT INTO workouts
                   (user_id,start,end,duration_s,distance_km,avg_hr,max_hr,energy_kcal,elev_gain_m,source,raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,start) DO UPDATE SET
                     end=excluded.end, duration_s=excluded.duration_s, distance_km=excluded.distance_km,
                     avg_hr=COALESCE(excluded.avg_hr,avg_hr), max_hr=COALESCE(excluded.max_hr,max_hr),
                     energy_kcal=COALESCE(excluded.energy_kcal,energy_kcal),
                     elev_gain_m=COALESCE(excluded.elev_gain_m,elev_gain_m), raw=excluded.raw""",
                (
                    user_id, w["start"], w.get("end"), w.get("duration_s"), w.get("distance_km"),
                    w.get("avg_hr"), w.get("max_hr"), w.get("energy_kcal"), w.get("elev_gain_m"),
                    w.get("source", "health_auto_export"), json.dumps(w.get("raw"), ensure_ascii=False),
                ),
            )
            n += 1
    return n


def workouts_since(user_id: int, days: int) -> list:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM workouts WHERE user_id=? AND start>=? ORDER BY start", (user_id, since))]


# ---------- daily metrics ----------
def upsert_metrics(user_id: int, rows: Iterable[dict]) -> int:
    n = 0
    with conn() as c:
        for m in rows:
            c.execute(
                """INSERT INTO daily_metrics (user_id,date,resting_hr,hrv,sleep_h,steps,weight_kg,vo2max)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,date) DO UPDATE SET
                     resting_hr=COALESCE(excluded.resting_hr,resting_hr), hrv=COALESCE(excluded.hrv,hrv),
                     sleep_h=COALESCE(excluded.sleep_h,sleep_h), steps=COALESCE(excluded.steps,steps),
                     weight_kg=COALESCE(excluded.weight_kg,weight_kg), vo2max=COALESCE(excluded.vo2max,vo2max)""",
                (user_id, m["date"], m.get("resting_hr"), m.get("hrv"), m.get("sleep_h"),
                 m.get("steps"), m.get("weight_kg"), m.get("vo2max")),
            )
            n += 1
    return n


def metrics_since(user_id: int, days: int) -> list:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM daily_metrics WHERE user_id=? AND date>=? ORDER BY date", (user_id, since))]


# ---------- briefings ----------
def save_briefing(user_id: int, date: str, summary: dict, text: str, channel: str, delivered: bool):
    with conn() as c:
        c.execute(
            """INSERT INTO briefings (user_id,date,summary,text,channel,delivered,created_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id,date) DO UPDATE SET summary=excluded.summary, text=excluded.text,
                 channel=excluded.channel, delivered=excluded.delivered, created_at=excluded.created_at""",
            (user_id, date, json.dumps(summary, ensure_ascii=False), text, channel, int(delivered),
             datetime.now().isoformat(timespec="seconds")),
        )


def latest_briefing(user_id: int):
    with conn() as c:
        r = c.execute("SELECT * FROM briefings WHERE user_id=? ORDER BY date DESC LIMIT 1", (user_id,)).fetchone()
        return dict(r) if r else None


def recent_briefings(user_id: int, n: int = 7) -> list:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT date, text FROM briefings WHERE user_id=? ORDER BY date DESC LIMIT ?", (user_id, n))]
