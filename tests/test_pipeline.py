import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DB_PATH"] = str(ROOT / "data" / "test.db")
os.environ["ANTHROPIC_API_KEY"] = ""  # 테스트는 규칙 기반 브리핑으로

from app import db, ingest, analysis, coach  # noqa: E402


def setup_module(_):
    p = Path(os.environ["DB_PATH"])
    if p.exists():
        p.unlink()
    db.init()


def test_parse_health_auto_export():
    payload = json.loads((ROOT / "samples" / "health_auto_export.json").read_text(encoding="utf-8"))
    w, m = ingest.parse_payload(payload)
    assert len(w) == 1  # Walking 은 제외
    r = w[0]
    assert r["distance_km"] == 6.42 and abs(r["duration_s"] - 2248) < 1
    assert 140 < r["avg_hr"] < 160 and r["max_hr"] == 166 and r["elev_gain_m"] == 38
    assert r["start"] == "2026-09-07T06:31:12"
    assert len(m) == 1 and m[0]["resting_hr"] == 53 and m[0]["sleep_h"] == 6.8 and m[0]["steps"] == 4614


def test_parse_shortcut_format():
    payload = {"workouts": [{"type": "Running", "start": "2026-09-07T06:00:00", "end": "2026-09-07T06:30:00",
                             "distance_km": 5.0, "avg_hr": 150}],
               "metrics": {"date": "2026-09-07", "resting_hr": 51, "hrv": 60, "sleep_h": 7.2}}
    w, m = ingest.parse_payload(payload)
    assert w[0]["duration_s"] == 1800 and w[0]["source"] == "shortcut"
    assert m[0]["hrv"] == 60


def test_summary_and_rule_briefing():
    u = db.add_user("테스트", "none", age=30, goal="10km 50분")
    payload = json.loads((ROOT / "samples" / "health_auto_export.json").read_text(encoding="utf-8"))
    w, m = ingest.parse_payload(payload)
    db.upsert_workouts(u["id"], w)
    db.upsert_metrics(u["id"], m)
    from datetime import date
    s = analysis.build_summary(u, today=date(2026, 9, 8))
    assert s["volume"]["last7_km"] == 6.4 and s["volume"]["runs_last7"] == 1
    assert s["yesterday_runs"][0]["pace"] == "5'50\""
    text = coach.rule_based_briefing(s)
    assert "테스트님" in text and "오늘 훈련" in text and len(text) < 900
    # 중복 저장은 upsert
    assert db.upsert_workouts(u["id"], w) == 1
    assert len(db.workouts_since(u["id"], 400)) == 1


def test_seed_users_from_env():
    os.environ["SEED_USERS"] = json.dumps([{"name": "seed1", "token": "tok-seed-1", "telegram_chat_id": "111", "age": 28}])
    assert db.seed_users_from_env() == 1
    u = db.get_user_by_token("tok-seed-1")
    assert u["telegram_chat_id"] == "111" and u["age"] == 28
    os.environ["SEED_USERS"] = json.dumps([{"name": "seed1", "token": "tok-seed-1", "telegram_chat_id": "222", "goal": "10k"}])
    db.seed_users_from_env()
    u2 = db.get_user_by_token("tok-seed-1")
    assert u2["id"] == u["id"] and u2["telegram_chat_id"] == "222" and u2["goal"] == "10k"
    os.environ.pop("SEED_USERS")
