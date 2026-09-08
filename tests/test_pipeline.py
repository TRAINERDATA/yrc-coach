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


def test_shortcut_string_units_and_dates():
    payload = {"workouts": [
        {"type": "달리기", "start": "2026-09-06T06:00:00+09:00", "end": "2026-09-06T06:35:00+09:00", "distance": "6.42 km"},
        {"type": "Running", "start": "2026-09-05T06:00:00+09:00", "end": "2026-09-05T06:30:00+09:00", "distance": "5,120 m"},
        {"type": "Running", "start": "2026-09-04T06:00:00+09:00", "end": "2026-09-04T06:30:00+09:00", "distance": 4800},
        {"type": "Running", "start": "2026-09-03T06:00:00+09:00", "end": "2026-09-03T07:00:00+09:00", "distance": "3.1 mi"},
    ]}
    w, _ = ingest.parse_payload(payload)
    assert [x["distance_km"] for x in w] == [6.42, 5.12, 4.8, 4.989]
    assert w[0]["duration_s"] == 2100 and w[0]["start"] == "2026-09-06T06:00:00"


def test_hourly_reconstruction():
    payload = {"hourly": {
        "speed": [{"start": "2026-09-07T06:00:00+09:00", "value": "10.4 km/h"},
                  {"start": "2026-09-07T07:00:00+09:00", "value": "10.8 km/h"},
                  {"start": "2026-09-05T19:00:00+09:00", "value": "2.9 m/s"}],
        "distance": [{"start": "2026-09-07T06:00:00+09:00", "value": "4.1 km"},
                     {"start": "2026-09-07T07:00:00+09:00", "value": "2.5 km"},
                     {"start": "2026-09-07T12:00:00+09:00", "value": "1.2 km"},
                     {"start": "2026-09-05T19:00:00+09:00", "value": "5200 m"}],
        "hr": [{"start": "2026-09-07T06:00:00+09:00", "value": "150 count/min"},
               {"start": "2026-09-07T07:00:00+09:00", "value": "156 count/min"}],
    }}
    w, _ = ingest.parse_payload(payload)
    assert len(w) == 2
    a, b = sorted(w, key=lambda x: x["start"])
    assert a["start"] == "2026-09-05T19:00:00" and a["distance_km"] == 5.2 and a["avg_hr"] is None
    assert b["start"] == "2026-09-07T06:00:00" and b["distance_km"] == 6.6 and b["avg_hr"] == 153
    assert 2150 < b["duration_s"] < 2300 and b["source"] == "shortcut_hourly"
    # 정오의 걷기(속도 샘플 없음)는 러닝으로 잡히지 않음
    assert all(x["start"][11:13] != "12" for x in w)


def test_text_section_body():
    body = """##speed_dates
2026-09-08T20:05:49+09:00
2026-09-06T07:30:54+09:00
##speed_values
10.06 km/h
9.86 km/h
##distance_dates
2026-09-08T20:00:00+09:00
2026-09-06T07:00:00+09:00
2026-09-08T12:00:00+09:00
##distance_values
6.5 km
7.1 km
2 km
##hr_dates
2026-09-08T20:00:00+09:00
##hr_values
155 회/분
""".encode("utf-8")
    payload = ingest.parse_body(body)
    assert set(payload["hourly"]) == {"speed_dates", "speed_values", "distance_dates", "distance_values", "hr_dates", "hr_values"}
    w, _ = ingest.parse_payload(payload)
    assert len(w) == 2 and {x["distance_km"] for x in w} == {6.5, 7.1}
    assert ingest.parse_body(b'{"hourly": {}}') == {"hourly": {}}


def test_hourly_raw_hr_samples_and_dedupe():
    # 20시 러닝: 속도 10km/h, 심박 원본 샘플 400개(=30분) → 거리 5.0km
    hr_dates = "\n".join(f"2026-09-08T20:{m:02d}:{s:02d}+09:00" for m in range(30) for s in range(0, 60, 5))[:0]
    dates, vals = [], []
    for i in range(400):
        m, s = divmod(i * 4, 60)
        dates.append(f"2026-09-08T20:{m:02d}:{s:02d}+09:00"); vals.append("170 회/분" if i % 2 else "160 회/분")
    payload = {"hourly": {"speed_dates": "2026-09-08T20:05:49+09:00", "speed_values": "10 km/h",
                          "distance_dates": "2026-09-08T20:00:00+09:00", "distance_values": "6.2 km",
                          "hr_dates": "\n".join(dates), "hr_values": "\n".join(vals)}}
    w, _ = ingest.parse_payload(payload)
    assert len(w) == 1 and w[0]["raw"]["method"] == "hr_samples"
    assert w[0]["distance_km"] == 5.0 and w[0]["duration_s"] == 1800 and w[0]["avg_hr"] == 165 and w[0]["max_hr"] == 170
    # 정확한 기록이 같은 시간대에 들어오면 근사치는 제거됨
    u = db.add_user("dedupe", "none")
    db.upsert_workouts(u["id"], w)
    assert len(db.workouts_since(u["id"], 400)) == 1
    db.upsert_workouts(u["id"], [{"start": "2026-09-08T20:05:49", "end": "2026-09-08T20:35:49", "duration_s": 1800,
                                  "distance_km": 5.01, "avg_hr": 172, "source": "health_export", "raw": {}}])
    rows = db.workouts_since(u["id"], 400)
    assert len(rows) == 1 and rows[0]["source"] == "health_export"
