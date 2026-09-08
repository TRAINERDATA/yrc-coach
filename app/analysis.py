"""러닝 데이터 분석. 코치(LLM)에 넘길 요약 JSON 을 만든다.

핵심 지표
- 주간 거리 / 직전 주 대비 증감 / 4주 평균
- ACWR(급성:만성 부하비) = 최근 7일 거리 / (최근 28일 거리 / 4)   → 0.8~1.3 안전, 1.5↑ 부상 위험
- 훈련 부하(TRIMP 근사) = 분 × (평균심박 / 최대심박)
- 회복 지표 = 안정심박·HRV·수면을 30일 기준선과 비교
- 페이스 추세 = 최근 2주 vs 이전 2주 (심박 보정 없이 단순 비교)
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from . import db


def pace_str(sec_per_km) -> str:
    if not sec_per_km:
        return "-"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}'{s:02d}\""


def _pace(w: dict):
    if w.get("distance_km") and w.get("duration_s"):
        return w["duration_s"] / w["distance_km"]
    return None


def _day(w: dict) -> date:
    return datetime.fromisoformat(w["start"]).date()


def _load(w: dict, max_hr: float) -> float:
    minutes = (w.get("duration_s") or 0) / 60
    if w.get("avg_hr") and max_hr:
        return round(minutes * (w["avg_hr"] / max_hr), 1)
    return round(minutes * 0.7, 1)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def build_summary(user: dict, today: date | None = None) -> dict:
    today = today or date.today()
    max_hr = user.get("max_hr") or (220 - (user.get("age") or 35))
    runs = db.workouts_since(user["id"], 56)
    metrics = db.metrics_since(user["id"], 35)

    def in_range(days_back_from: int, days_back_to: int):
        lo, hi = today - timedelta(days=days_back_from), today - timedelta(days=days_back_to)
        return [w for w in runs if lo <= _day(w) < hi]

    last7 = in_range(7, 0)
    prev7 = in_range(14, 7)
    last28 = in_range(28, 0)
    last14 = in_range(14, 0)
    prev14 = in_range(28, 14)

    km7 = round(sum(w["distance_km"] for w in last7), 1)
    km_prev7 = round(sum(w["distance_km"] for w in prev7), 1)
    km28 = round(sum(w["distance_km"] for w in last28), 1)
    chronic_weekly = km28 / 4 if km28 else 0
    acwr = round(km7 / chronic_weekly, 2) if chronic_weekly >= 5 else None

    daily_load = {}
    for w in last7:
        daily_load[_day(w)] = daily_load.get(_day(w), 0) + _load(w, max_hr)
    loads = [daily_load.get(today - timedelta(days=i), 0) for i in range(1, 8)]
    monotony = round(statistics.mean(loads) / statistics.pstdev(loads), 2) if len(loads) > 1 and statistics.pstdev(loads) > 0 else None

    # 최근 러닝 목록 (코치가 볼 것)
    recent = []
    for w in sorted(last14, key=lambda x: x["start"], reverse=True)[:10]:
        recent.append({
            "date": w["start"][:10],
            "km": round(w["distance_km"], 2),
            "time_min": round((w.get("duration_s") or 0) / 60, 1),
            "pace": pace_str(_pace(w)),
            "avg_hr": round(w["avg_hr"]) if w.get("avg_hr") else None,
            "max_hr": round(w["max_hr"]) if w.get("max_hr") else None,
            "elev_m": round(w["elev_gain_m"]) if w.get("elev_gain_m") else None,
            "load": _load(w, max_hr),
        })

    yesterday = [w for w in runs if _day(w) == today - timedelta(days=1)]
    last_run_day = max((_day(w) for w in runs), default=None)
    days_since_run = (today - last_run_day).days if last_run_day else None

    # 연속 러닝 일수
    streak = 0
    d = today - timedelta(days=1)
    run_days = {_day(w) for w in runs}
    while d in run_days:
        streak += 1
        d -= timedelta(days=1)

    # 페이스 추세 (5~12km 정도의 일반 러닝만)
    def avg_pace(ws):
        ps = [_pace(w) for w in ws if 3 <= w["distance_km"] <= 15 and _pace(w)]
        return round(sum(ps) / len(ps)) if ps else None

    p_recent, p_prev = avg_pace(last14), avg_pace(prev14)
    pace_delta = (p_recent - p_prev) if p_recent and p_prev else None

    # 심박 효율: 같은 페이스대에서 심박이 내려가면 좋아지는 것
    def hr_per_speed(ws):
        vals = [w["avg_hr"] / (3600 / _pace(w)) for w in ws if w.get("avg_hr") and _pace(w)]
        return round(sum(vals) / len(vals), 1) if vals else None

    eff_recent, eff_prev = hr_per_speed(last14), hr_per_speed(prev14)

    # 회복 지표
    m_by_date = {m["date"]: m for m in metrics}
    today_m = m_by_date.get(today.isoformat()) or m_by_date.get((today - timedelta(days=1)).isoformat()) or {}
    base = [m for m in metrics if m["date"] < today.isoformat()]
    baseline = {
        "resting_hr": _mean([m.get("resting_hr") for m in base]),
        "hrv": _mean([m.get("hrv") for m in base]),
        "sleep_h": _mean([m.get("sleep_h") for m in base]),
    }
    body_flags, load_flags = [], []  # 몸 상태 경고 / 훈련 부하 경고
    if today_m.get("resting_hr") and baseline["resting_hr"] and today_m["resting_hr"] > baseline["resting_hr"] * 1.05:
        body_flags.append(f"안정심박 상승 ({today_m['resting_hr']:.0f} vs 평소 {baseline['resting_hr']:.0f})")
    if today_m.get("hrv") and baseline["hrv"] and today_m["hrv"] < baseline["hrv"] * 0.75:
        body_flags.append(f"HRV 저하 ({today_m['hrv']:.0f} vs 평소 {baseline['hrv']:.0f})")
    if today_m.get("sleep_h") and today_m["sleep_h"] < 6:
        body_flags.append(f"수면 부족 ({today_m['sleep_h']:.1f}h)")
    if acwr and acwr > 1.4:
        load_flags.append(f"부하 급증 ACWR {acwr}")
    if streak >= 5:
        load_flags.append(f"{streak}일 연속 러닝")
    if km_prev7 and km7 > km_prev7 * 1.25 and km7 - km_prev7 > 5:
        load_flags.append(f"주간 거리 {round((km7 / km_prev7 - 1) * 100)}% 증가")
    flags = body_flags + load_flags

    # 몸 상태 경고가 2개 이상이거나, 몸 상태 + 부하 경고가 같이 있으면 휴식. 그 외 경고가 있으면 주의.
    if len(body_flags) >= 2 or (body_flags and load_flags):
        readiness = "rest"
    elif flags:
        readiness = "caution"
    else:
        readiness = "good"

    return {
        "date": today.isoformat(),
        "weekday": ["월", "화", "수", "목", "금", "토", "일"][today.weekday()],
        "user": {
            "name": user["name"], "goal": user.get("goal"), "weekly_days": user.get("weekly_days"),
            "age": user.get("age"), "max_hr": max_hr, "notes": user.get("notes"),
        },
        "volume": {
            "last7_km": km7, "prev7_km": km_prev7, "last28_km": km28,
            "runs_last7": len(last7), "runs_last28": len(last28),
            "longest_last28_km": round(max((w["distance_km"] for w in last28), default=0), 1),
            "acwr": acwr, "monotony": monotony,
        },
        "trend": {
            "avg_pace_last14": pace_str(p_recent), "avg_pace_prev14": pace_str(p_prev),
            "pace_delta_sec_per_km": pace_delta,
            "hr_per_kmh_last14": eff_recent, "hr_per_kmh_prev14": eff_prev,
        },
        "recovery": {
            "today": {k: today_m.get(k) for k in ("resting_hr", "hrv", "sleep_h", "steps")},
            "baseline30d": baseline,
            "flags": flags, "readiness": readiness,
        },
        "yesterday_runs": [r for r in recent if r["date"] == (today - timedelta(days=1)).isoformat()],
        "days_since_last_run": days_since_run,
        "streak_days": streak,
        "recent_runs": recent,
        "data_points": {"runs_56d": len(runs), "metric_days_35d": len(metrics)},
    }
