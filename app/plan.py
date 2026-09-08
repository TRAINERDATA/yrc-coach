"""규칙 기반 훈련 처방 (Claude 없이 동작). 목표·주당 횟수·현재 페이스·회복 상태로 오늘과 이번 주 계획을 만든다."""
from __future__ import annotations

import re
from datetime import date

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def pace_str(sec) -> str:
    if not sec:
        return "-"
    m, s = divmod(int(round(sec)), 60)
    return f"{m}'{s:02d}\""


def parse_pace(s) -> int | None:
    """"5:30", "5'30\"", "5분30초", "530" 등을 초/km 로."""
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s*[:'′분]\s*(\d{1,2})", str(s))
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def parse_goal(goal: str | None) -> dict:
    """목표 문장에서 페이스/시간/거리를 뽑는다. 예) "5:30 페이스로 1시간", "10km 50분", "11월 하프 1:50" """
    g = (goal or "").strip()
    out = {"text": g, "pace_s": None, "duration_s": None, "distance_km": None}
    if not g:
        return out
    if "하프" in g or "half" in g.lower():
        out["distance_km"] = 21.1
    elif "풀" in g or "마라톤" in g and "하프" not in g:
        out["distance_km"] = 42.2
    dm = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|킬로)", g, re.I)
    if dm:
        out["distance_km"] = float(dm.group(1))
    hm = re.search(r"(\d+)\s*시간\s*(\d+)?\s*분?", g)
    if hm:
        out["duration_s"] = int(hm.group(1)) * 3600 + int(hm.group(2) or 0) * 60
    else:
        mm = re.search(r"(\d+)\s*분", g)
        if mm and not re.search(r"\d+\s*분\s*\d+\s*초", g):
            out["duration_s"] = int(mm.group(1)) * 60
    # "1:50" 처럼 시:분 표기 (거리 목표와 같이 쓰일 때)
    if out["duration_s"] is None and out["distance_km"] and out["distance_km"] >= 15:
        tm = re.search(r"\b(\d):(\d{2})\b", g)
        if tm:
            out["duration_s"] = int(tm.group(1)) * 3600 + int(tm.group(2)) * 60
    if "페이스" in g or "pace" in g.lower() or (out["distance_km"] is None and out["duration_s"] is None):
        out["pace_s"] = parse_pace(g)
    elif out["distance_km"] and out["duration_s"]:
        out["pace_s"] = round(out["duration_s"] / out["distance_km"])
    return out


def week_template(weekly_days: int) -> dict:
    """요일(0=월) -> 세션 종류. easy / quality / long / rest"""
    weekly_days = max(2, min(int(weekly_days or 4), 6))
    templates = {
        2: {1: "quality", 5: "long"},
        3: {1: "quality", 3: "easy", 5: "long"},
        4: {1: "quality", 3: "easy", 5: "long", 6: "easy"},
        5: {0: "easy", 1: "quality", 2: "easy", 4: "easy", 5: "long"},
        6: {0: "easy", 1: "quality", 2: "easy", 3: "tempo", 4: "easy", 5: "long"},
    }
    t = templates[weekly_days]
    return {d: t.get(d, "rest") for d in range(7)}


def paces(summary: dict, goal: dict) -> dict:
    """현재 체력 기준 훈련 페이스. 목표 페이스가 있으면 강도 세션을 그쪽으로 조금씩 당긴다."""
    cur = parse_pace(summary["trend"].get("avg_pace_last14")) or parse_pace(summary["trend"].get("avg_pace_prev14"))
    if not cur:
        recent = [r for r in summary.get("recent_runs", []) if r.get("pace") and r["pace"] != "-"]
        cur = parse_pace(recent[0]["pace"]) if recent else None
    if not cur:
        return {"cur": None, "easy": None, "long": None, "tempo": None, "interval": None}
    pz = (summary.get("fitness") or {}).get("paces_sec") or {}
    if pz.get("E") and pz.get("T") and pz.get("I"):
        tempo, interval = pz["T"], pz["I"]
        if goal.get("pace_s") and goal["pace_s"] > tempo:
            tempo = goal["pace_s"]  # 목표가 템포보다 느리면 목표 페이스로 유지 연습
        return {"cur": cur, "easy": pz["E"], "long": round((pz["E"] + pz.get("M", pz["E"])) / 2), "tempo": tempo, "interval": interval}
    easy = cur + 45
    long_ = cur + 30
    tempo = cur - 20
    interval = cur - 45
    if goal.get("pace_s"):
        gp = goal["pace_s"]
        tempo = max(gp, min(tempo, gp + 30)) if cur - gp <= 90 else cur - 25   # 목표가 멀면 현재 기준
        interval = max(gp - 15, interval)
    return {"cur": cur, "easy": easy, "long": long_, "tempo": tempo, "interval": interval}


def _week_index(d: date) -> int:
    return d.isocalendar()[1]


CADENCE_GOAL = 172  # 최종 목표 (분당 걸음). 160 미만은 낮음, 165~175 권장 범위.


def cadence_plan(summary: dict) -> dict:
    """케이던스 현황과 이번 주 목표. 2주 평균 + 3~5 씩 단계적으로 올린다 (한 번에 10% 이상 올리면 종아리 부상 위험)."""
    t = summary.get("trend") or {}
    avg, prev = t.get("cadence_last14"), t.get("cadence_prev14")
    if not avg:
        return {"avg": None, "prev": None, "target": None, "delta": None, "status": "no_data"}
    step = 5 if avg < 160 else (4 if avg < 168 else 3)
    target = min(CADENCE_GOAL, avg + step)
    delta = (avg - prev) if prev else None
    if avg >= CADENCE_GOAL:
        status = "reached"
    elif delta is not None and delta >= 2:
        status = "improving"
    elif delta is not None and delta <= -2:
        status = "dropping"
    else:
        status = "flat"
    yest = (summary.get("yesterday_runs") or [{}])[0].get("cadence")
    return {"avg": avg, "prev": prev, "target": target, "delta": delta, "status": status, "yesterday": yest,
            "goal": CADENCE_GOAL}


def cadence_cue(target: int | None, kind: str) -> str:
    if not target:
        return ""
    if kind in ("quality", "tempo"):
        return f" 빠른 구간은 케이던스 {target + 3}+ 로, 조깅 구간도 {target - 5} 아래로 떨어뜨리지 않기."
    if kind == "long":
        return f" 케이던스 {target} 유지가 오늘의 진짜 과제. 10분마다 20걸음 세어보기(=20초에 {round(target / 3)}걸음)."
    if kind == "easy":
        return f" 느리게 뛰되 케이던스는 {target} (메트로놈 {target}bpm 켜기). 마지막에 20초 스트라이드 4회, 케이던스 180 느낌으로."
    return ""


def session_text(kind: str, summary: dict, p: dict, goal: dict, today: date) -> str:
    weekly = summary["volume"]["last7_km"] or 0
    base = max(weekly, 12)  # 볼륨이 아주 적어도 최소 처방
    if kind == "rest":
        return "휴식. 가벼운 스트레칭이나 20분 걷기까지만."
    if kind == "easy":
        km = round(min(max(base * 0.18, 4), 10))
        return f"쉬운 러닝 {km}km · 페이스 {pace_str(p['easy'])} 전후 (대화 가능한 강도). 워밍업 걷기 3분, 마지막에 스트레칭 5분."
    if kind == "long":
        km = round(min(max(base * 0.3, 6), 18))
        return f"장거리 {km}km · 페이스 {pace_str(p['long'])} 로 일정하게. 후반 2km 만 {pace_str(p['long'] - 15)} 로 살짝 올려도 좋습니다."
    if kind == "tempo" or (kind == "quality" and _week_index(today) % 2 == 0):
        # 목표가 "일정 페이스로 N분" 이면 그 페이스로 유지 시간을 점진적으로 늘린다
        if goal.get("pace_s") and goal.get("duration_s"):
            step = (_week_index(today) // 2) % 4
            mins = [15, 20, 25, 30][step]
            return (f"템포 러닝: 워밍업 조깅 10분 + {mins}분 {pace_str(p['tempo'])} 유지 + 쿨다운 10분. "
                    f"목표 {pace_str(goal['pace_s'])} 로 {round(goal['duration_s'] / 60)}분 달리기를 향해 유지 시간을 늘려가는 단계입니다.")
        return f"템포 러닝: 워밍업 10분 + 20분 {pace_str(p['tempo'])} 유지 + 쿨다운 10분. '숨차지만 20분은 버틸 수 있는' 강도."
    # quality (인터벌)
    reps = 4 if base < 25 else (5 if base < 40 else 6)
    return (f"인터벌: 워밍업 10분 + (1km {pace_str(p['interval'])} + 2분 조깅) × {reps} + 쿨다운 10분. "
            f"마지막 반복도 첫 반복과 같은 페이스로 끝내는 게 목표.")


def build_plan(summary: dict) -> dict:
    """{'today': str, 'today_kind': str, 'week_lines': [str], 'paces': {...}, 'goal': {...}}"""
    today = date.fromisoformat(summary["date"])
    u = summary["user"]
    goal = parse_goal(u.get("goal"))
    p = paces(summary, goal)
    template = week_template(u.get("weekly_days") or 4)
    readiness = summary["recovery"]["readiness"]
    few_data = summary["data_points"]["runs_56d"] < 5

    kind = template[today.weekday()]
    days_since = summary.get("days_since_last_run")
    # 어제 강도 세션을 했으면 오늘 강도 세션은 쉬운 러닝으로 교체
    y = summary.get("yesterday_runs") or []
    y_hard = any(parse_pace(r.get("pace")) and p["tempo"] and parse_pace(r["pace"]) <= p["tempo"] + 5 for r in y)
    if kind in ("quality", "tempo") and y_hard:
        kind = "easy"
    if readiness == "rest":
        today_text, kind = "휴식 또는 20~30분 가벼운 걷기. 회복 지표(안정심박·HRV)가 평소로 돌아오면 내일 쉬운 러닝부터 재개.", "rest"
    elif not p["cur"] or few_data:
        today_text = "쉬운 러닝 30~40분, 대화 가능한 페이스(최대심박 65~75%). 아직 기준선을 쌓는 중이라 강도는 올리지 않습니다."
    elif readiness == "caution":
        if kind == "rest":
            today_text = session_text("rest", summary, p, goal, today)
        else:
            km = round(min(max((summary["volume"]["last7_km"] or 12) * 0.12, 3), 6))
            today_text = f"회복 러닝 {km}km · 페이스 {pace_str(p['easy'] + 15)} 이하로 아주 편하게. 강도 세션은 컨디션 회복 후로 미룹니다."
            kind = "easy"
    else:
        if kind == "rest" and days_since is not None and days_since >= 4:
            kind = "easy"  # 너무 오래 쉬었으면 휴식일이어도 가볍게
        today_text = session_text(kind, summary, p, goal, today)

    cad = cadence_plan(summary)
    if kind != "rest" and readiness != "rest":
        today_text += cadence_cue(cad.get("target"), kind)

    week_lines = []
    for d in range(today.weekday() + 1, 7):
        k = template[d]
        label = {"easy": "쉬운 러닝", "quality": "강도(인터벌/템포)", "tempo": "템포", "long": "장거리", "rest": "휴식"}[k]
        detail = ""
        if p["cur"]:
            if k == "easy":
                detail = f" {round(min(max((summary['volume']['last7_km'] or 12) * 0.18, 4), 10))}km @{pace_str(p['easy'])}"
            elif k == "long":
                detail = f" {round(min(max((summary['volume']['last7_km'] or 12) * 0.3, 6), 18))}km @{pace_str(p['long'])}"
            elif k in ("quality", "tempo"):
                detail = f" @{pace_str(p['tempo'])}~{pace_str(p['interval'])}"
        week_lines.append(f"{WEEKDAYS[d]}: {label}{detail}")
    return {"today": today_text, "today_kind": kind, "week_lines": week_lines, "paces": p, "goal": goal, "cadence": cad}


def goal_progress_line(summary: dict, plan: dict) -> str | None:
    g, p = plan["goal"], plan["paces"]
    if not (g.get("pace_s") and p.get("cur")):
        return None
    gap = p["cur"] - g["pace_s"]
    if gap <= 0:
        return f"최근 평균 페이스 {pace_str(p['cur'])} 로 이미 목표 페이스({pace_str(g['pace_s'])})에 도달했어요. 이제 유지 시간을 늘리는 게 과제입니다."
    return f"목표 {pace_str(g['pace_s'])} 까지 최근 평균 페이스({pace_str(p['cur'])})에서 {gap}초/km 남았어요. 템포 세션에서 {pace_str(p['tempo'])} 를 편하게 느끼는 게 다음 단계입니다."
