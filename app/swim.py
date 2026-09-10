"""수영 코치 (체중 감량 + 유산소). 분석 요약 · 훈련 처방 · 식단 · 브리핑 글.

핵심 지표
- 주간 수영 거리(m), 세션 수, 100m 페이스, 25m당 스트로크(효율), 심박, 소모 칼로리
- 핵심 과제 = 스트로크 효율 (같은 거리를 더 적은 스트로크로): 러닝의 케이던스에 해당
- 식단: Mifflin-St Jeor 기초대사량 × 활동계수 + 운동 소모 → 하루 목표 = 유지 - 500kcal (최소 1,400)
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from . import db

POOL_M = 25
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def pace100_str(sec_per_100):
    if not sec_per_100:
        return "-"
    m, s = divmod(int(round(sec_per_100)), 60)
    return f"{m}'{s:02d}\""


def _day(w):
    return datetime.fromisoformat(w["start"]).date()


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _pace100(w):
    m = w["distance_km"] * 1000
    return w["duration_s"] / (m / 100) if m and w.get("duration_s") else None


def _spl(w):  # strokes per length (25m)
    m = w["distance_km"] * 1000
    return w["strokes"] / (m / POOL_M) if w.get("strokes") and m else None


# ---------------- 분석 ----------------
def build_summary(user: dict, today: date | None = None) -> dict:
    today = today or date.today()
    max_hr = user.get("max_hr") or (220 - (user.get("age") or 30))
    sessions = db.workouts_since(user["id"], 56, sport="swim")

    def in_range(a, b):
        lo, hi = today - timedelta(days=a), today - timedelta(days=b)
        return [w for w in sessions if lo <= _day(w) < hi]

    last7, prev7, last28, last14, prev14 = in_range(7, 0), in_range(14, 7), in_range(28, 0), in_range(14, 0), in_range(28, 14)
    m7 = round(sum(w["distance_km"] for w in last7) * 1000)
    m_prev7 = round(sum(w["distance_km"] for w in prev7) * 1000)
    m28 = round(sum(w["distance_km"] for w in last28) * 1000)
    chronic = m28 / 4
    acwr = round(m7 / chronic, 2) if chronic >= 500 else None
    kcal7 = round(sum(w.get("energy_kcal") or 0 for w in last7))
    min7 = round(sum(w.get("duration_s") or 0 for w in last7) / 60)

    recent = []
    for w in sorted(last14, key=lambda x: x["start"], reverse=True)[:8]:
        p100, spl = _pace100(w), _spl(w)
        recent.append({
            "date": w["start"][:10], "time": w["start"][11:16], "m": round(w["distance_km"] * 1000),
            "time_min": round((w.get("duration_s") or 0) / 60), "pace100": pace100_str(p100), "pace100_s": round(p100) if p100 else None,
            "avg_hr": round(w["avg_hr"]) if w.get("avg_hr") else None, "spl": round(spl, 1) if spl else None,
            "swolf": round(p100 / 4 + spl) if (p100 and spl) else None, "kcal": round(w["energy_kcal"]) if w.get("energy_kcal") else None,
        })
    yesterday = [r for r in recent if r["date"] == (today - timedelta(days=1)).isoformat()]
    today_sessions = [r for r in recent if r["date"] == today.isoformat()]

    p_recent = _mean([_pace100(w) for w in last14])
    p_prev = _mean([_pace100(w) for w in prev14])
    spl_recent = _mean([_spl(w) for w in last14])
    spl_prev = _mean([_spl(w) for w in prev14])
    hr_recent = _mean([w.get("avg_hr") for w in last14])

    flags = []
    if acwr and acwr > 1.5:
        flags.append(f"훈련량 급증 (평소의 {round(acwr * 100)}%)")
    streak = 0
    d = today - timedelta(days=1)
    days = {_day(w) for w in sessions}
    while d in days:
        streak += 1
        d -= timedelta(days=1)
    if streak >= 6:
        flags.append(f"{streak}일 연속 수영")
    readiness = "caution" if flags else "good"

    weeks = []
    monday = today - timedelta(days=today.weekday())
    for i in range(7, -1, -1):
        ws = monday - timedelta(weeks=i)
        we = ws + timedelta(days=7)
        km = sum(w["distance_km"] for w in sessions if ws <= _day(w) < we)
        weeks.append({"label": f"{ws.month}/{ws.day}", "m": round(km * 1000)})

    return {
        "sport": "swim", "date": today.isoformat(), "weekday": WEEKDAYS[today.weekday()],
        "user": {k: user.get(k) for k in ("name", "goal", "weekly_days", "age", "weight_kg", "height_cm", "sex", "target_weight_kg", "activity", "diet_notes")} | {"max_hr": max_hr},
        "volume": {"last7_m": m7, "prev7_m": m_prev7, "last28_m": m28, "sessions_last7": len(last7), "sessions_last28": len(last28),
                   "acwr": acwr, "kcal_last7": kcal7, "min_last7": min7, "longest_last28_m": round(max((w["distance_km"] for w in last28), default=0) * 1000)},
        "trend": {"pace100_last14": pace100_str(p_recent), "pace100_prev14": pace100_str(p_prev), "pace100_last14_s": p_recent, "pace100_prev14_s": p_prev,
                  "spl_last14": spl_recent, "spl_prev14": spl_prev, "hr_last14": hr_recent},
        "recovery": {"flags": flags, "readiness": readiness, "today": {}, "baseline30d": {}},
        "yesterday_sessions": yesterday, "today_sessions": today_sessions, "recent_sessions": recent, "streak_days": streak,
        "charts": {"weeks": weeks},
        "fitness": {"max_hr": max_hr, "fat_zone": (round(max_hr * 0.60), round(max_hr * 0.75)), "aerobic_zone": (round(max_hr * 0.70), round(max_hr * 0.80))},
        "data_points": {"sessions_56d": len(sessions)},
    }


# ---------------- 식단 ----------------
def diet_plan(summary: dict) -> dict:
    u, v = summary["user"], summary["volume"]
    w, h, age, sex = u.get("weight_kg"), u.get("height_cm"), u.get("age") or 30, (u.get("sex") or "M").upper()
    act = {"sedentary": 1.3, "light": 1.45, "active": 1.6}.get(u.get("activity") or "sedentary", 1.3)
    out = {"personalized": bool(w and h)}
    if w and h:
        bmr = 10 * w + 6.25 * h - 5 * age + (5 if sex == "M" else -161)
        exercise_kcal_day = (v.get("kcal_last7") or 0) / 7
        tdee = bmr * act + exercise_kcal_day
        target = max(1400, round((tdee - 500) / 10) * 10)
        protein = round(w * 1.6)
        fat = round(target * 0.25 / 9)
        carbs = max(120, round((target - protein * 4 - fat * 9) / 4))
        out.update({"bmr": round(bmr), "tdee": round(tdee), "target_kcal": target, "protein_g": protein, "fat_g": fat, "carbs_g": carbs,
                    "exercise_kcal_day": round(exercise_kcal_day)})
        if u.get("target_weight_kg"):
            gap = round(w - u["target_weight_kg"], 1)
            out["to_goal_kg"] = gap
            out["weeks_to_goal"] = round(gap / 0.5) if gap > 0 else 0  # 주 0.5kg
    else:
        out.update({"target_kcal": 1800, "protein_g": 120, "fat_g": 50, "carbs_g": 210})
    # 점심이 구내식당처럼 고정 칼로리면 아침·저녁에서 나머지를 배분
    notes_txt = (u.get("diet_notes") or "")
    lunch_fixed = None
    if "구내" in notes_txt or "외식" in notes_txt or "고정" in notes_txt:
        import re
        m = re.search(r"(\d{3,4})\s*kcal", notes_txt)
        lunch_fixed = int(m.group(1)) if m else 1000
    target = out["target_kcal"]
    if lunch_fixed:
        rest = max(700, target - lunch_fixed)
        bk, dn = round(rest * 0.42 / 10) * 10, round(rest * 0.58 / 10) * 10
        out["split"] = {"아침": bk, "점심": lunch_fixed, "저녁": dn}
    else:
        out["split"] = {"아침": round(target * 0.28 / 10) * 10, "점심": round(target * 0.37 / 10) * 10, "저녁": round(target * 0.35 / 10) * 10}
    bk, dn = out["split"]["아침"], out["split"]["저녁"]

    def bk_menu(i):
        base = ["삶은 계란 2 + 바나나 1 + 우유 200ml", "그릭요거트 150g + 견과 한 줌 + 사과", "오트밀 40g + 우유 + 계란 1",
                "두유 1팩 + 삶은 계란 2 + 방울토마토", "통밀식빵 1장 + 계란 2 스크램블", "프로틴 쉐이크 + 바나나", "그릭요거트 + 블루베리 + 계란 1"][i]
        return base + ("" if bk >= 400 else " (양 조금 줄이기)") + f" ≈{bk}kcal"

    def dn_menu(i):
        rice = "잡곡밥 1/3공기" if dn < 550 else ("잡곡밥 1/2공기" if dn < 700 else "잡곡밥 2/3공기")
        base = [f"닭가슴살 150g + 샐러드 + {rice}", f"두부 200g + 구운 고등어 + 나물 + 미역국", f"소고기 살코기 130g + 채소볶음 + {rice}",
                f"연어 130g + 샐러드 + 고구마 100g", f"돼지 안심 130g + 구운 채소 + {rice}", f"두부김치(기름 적게) + 계란 1 + 된장국",
                f"닭가슴살 200g + 양배추 + 감자 1개"][i]
        return base + f" ≈{dn}kcal"

    lunch = (f"구내식당 ≈{lunch_fixed}kcal — 밥은 2/3만, 국물은 건더기만, 튀김·볶음 1개 이하, 단백질 반찬(생선·고기·두부) 먼저"
             if lunch_fixed else "잡곡밥 2/3 + 단백질 반찬 + 나물 2가지 (국물은 건더기만)")
    idx = date.fromisoformat(summary["date"]).toordinal() % 7
    out["meals"] = {"아침": bk_menu(idx), "점심": lunch, "저녁": dn_menu(idx)}
    out["notes"] = [
        "아침 수영 전: 바나나 1개 또는 꿀물 (공복은 40분 넘으면 힘 빠짐), 나머지 아침은 수영 후",
        "수영 직후 30분 내 단백질 20g (우유·계란·프로틴) — 근손실 없이 살 빼는 핵심",
        "저녁 수영 후 폭식 주의: 저녁을 수영 전에 가볍게 먹고, 후에는 단백질 위주 소량",
        "물 하루 2L 이상. 수영은 땀이 안 보여도 탈수됩니다",
        "구내식당 국·찌개는 건더기만. 국물 한 그릇이 200kcal에 나트륨 폭탄",
        "주 0.5~0.7kg 감량이 정상 속도. 더 빠르면 근육이 빠지고 요요가 옵니다",
    ]
    return out


# ---------------- 훈련 처방 ----------------
def session_plan(summary: dict) -> dict:
    """아침/저녁 두 세션. 체중 감량 목적: 대부분 심박 60~75% 지속 + 주 2회 인터벌."""
    today = date.fromisoformat(summary["date"])
    wd = today.weekday()
    v, t = summary["volume"], summary["trend"]
    fz = summary["fitness"]["fat_zone"]
    notes = f"{summary['user'].get('diet_notes') or ''} {summary['user'].get('goal') or ''}"
    beginner = "초보" in notes or "처음" in notes or v["sessions_28d" if "sessions_28d" in v else "sessions_last28"] < 6
    if v["sessions_last28"]:
        base_m = max(600, min(2500, round((v["last28_m"] / max(v["sessions_last28"], 1)) / 100) * 100))
    else:
        base_m = 700 if beginner else 1000
    p100 = t.get("pace100_last14_s")
    easy_p = pace100_str(p100 + 15) if p100 else "편한 페이스"
    fast_p = pace100_str(p100 - 10) if p100 else "조금 빠르게"
    readiness = summary["recovery"]["readiness"]
    rest_note = "25m마다 15~20초 쉬어도 OK" if beginner else "가능한 쉬지 않고"

    am = f"지속 40~45분 · 자유형 50/평영 50 교대 · 총 {base_m}m ({rest_note}) · 심박 {fz[0]}~{fz[1]} (대화 가능)"
    if beginner:
        pm_by_day = {
            0: f"인터벌 · 몸풀기 100m + 자유형 25m×10 ({fast_p}, 쉬기 20초) + 평영 25m×6 + 정리 100m",
            1: f"지속 · 평영 위주 {base_m + 100}m · 50m마다 15초 쉬기 · 편하게 오래",
            2: f"자유형 집중 · 50m×8 (쉬기 30초) + 평영 200m 정리 · 호흡 2번에 1번",
            3: "기술 · 킥판 25m×8 + 한 팔 자유형 25m×6 + 평영 글라이드(킥 후 1초 멈춤) 25m×8",
            4: f"지속 · {base_m + 200}m · 100m마다 20초 쉬기 · 후반 100m만 {fast_p}",
            5: f"장거리 · {round(base_m * 1.4 / 100) * 100}m 자유형/평영 교대 · 쉬는 시간 포함 50분 · 심박 {fz[0]}~{fz[1]}",
            6: "휴식 · 어깨·등 스트레칭 10분",
        }
    else:
        pm_by_day = {
            0: f"인터벌 · 워밍업 200m + 자유형 100m×8 ({fast_p}, 휴식 20초) + 평영 200m 쿨다운",
            1: f"지속 · 자유형/평영 자유롭게 {base_m + 200}m 쉬지 않고 · {easy_p} 페이스",
            2: "피라미드 · 100-200-300-200-100m 자유형 (휴식 30초) + 평영 200m",
            3: "기술 · 킥판 25m×8 + 캐치업 드릴 25m×8 + 평영 글라이드 25m×8 (효율 훈련)",
            4: f"지속 · {base_m + 400}m 한 번에 · 후반 200m 만 {fast_p}",
            5: f"장거리 · {round(base_m * 1.5 / 100) * 100}m 자유형/평영 교대 · 심박 {fz[0]}~{fz[1]}",
            6: "휴식 · 가벼운 스트레칭. 수영은 어깨 회복이 중요합니다",
        }
    pm = pm_by_day[wd]
    if readiness != "good":
        am = f"가볍게 30분 · 평영 위주 {max(500, base_m - 300)}m · 심박 {fz[0]} 이하"
        pm = "휴식 또는 스트레칭 (훈련량이 평소보다 많아서 하루는 쉬는 게 낫습니다)"
    if wd == 6:
        am = "휴식 (주 1회는 완전히 쉬어야 지방 연소 호르몬이 회복됩니다)"
    week_lines = []
    for d in range(wd + 1, 7):
        week_lines.append(f"{WEEKDAYS[d]} " + pm_by_day[d].split(" · ")[0])
    return {"am": am, "pm": pm, "week_lines": week_lines, "base_m": base_m, "fat_zone": fz, "beginner": beginner}


def tomorrow_summary(summary: dict) -> dict:
    """저녁 브리핑용: 날짜만 내일로 바꾼 요약 (계획·식단 로테이션에 사용)."""
    s = dict(summary)
    t = date.fromisoformat(summary["date"]) + timedelta(days=1)
    s["date"], s["weekday"] = t.isoformat(), WEEKDAYS[t.weekday()]
    return s


def efficiency_plan(summary: dict) -> dict:
    """스트로크 효율 (25m당 스트로크). 자유형 초보 22~25 → 목표 18 이하."""
    t = summary["trend"]
    spl, prev = t.get("spl_last14"), t.get("spl_prev14")
    if not spl:
        return {"spl": None}
    target = max(16, round(spl - 1))
    delta = round(spl - prev, 1) if prev else None
    status = "좋아지는 중" if (delta is not None and delta <= -0.5) else ("나빠짐" if (delta is not None and delta >= 0.5) else "유지")
    tips = [
        "손 입수 후 앞으로 쭉 뻗어 글라이드 한 박자. 조급하게 젓지 않기",
        "머리를 물속에 두고 시선은 바닥 45도. 고개 들면 하체가 가라앉아 스트로크가 늘어요",
        "평영은 킥 후 '글라이드 1-2초' 세고 다음 스트로크. 팔은 작게, 킥으로 나가기",
        "자유형 롤링: 어깨를 좌우로 굴리며 팔을 멀리 뻗기. 손끝은 물 아래로 잡아당기기",
        "25m마다 스트로크 세기. 숫자를 알면 저절로 줄어듭니다",
    ]
    return {"spl": spl, "prev": prev, "target": target, "delta": delta, "status": status,
            "tip": tips[date.fromisoformat(summary["date"]).toordinal() % len(tips)]}


# ---------------- 브리핑 글 ----------------
def _session_line(y: dict) -> str:
    s = f"{y['m']:,}m {y['time_min']}분 · 100m {y['pace100']}"
    if y.get("avg_hr"):
        s += f" ♥{y['avg_hr']}"
    if y.get("spl"):
        s += f" · 25m당 {y['spl']}스트로크"
    if y.get("kcal"):
        s += f" · {y['kcal']}kcal"
    return s


def briefing_text(summary: dict, mode: str = "morning") -> str:
    v, r = summary["volume"], summary["recovery"]
    d = summary["date"]
    ready = {"good": "좋음", "caution": "주의", "rest": "휴식"}[r["readiness"]]
    ef = efficiency_plan(summary)
    lines = []

    if mode == "evening":
        head = f"🌙 {int(d[5:7])}/{int(d[8:10])}({summary['weekday']}) 저녁 수영 브리핑"
        lines.append(head)
        ts = summary.get("today_sessions") or []
        if ts:
            lines.append("오늘 " + " / ".join(_session_line(y) for y in ts[:2]))
            total_kcal = sum(y.get("kcal") or 0 for y in ts)
            if total_kcal:
                lines.append(f"오늘 소모 {total_kcal:,}kcal · 저녁은 단백질 위주 소량, 야식 금지")
        else:
            lines.append("오늘 수영 기록이 아직 없어요 (단축어가 22:30에 보냅니다)")
        lines.append("")
        tm = tomorrow_summary(summary)
        sp = session_plan(tm)
        lines.append(f"🌅 내일 아침: {sp['am']}")
        lines.append(f"🌙 내일 저녁: {sp['pm']}")
        if ef.get("spl"):
            lines.append(f"🏊 효율: 25m당 {ef['spl']}스트로크 → 목표 {ef['target']} · 내일 첫 100m는 스트로크 세면서")
        diet = diet_plan(tm)
        m = diet["meals"]
        lines.append(f"🍽 내일 {diet['target_kcal']:,}kcal (아침 {diet['split']['아침']} · 점심 {diet['split']['점심']} · 저녁 {diet['split']['저녁']})")
        lines.append(f"아침 {m['아침']} / 저녁 {m['저녁']}")
        lines.append(f"⚖️ 이번 주 {v['last7_m']:,}m · {v['kcal_last7']:,}kcal 소모")
        return "\n".join(lines)

    head = f"🏊 {int(d[5:7])}/{int(d[8:10])}({summary['weekday']}) 수영 브리핑 · 컨디션 {ready}"
    if r["flags"]:
        head += f" · {r['flags'][0]}"
    lines.append(head)
    ys = summary.get("yesterday_sessions") or []
    if ys:
        lines.append("어제 " + " / ".join(_session_line(y) for y in ys[:2]))
    elif summary["data_points"]["sessions_56d"] == 0:
        lines.append("아직 수영 기록이 없어요. 단축어가 데이터를 보내면 여기에 나옵니다")
    lines.append("")
    sp = session_plan(summary)
    lines.append(f"🌅 아침: {sp['am']}")
    lines.append(f"🌙 저녁: {sp['pm']}")
    if ef.get("spl"):
        trend = f" ({'+' if ef['delta'] >= 0 else ''}{ef['delta']} vs 2주 전)" if ef.get("delta") is not None else ""
        lines.append(f"🏊 효율: 25m당 {ef['spl']}스트로크{trend} → 목표 {ef['target']} · {ef['status']}")
        lines.append(f"💡 {ef['tip']}")
    elif sp.get("beginner"):
        lines.append("💡 초보 2주 적응기: 거리보다 '물에서 편해지기'. 숨이 차면 바로 쉬고, 평영으로 바꿔도 됩니다")
    diet = diet_plan(summary)
    m = diet["meals"]
    kcal_line = f"🍽 오늘 {diet['target_kcal']:,}kcal · 단백질 {diet['protein_g']}g (아침 {diet['split']['아침']} · 점심 {diet['split']['점심']} · 저녁 {diet['split']['저녁']})"
    if not diet["personalized"]:
        kcal_line += " (키·체중 입력 전 기본값)"
    lines.append(kcal_line)
    lines.append(f"아침 {m['아침']}")
    lines.append(f"점심 {m['점심']}")
    lines.append(f"저녁 {m['저녁']}")
    lines.append("📌 " + diet["notes"][date.fromisoformat(d).toordinal() % len(diet["notes"])])
    if sp["week_lines"]:
        lines.append("📅 " + " · ".join(sp["week_lines"]))
    tail = f"⚖️ 이번 주 {v['last7_m']:,}m · {v['min_last7']}분 · {v['kcal_last7']:,}kcal 소모"
    if diet.get("to_goal_kg") is not None:
        tail += f" · 목표까지 {diet['to_goal_kg']}kg (주 0.5kg 기준 {diet['weeks_to_goal']}주)"
    lines.append(tail)
    return "\n".join(lines)
