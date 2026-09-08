import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(encoding="utf-8")


def _clean(v: str) -> str:
    # 같은 줄에 '# 주석' 이 붙어 있어도 값으로 읽히지 않도록
    return v.split(" #", 1)[0].strip() if v and not v.startswith("#") else ""


os.environ.update({k: _clean(os.environ[k]) for k in (
    "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "KAKAO_REST_API_KEY", "PUBLIC_BASE_URL", "DB_PATH") if k in os.environ})

DB_PATH = os.getenv("DB_PATH", "./data/yrc.db")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
BRIEF_HOUR = int(os.getenv("BRIEF_HOUR", "7"))
BRIEF_MINUTE = int(os.getenv("BRIEF_MINUTE", "0"))
TZ = os.getenv("TZ", "Asia/Seoul")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", f"{PUBLIC_BASE_URL}/kakao/callback")
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "").strip()
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET", "").strip()
# Postgres 를 쓰면 (Supabase/Neon 무료) DATABASE_URL 설정. 없으면 SQLite(DB_PATH).
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# COACH_PROVIDER: auto(키 있으면 Claude, 없으면 규칙) | rules(항상 규칙 기반, 비용 0) | claude
COACH_PROVIDER = os.getenv("COACH_PROVIDER", "auto").lower()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")
COACH_EFFORT = os.getenv("COACH_EFFORT", "medium")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def local_today():
    """서버가 어느 시간대에 있든 한국 날짜 기준."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TZ)).date()
    except Exception:  # noqa: BLE001
        from datetime import timedelta, timezone
        return datetime.now(timezone(timedelta(hours=9))).date()
