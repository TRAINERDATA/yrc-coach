"""삼성 헬스(Samsung Health) '개인 데이터 다운로드' 파일에서 러닝 기록 읽기 (갤럭시 크루원용).

삼성 헬스 앱 → 설정 → 개인 데이터 다운로드 → zip 안의
  com.samsung.shealth.exercise.<날짜>.csv  (또는 com.samsung.health.exercise...)
첫 줄은 메타데이터, 둘째 줄이 헤더. 시각은 UTC 이고 time_offset 컬럼(UTC+0900)으로 보정한다.
exercise_type: 1002 = 달리기, 1001 = 걷기, 14001 = 수영 ...
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timedelta

RUN_TYPES = {"1002", "1002.0", "running", "run"}


def _find_col(header: list, *suffixes: str):
    for i, h in enumerate(header):
        hl = h.strip().lower()
        for s in suffixes:
            if hl == s or hl.endswith("." + s) or hl.endswith("_" + s) and hl.split(".")[-1] == s:
                return i
    for i, h in enumerate(header):
        hl = h.strip().lower()
        if any(hl.endswith(s) for s in suffixes):
            return i
    return None


def _parse_time(s: str, offset: str | None) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = datetime.strptime(s[:26], fmt)
            break
        except ValueError:
            d = None
    if d is None:
        return None
    m = re.match(r"UTC([+-])(\d{2})(\d{2})", (offset or "").strip())
    if m:
        sign = 1 if m.group(1) == "+" else -1
        d = d + sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    else:
        d = d + timedelta(hours=9)  # 오프셋 정보가 없으면 한국 시각으로 가정
    return d


def parse_csv_text(text: str) -> list:
    lines = text.splitlines()
    if not lines:
        return []
    # 첫 줄이 메타데이터(헤더 아님)면 건너뜀
    start = 1 if (lines[0].lower().startswith("com.samsung") and "start_time" not in lines[0].lower()) else 0
    reader = csv.reader(io.StringIO("\n".join(lines[start:])))
    rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    ci = {
        "start": _find_col(header, "start_time"), "end": _find_col(header, "end_time"),
        "dur": _find_col(header, "duration"), "dist": _find_col(header, "distance"),
        "type": _find_col(header, "exercise_type"), "hr": _find_col(header, "mean_heart_rate"),
        "hrmax": _find_col(header, "max_heart_rate"), "kcal": _find_col(header, "calorie"),
        "off": _find_col(header, "time_offset"), "title": _find_col(header, "title"),
        "cad": _find_col(header, "mean_cadence"), "count": _find_col(header, "count"),
    }
    if ci["start"] is None or ci["dist"] is None:
        return []

    def get(row, key):
        i = ci[key]
        return row[i].strip() if i is not None and i < len(row) else ""

    out = []
    for row in rows[1:]:
        if not row or len(row) < 3:
            continue
        et = get(row, "type").lower()
        title = get(row, "title").lower()
        if et not in RUN_TYPES and "run" not in title and "달리기" not in title and "러닝" not in title:
            continue
        start = _parse_time(get(row, "start"), get(row, "off"))
        if not start:
            continue
        end = _parse_time(get(row, "end"), get(row, "off"))
        try:
            dist_km = float(get(row, "dist") or 0) / 1000
        except ValueError:
            continue
        try:
            dur = float(get(row, "dur") or 0) / 1000  # ms → s
        except ValueError:
            dur = 0
        if not dur and end:
            dur = (end - start).total_seconds()
        if dist_km < 0.3 or dur <= 0:
            continue

        def num(key):
            try:
                v = float(get(row, key))
                return v if v > 0 else None
            except ValueError:
                return None

        cadence = num("cad")
        if not cadence and num("count") and dur:
            cadence = round(num("count") / (dur / 60))
        if cadence and not 120 <= cadence <= 220:
            cadence = None
        out.append({
            "start": start.isoformat(timespec="seconds"),
            "end": (end or start + timedelta(seconds=dur)).isoformat(timespec="seconds"),
            "duration_s": round(dur), "distance_km": round(dist_km, 3),
            "avg_hr": num("hr"), "max_hr": num("hrmax"), "energy_kcal": num("kcal"), "elev_gain_m": None,
            "cadence": round(cadence) if cadence else None,
            "source": "samsung_health", "raw": {"exercise_type": et},
        })
    return out


def parse_upload(filename: str, data: bytes) -> list:
    """zip(삼성 헬스 다운로드 전체) 또는 csv 한 개."""
    name = (filename or "").lower()
    if name.endswith(".zip") or data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        out = []
        for n in z.namelist():
            nl = n.lower()
            if "exercise" in nl and nl.endswith(".csv") and "pace" not in nl and "live" not in nl:
                out += parse_csv_text(z.read(n).decode("utf-8", errors="replace"))
        return out
    return parse_csv_text(data.decode("utf-8", errors="replace"))
