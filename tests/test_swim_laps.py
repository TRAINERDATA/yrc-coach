import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DB_PATH"] = str(ROOT / "data" / "test_laps.db")

from app import db, ingest  # noqa: E402


def setup_module(_):
    p = Path(os.environ["DB_PATH"])
    if p.exists():
        p.unlink()
    db.init()


def _ts(sec):
    return f"2026-09-15T{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}+09:00"


def test_swim_lap_samples_duration_and_dedupe():
    base = 6 * 3600 + 50 * 60
    lap_d = [_ts(base + i * 65) for i in range(27)]
    lap_v = ["11"] * 27
    hr_d = [_ts(base + i) for i in range(0, 1800, 15)]
    hr_v = ["130"] * len(hr_d)
    p = {"hourly": {"swim_dates": "2026-09-15T06:50:28+09:00\n2026-09-15T07:00:40+09:00", "swim_values": "200\n475",
                    "strokes_dates": "\n".join(lap_d), "strokes_values": "\n".join(lap_v),
                    "hr_dates": "\n".join(hr_d), "hr_values": "\n".join(hr_v)}}
    w, _ = ingest.parse_payload(p)
    assert len(w) == 1
    s = w[0]
    assert s["raw"]["method"] == "lap_samples" and s["raw"]["lengths"] == 27
    assert s["start"] == "2026-09-15T06:50:00" and 1700 <= s["duration_s"] <= 1760 and s["strokes"] == 297 and s["avg_hr"] == 130
    u = db.add_user("swimdedupe", "none", sport="swim")
    db.upsert_workouts(u["id"], [{"start": "2026-09-15T06:00:00", "end": "2026-09-15T06:13:00", "duration_s": 780,
                                  "distance_km": 0.675, "sport": "swim", "source": "shortcut_hourly", "raw": {}}])
    db.upsert_workouts(u["id"], w)
    rows = db.workouts_since(u["id"], 400, sport="swim")
    assert len(rows) == 1 and rows[0]["start"] == "2026-09-15T06:50:00"
