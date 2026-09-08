"""아이폰 건강 앱 '모든 건강 데이터 내보내기' (export.zip / 내보내기.zip) 에서 러닝 기록과 일일 지표를 읽는다.

python -m app.cli import-health <user_id> export.zip [--days 90]
파일이 수백 MB 여도 스트리밍(iterparse)으로 읽어 메모리를 적게 쓴다.
"""
from __future__ import annotations

import zipfile
from datetime import datetime, timedelta
from typing import IO
from xml.etree import ElementTree as ET

RUN_TYPES = {"HKWorkoutActivityTypeRunning"}
METRIC_TYPES = {
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_hr",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
    "HKQuantityTypeIdentifierVO2Max": "vo2max",
    "HKQuantityTypeIdentifierBodyMass": "weight_kg",
}


def _dt(s: str) -> datetime:
    return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def _open_xml(path: str) -> IO[bytes]:
    if path.lower().endswith(".zip"):
        z = zipfile.ZipFile(path)

        def real_name(n: str) -> str:  # 한글 파일명은 zip 안에서 cp437 로 깨져 있을 수 있음
            try:
                return n.encode("cp437").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                return n

        cands = [n for n in z.namelist() if real_name(n).lower().endswith(".xml") and "cda" not in real_name(n).lower()]
        name = next((n for n in cands if real_name(n).endswith(("export.xml", "내보내기.xml"))), None) or (cands[0] if cands else None)
        if not name:
            raise ValueError("zip 안에 export.xml(내보내기.xml) 이 없습니다")
        return z.open(name)
    return open(path, "rb")


def parse(path: str, days: int = 90):
    """(workouts, metrics) 반환. 최근 days 일만."""
    since = datetime.now() - timedelta(days=days)
    workouts, metrics = [], {}
    sleep_by_day: dict = {}
    with _open_xml(path) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            tag = el.tag
            if tag == "Workout":
                if el.get("workoutActivityType") in RUN_TYPES:
                    start = _dt(el.get("startDate"))
                    if start >= since:
                        end = _dt(el.get("endDate"))
                        dist = el.get("totalDistance")
                        unit = (el.get("totalDistanceUnit") or "km").lower()
                        avg_hr = max_hr = None
                        for st in el.findall("WorkoutStatistics"):
                            t = st.get("type")
                            if t == "HKQuantityTypeIdentifierDistanceWalkingRunning" and dist is None:
                                dist, unit = st.get("sum"), (st.get("unit") or "km").lower()
                            elif t == "HKQuantityTypeIdentifierHeartRate":
                                avg_hr = float(st.get("average")) if st.get("average") else None
                                max_hr = float(st.get("maximum")) if st.get("maximum") else None
                        dist_km = float(dist) if dist else 0.0
                        if unit in ("m", "meters"):
                            dist_km /= 1000
                        elif unit in ("mi", "miles"):
                            dist_km *= 1.609344
                        dur = el.get("duration")
                        dur_s = float(dur) * (60 if (el.get("durationUnit") or "min") == "min" else 1) if dur else (end - start).total_seconds()
                        if dist_km >= 0.3:
                            workouts.append({
                                "start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"),
                                "duration_s": dur_s, "distance_km": round(dist_km, 3), "avg_hr": avg_hr, "max_hr": max_hr,
                                "energy_kcal": None, "elev_gain_m": None, "source": "health_export",
                                "raw": {"device": (el.get("sourceName") or "")[:40]},
                            })
                el.clear()
            elif tag == "Record":
                t = el.get("type")
                col = METRIC_TYPES.get(t)
                if col or t == "HKCategoryTypeIdentifierSleepAnalysis":
                    start = _dt(el.get("startDate"))
                    if start >= since:
                        if col:
                            day = start.strftime("%Y-%m-%d")
                            m = metrics.setdefault(day, {"date": day})
                            # 하루에 여러 번 측정되는 값(HRV 등)은 평균
                            cnt = m.setdefault("_n", {}).get(col, 0)
                            m[col] = (m.get(col, 0) * cnt + float(el.get("value"))) / (cnt + 1)
                            m["_n"][col] = cnt + 1
                        elif "Asleep" in (el.get("value") or ""):
                            end = _dt(el.get("endDate"))
                            day = end.strftime("%Y-%m-%d")  # 기상일 기준
                            sleep_by_day[day] = sleep_by_day.get(day, 0) + (end - start).total_seconds() / 3600
                el.clear()
            elif tag in ("Correlation", "ActivitySummary", "ClinicalRecord"):
                el.clear()
    for day, h in sleep_by_day.items():
        metrics.setdefault(day, {"date": day})["sleep_h"] = round(h, 2)
    out = []
    for m in metrics.values():
        m.pop("_n", None)
        out.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()})
    return workouts, out
