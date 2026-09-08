"""러닝 체력 지표: VDOT(Jack Daniels), 훈련 페이스, 예상 기록, 심박 존.

VDOT 는 Daniels & Gilbert 공식:
  VO2(v)   = -4.60 + 0.182258 v + 0.000104 v²        (v: m/min)
  %VO2max(t) = 0.8 + 0.1894393 e^(-0.012778 t) + 0.2989558 e^(-0.1932605 t)   (t: 분)
  VDOT = VO2 / %VO2max
"""
from __future__ import annotations

import math

# 훈련 강도 (VDOT 대비 %VO2max 의 대표값)
INTENSITY = {"E": 0.70, "M": 0.80, "T": 0.87, "I": 0.975, "R": 1.06}
RACES = {"5K": 5000, "10K": 10000, "하프": 21097.5, "풀": 42195}


def _vo2(v: float) -> float:
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def _frac(t_min: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot(distance_m: float, seconds: float) -> float | None:
    if not distance_m or not seconds or seconds <= 0 or distance_m < 1000:
        return None
    t = seconds / 60
    v = distance_m / t
    val = _vo2(v) / _frac(t)
    return round(val, 1) if 15 <= val <= 90 else None


def velocity_for_vo2(vo2: float) -> float:
    """VO2 → m/min (2차식 역산)"""
    a, b, c = 0.000104, 0.182258, -(4.60 + vo2)
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def training_paces(vdot_val: float) -> dict:
    """강도별 페이스 (초/km). E 는 범위(느린쪽~빠른쪽)."""
    out = {}
    for k, f in INTENSITY.items():
        v = velocity_for_vo2(vdot_val * f)
        out[k] = round(1000 / v * 60)
    v_slow = velocity_for_vo2(vdot_val * 0.62)
    out["E_slow"] = round(1000 / v_slow * 60)
    return out


def predict_time(vdot_val: float, distance_m: float) -> int:
    """주어진 VDOT 로 distance_m 를 달리는 예상 시간(초). t 에 대해 이분법."""
    lo, hi = 3.0, 600.0  # 분
    for _ in range(60):
        mid = (lo + hi) / 2
        v = distance_m / mid
        if _vo2(v) / _frac(mid) > vdot_val:  # 너무 빠른 가정 → 시간 늘림
            lo = mid
        else:
            hi = mid
    return round(hi * 60)


def race_predictions(vdot_val: float) -> dict:
    return {name: predict_time(vdot_val, d) for name, d in RACES.items()}


def hms(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def pace_str(sec_per_km) -> str:
    if not sec_per_km:
        return "-"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}'{s:02d}\""


def hr_zone(avg_hr: float, max_hr: float) -> int:
    """1~5 존 (최대심박 대비 %)"""
    if not avg_hr or not max_hr:
        return 0
    r = avg_hr / max_hr
    if r < 0.60:
        return 1
    if r < 0.70:
        return 2
    if r < 0.80:
        return 3
    if r < 0.90:
        return 4
    return 5


def hr_zone_bounds(max_hr: float) -> dict:
    return {z: (round(max_hr * lo), round(max_hr * hi)) for z, (lo, hi) in
            {1: (0.50, 0.60), 2: (0.60, 0.70), 3: (0.70, 0.80), 4: (0.80, 0.90), 5: (0.90, 1.0)}.items()}
