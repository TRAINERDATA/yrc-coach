"""브리핑 전송 채널: Telegram 봇 / 카카오톡 '나에게 보내기' / ntfy 푸시."""
from __future__ import annotations

import json
import logging

import requests

from . import config, db

log = logging.getLogger(__name__)


def brief_url(user: dict) -> str:
    return f"{config.PUBLIC_BASE_URL}/brief/{user['token']}"


# ---------- Telegram ----------
def send_telegram(chat_id: str, text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 이 설정되지 않았습니다")
    r = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )
    if r.status_code != 200:
        log.error("telegram error %s %s", r.status_code, r.text[:300])
    return r.status_code == 200


def telegram_updates() -> list:
    """봇에게 말을 건 사람들의 chat_id 를 찾을 때 사용 (CLI: telegram-chats)."""
    r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates", timeout=20)
    r.raise_for_status()
    out = []
    for u in r.json().get("result", []):
        m = u.get("message") or u.get("channel_post") or {}
        chat = m.get("chat") or {}
        if chat.get("id"):
            out.append({"chat_id": str(chat["id"]), "name": chat.get("first_name") or chat.get("title"), "text": m.get("text")})
    return out


# ---------- Kakao (나에게 보내기) ----------
KAKAO_AUTH = "https://kauth.kakao.com/oauth"
KAKAO_API = "https://kapi.kakao.com"


def kakao_authorize_url() -> str:
    return (f"{KAKAO_AUTH}/authorize?response_type=code&client_id={config.KAKAO_REST_API_KEY}"
            f"&redirect_uri={config.KAKAO_REDIRECT_URI}&scope=talk_message")


def kakao_exchange_code(code: str) -> dict:
    r = requests.post(f"{KAKAO_AUTH}/token", data={
        "grant_type": "authorization_code", "client_id": config.KAKAO_REST_API_KEY,
        "redirect_uri": config.KAKAO_REDIRECT_URI, "code": code}, timeout=20)
    r.raise_for_status()
    return r.json()


def kakao_refresh(user: dict) -> str:
    r = requests.post(f"{KAKAO_AUTH}/token", data={
        "grant_type": "refresh_token", "client_id": config.KAKAO_REST_API_KEY,
        "refresh_token": user["kakao_refresh_token"]}, timeout=20)
    r.raise_for_status()
    tok = r.json()
    fields = {"kakao_access_token": tok["access_token"]}
    if tok.get("refresh_token"):
        fields["kakao_refresh_token"] = tok["refresh_token"]
    db.update_user(user["id"], **fields)
    return tok["access_token"]


def send_kakao(user: dict, text: str) -> bool:
    """카카오 텍스트 템플릿은 200자 제한. 앞부분만 보내고 전체는 링크로."""
    head = text if len(text) <= 190 else text[:185].rstrip() + "…"
    template = {"object_type": "text", "text": head,
                "link": {"web_url": brief_url(user), "mobile_web_url": brief_url(user)},
                "button_title": "전체 브리핑 보기"}

    def _post(token: str):
        return requests.post(f"{KAKAO_API}/v2/api/talk/memo/default/send",
                             headers={"Authorization": f"Bearer {token}"},
                             data={"template_object": json.dumps(template, ensure_ascii=False)}, timeout=20)

    r = _post(user["kakao_access_token"] or "")
    if r.status_code == 401 and user.get("kakao_refresh_token"):
        r = _post(kakao_refresh(user))
    if r.status_code != 200:
        log.error("kakao error %s %s", r.status_code, r.text[:300])
    return r.status_code == 200


# ---------- ntfy ----------
def send_ntfy(topic: str, text: str, user: dict) -> bool:
    r = requests.post(f"{config.NTFY_SERVER}/{topic}", data=text.encode("utf-8"),
                      headers={"Title": "YRC Running Coach".encode("utf-8"), "Click": brief_url(user), "Tags": "running_shirt_with_sash"},
                      timeout=20)
    return r.status_code == 200


# ---------- dispatcher ----------
def deliver(user: dict, text: str) -> bool:
    ch = user.get("channel") or "none"
    if ch == "telegram" and user.get("telegram_chat_id"):
        return send_telegram(user["telegram_chat_id"], text)
    if ch == "kakao" and user.get("kakao_access_token"):
        return send_kakao(user, text)
    if ch == "ntfy" and user.get("ntfy_topic"):
        return send_ntfy(user["ntfy_topic"], text, user)
    log.info("no delivery channel for %s (channel=%s)", user["name"], ch)
    return False
