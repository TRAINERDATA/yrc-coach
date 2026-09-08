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
from datetime import datetime, timedelta
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
    if isinstance(v, dict):
        return str(v.get("units") or "").lower()
    if isinstance(v, str):  # 단축어가 보내는 "6.42 km", "6,420 m", "3.9 mi" 형태
        m = re.search(r"[a-zA-Z]+\s*$", v.strip())
        return m.group().strip().lower() if m else ""
    return ""


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
        pass
    # 한국식: "2026. 9. 7. 오전 6:00", "2026년 9월 7일 오후 3:05:10", "9/7/26, 6:00 AM"
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        rest = s[m.end():]
        t = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", rest)
        hh, mm, ss = (int(t.group(1)), int(t.group(2)), int(t.group(3) or 0)) if t else (0, 0, 0)
        a = re.search(r"오전|오후|AM|PM", rest, re.I)
        ampm = a.group().upper() if a else ""
        if ampm in ("오후", "PM") and hh < 12:
            hh += 12
        if ampm in ("오전", "AM") and hh == 12:
            hh = 0
        try:
            return datetime(y, mo, d, hh, mm, ss)
        except ValueError:
            return None
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


def _speed_kmh(v: Any) -> Optional[float]:
    """'10.6 km/h', '2.9 m/s', '5:40 /km' 같은 표기를 km/h 로."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    m = re.match(r"(\d+):(\d{1,2})", s)  # 분:초 /km 페이스
    if m and ("/km" in s or "min" in s):
        sec = int(m.group(1)) * 60 + int(m.group(2))
        return 3600 / sec if sec else None
    q = _num(s)
    if q is None:
        return None
    if "m/s" in s:
        return q * 3.6
    if "min/km" in s or "/km" in s:
        return 60 / q if q else None
    if "mph" in s or "mi/h" in s:
        return q * 1.609344
    return q


def _hour_key(s: Any) -> Optional[str]:
    d = parse_dt(s)
    return d.strftime("%Y-%m-%dT%H:00:00") if d else None


def parse_hourly(payload: dict) -> list:
    """단축어가 보내는 '시간별 그룹' 샘플로 러닝을 복원한다 (iOS 단축어는 운동 기록을 직접 못 꺼내므로).

    {"hourly": {"speed": [{"start": "...", "value": "10.6 km/h"}], "distance": [{"start","value":"6.4 km"}],
                "hr": [{"start","value":"148 count/min"}]}}
    - 달리기 속도 샘플은 애플워치 러닝 워크아웃 중에만 기록되므로 그 시간대 = 러닝.
    - 연속된 시간대는 한 번의 러닝으로 합치고, 거리는 그 시간대 걷기+달리기 거리 합, 시간은 거리/속도로 추정.
    """
    h = payload.get("hourly")
    if not isinstance(h, dict):
        return []

    def items(name: str) -> list:
        """단축어가 [[...]] 로 한 겹 더 싸거나, 사전을 JSON 문자열로 보내도 풀어준다."""
        raw = h.get(name) or []
        if isinstance(raw, (dict, str)):
            raw = [raw]
        out = []
        for x in raw:
            if isinstance(x, list):
                out.extend(x)
            else:
                out.append(x)
        import json
        fixed = []
        for x in out:
            if isinstance(x, str):
                # 단축어는 목록을 "{...}\n{...}\n{...}" 한 덩어리 문자열로 보낸다
                for line in x.splitlines():
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            fixed.append(json.loads(line))
                        except ValueError:
                            pass
            else:
                fixed.append(x)
        return fixed

    def lines(v) -> list:
        if v is None:
            return []
        if isinstance(v, list):
            out = []
            for x in v:
                out += lines(x)
            return out
        return [ln.strip() for ln in str(v).splitlines() if ln.strip()]

    def table(name: str, conv):
        out = {}
        for s in items(name):  # 형식 1: [{"start","value"}, ...] (반복문 방식)
            if not isinstance(s, dict):
                continue
            k = _hour_key(s.get("start") or s.get("date"))
            v = conv(s.get("value") if "value" in s else s.get("qty"))
            if k and v is not None:
                out[k] = v
        # 형식 2: "<name>_dates" / "<name>_values" 줄바꿈 목록 (반복문 없는 빠른 방식)
        dates, values = lines(h.get(f"{name}_dates")), lines(h.get(f"{name}_values"))
        if dates and values and len(dates) == len(values):
            for d, v in zip(dates, values):
                k, val = _hour_key(d), conv(v)
                if k and val is not None:
                    out[k] = val
        elif dates or values:
            import logging
            logging.getLogger(__name__).warning("hourly %s: dates=%d values=%d 개수 불일치", name, len(dates), len(values))
        return out

    speed = table("speed", _speed_kmh)
    dist = table("distance", lambda v: _num(v) / 1000 if _units(v) in ("m", "meters") else _num(v))
    hr = table("hr", _num)

    run_hours = sorted(k for k, v in speed.items() if v >= 5.5)
    runs, block = [], []
    for k in run_hours:
        if block and (parse_dt(k) - parse_dt(block[-1])).total_seconds() > 3600:
            runs.append(block)
            block = []
        block.append(k)
    if block:
        runs.append(block)

    out = []
    for hours in runs:
        d_km = sum(dist.get(k, 0) for k in hours)
        v = sum(speed[k] for k in hours) / len(hours)
        if d_km < 1.0 or not v:
            continue
        dur = d_km / v * 3600
        hrs = [hr[k] for k in hours if hr.get(k)]
        start = parse_dt(hours[0])
        out.append({
            "start": start.isoformat(timespec="seconds"),
            "end": (start + timedelta(seconds=dur)).isoformat(timespec="seconds"),
            "duration_s": round(dur), "distance_km": round(d_km, 3),
            "avg_hr": round(sum(hrs) / len(hrs), 1) if hrs else None, "max_hr": None,
            "energy_kcal": None, "elev_gain_m": None, "source": "shortcut_hourly",
            "raw": {"hours": hours, "speed_kmh": round(v, 2), "note": "시간별 샘플로 복원한 근사치"},
        })
    return out


def parse_body(body: bytes):
    """요청 본문이 JSON 이면 그대로, 아니면 '##이름' 구역으로 나뉜 텍스트를 hourly 사전으로 변환.

    ##speed_dates
    2026-09-08T20:05:49+09:00
    ##speed_values
    10.06 km/h
    ...
    """
    import json
    text = body.decode("utf-8", errors="replace").lstrip("﻿").strip()
    if not text:
        return {}
    if text[0] in "{[":
        try:
            return json.loads(text)
        except ValueError:
            pass
    sections, current = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("##"):
            current = s[2:].strip().lower()
            sections[current] = []
        elif current and s:
            sections[current].append(s)
    if not sections:
        return {}
    return {"hourly": {k: "\n".join(v) for k, v in sections.items()}}


def hourly_counts(payload: dict) -> dict:
    """디버깅용: 시간별 샘플이 종류별로 몇 시간대 들어왔는지."""
    h = payload.get("hourly")
    if not isinstance(h, dict):
        return {}
    counts = {}
    for name in ("speed", "distance", "hr"):
        raw = h.get(name) or h.get(f"{name}_dates") or []
        if isinstance(raw, (dict, str)):
            raw = [raw]
        n = 0
        for x in raw:
            if isinstance(x, str):
                n += sum(1 for line in x.splitlines() if line.strip())
            elif isinstance(x, list):
                n += len(x)
            else:
                n += 1
        counts[name] = n
    return counts


def parse_payload(payload: dict):
    workouts = parse_workouts(payload) + parse_hourly(payload)
    return workouts, parse_metrics(payload)
