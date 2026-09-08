"""iPhone 건강 데이터 파서.

지원 포맷
1) Health Auto Export 앱 (REST API 자동화, JSON)
   {"data": {"workouts": [...], "metrics": [...]}}
2) 단축어(Shortcuts)로 직접 보내는 단순 포맷
   {"workouts": [{"start", "end", "distance_km", "duration_s", "avg_hr"}], "metrics": {"resting_hr": 52, ...}}

어떤 키가 와도 최대한 관대하게 읽고, 원본은 raw 로 보관한다.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

RUN_NAMES = ("running", "run", "달리기", "러닝", "treadmill")


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, dict):  # {"qty": 5.2, "units": "km"}
        return _num(v.get("qty", v.get("value")))
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(\.\d+)?", v.replace(",", ""))
        return float(m.group()) if m else None
    return None


def _units(v: Any) -> str:
    return str(v.get("units") or "").lower() if isinstance(v, dict) else ""


def parse_dt(s: Any) -> Optional[datetime]:
    """여러 날짜 포맷을 로컬 naive datetime 으로 변환."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return datetime.fromtimestamp(s)
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = datetime.strptime(s, fmt)
            return d if d.tzinfo is None else d.astimezone().replace(tzinfo=None)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo is None else d.astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def _is_run(w: dict) -> bool:
    name = str(w.get("name") or w.get("type") or w.get("workoutActivityType") or "").lower()
    return any(k in name for k in RUN_NAMES)


def _distance_km(w: dict) -> Optional[float]:
    for key in ("distance_km", "distance", "totalDistance"):
        if key in w:
            q = _num(w[key])
            if q is None:
                continue
            u = _units(w[key])
            if u in ("m", "meter", "meters"):
                return q / 1000
            if u in ("mi", "mile", "miles"):
                return q * 1.609344
            if u in ("km", "kilometer", "kilometers", "") and q > 200:
                return q / 1000  # 단위 없이 큰 숫자면 미터로 간주
            return q  # km
    return None


def _hr(w: dict):
    avg = _num(w.get("avg_hr")) or _num(w.get("avgHeartRate")) or _num(w.get("averageHeartRate"))
    mx = _num(w.get("max_hr")) or _num(w.get("maxHeartRate"))
    hr = w.get("heartRate") or w.get("heart_rate")
    if isinstance(hr, dict):
        avg = avg or _num(hr.get("avg") or hr.get("Avg") or hr.get("average"))
        mx = mx or _num(hr.get("max") or hr.get("Max"))
    samples = w.get("heartRateData")
    if isinstance(samples, list) and samples:
        avgs = [x for x in (_num(s.get("Avg") or s.get("avg") or s.get("qty")) for s in samples) if x]
        maxs = [x for x in (_num(s.get("Max") or s.get("max")) for s in samples) if x]
        avg = avg or (sum(avgs) / len(avgs) if avgs else None)
        mx = mx or (max(maxs) if maxs else (max(avgs) if avgs else None))
    return avg, mx


def parse_workouts(payload: dict) -> list:
    data = payload.get("data", payload)
    items = data.get("workouts") or []
    out = []
    for w in items:
        if not isinstance(w, dict) or not _is_run(w):
            continue
        start, end = parse_dt(w.get("start")), parse_dt(w.get("end"))
        if not start:
            continue
        dur = _num(w.get("duration_s"))
        if dur is None:
            dur = _num(w.get("duration"))
        if dur is None and end:
            dur = (end - start).total_seconds()
        elif dur is not None and end and dur < 300 and (end - start).total_seconds() > 600:
            dur = dur * 60  # 분 단위로 온 경우
        dist = _distance_km(w)
        if not dist or dist < 0.3:
            continue
        avg_hr, max_hr = _hr(w)
        energy = _num(w.get("activeEnergyBurned") or w.get("activeEnergy") or w.get("energy_kcal"))
        elev = _num(w.get("elevationUp") or w.get("elevation_gain_m") or w.get("elevation"))
        out.append({
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds") if end else None,
            "duration_s": dur,
            "distance_km": round(dist, 3),
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "energy_kcal": energy,
            "elev_gain_m": elev,
            "source": "shortcut" if "distance_km" in w else "health_auto_export",
            "raw": {k: v for k, v in w.items() if k not in ("route", "heartRateData", "stepCount", "heartRateRecovery")},
        })
    return out


# Health Auto Export metric 이름 -> daily_metrics 컬럼
METRIC_MAP = {
    "resting_heart_rate": "resting_hr",
    "heart_rate_variability": "hrv",
    "sleep_analysis": "sleep_h",
    "step_count": "steps",
    "weight_body_mass": "weight_kg",
    "vo2_max": "vo2max",
    # 단축어 단순 포맷
    "resting_hr": "resting_hr",
    "hrv": "hrv",
    "sleep_h": "sleep_h",
    "steps": "steps",
    "weight_kg": "weight_kg",
    "vo2max": "vo2max",
}


def parse_metrics(payload: dict) -> list:
    data = payload.get("data", payload)
    metrics = data.get("metrics") or []
    by_date: dict = {}

    def put(date: str, col: str, val):
        if val is None:
            return
        by_date.setdefault(date, {"date": date})
        if col == "steps":  # 걸음은 하루 합계
            by_date[date][col] = (by_date[date].get(col) or 0) + val
        else:
            by_date[date][col] = val

    if isinstance(metrics, dict):  # 단순 포맷
        d = parse_dt(metrics.get("date")) or datetime.now()
        for k, v in metrics.items():
            if k in METRIC_MAP:
                put(d.strftime("%Y-%m-%d"), METRIC_MAP[k], _num(v))
        return list(by_date.values())

    for m in metrics:
        if not isinstance(m, dict):
            continue
        col = METRIC_MAP.get(str(m.get("name", "")).lower())
        if not col:
            continue
        units = _units(m)
        for s in m.get("data") or []:
            if not isinstance(s, dict):
                continue
            d = parse_dt(s.get("date"))
            if not d:
                continue
            if col == "sleep_h":
                val = _num(s.get("asleep") or s.get("totalSleep") or s.get("qty"))
                if val is not None and (units in ("min", "minutes") or val > 24):
                    val = val / 60
                put(d.strftime("%Y-%m-%d"), col, val)
            else:
                raw = s.get("qty") if "qty" in s else s.get("Avg", s.get("value"))
                put(d.strftime("%Y-%m-%d"), col, _num(raw))
    return list(by_date.values())


def parse_payload(payload: dict):
    return parse_workouts(payload), parse_metrics(payload)
