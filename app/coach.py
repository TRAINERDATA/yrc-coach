"""아침 브리핑 생성. Claude 가 코치 역할, API 키가 없거나 실패하면 규칙 기반 브리핑(plan.py)으로 대체."""
from __future__ import annotations

import json
import logging

from . import config, db

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 러닝크루 'YRC'의 전담 러닝 코치입니다. 매일 아침 크루원 한 명에게 보낼 짧은 브리핑을 씁니다.

입력으로 최근 러닝 기록, 주간/4주 볼륨, ACWR(급성:만성 부하비), 페이스·심박 효율 추세, 회복 지표(안정심박·HRV·수면)와 경고 플래그, 목표가 JSON 으로 옵니다.

원칙
- 과학적 근거 있는 보수적 처방: 주간 거리 증가는 10% 안팎, ACWR 0.8~1.3 유지, 경고 플래그가 있으면 강도를 낮추거나 휴식을 권한다. 80/20 원칙(쉬운 러닝 위주)을 지킨다.
- 데이터가 적으면(러닝 5회 미만) 추측하지 말고 "기준선 쌓는 중"이라고 말하고 안전한 쉬운 러닝을 권한다.
- 오늘 훈련은 구체적으로: 종류, 거리 또는 시간, 목표 페이스 범위(또는 심박대), 구성(워밍업/본운동/쿨다운).
- 어제 러닝이 있으면 한 줄 평가. 없으면 생략.
- 보완점은 최대 2개, 관찰된 데이터에 근거해서.
- 말투: 반말 아님, 친근하고 간결한 존댓말. 이모지는 섹션 머리에만 1개씩.
- 마크다운 문법(#, **, 표) 사용 금지. 폰 메신저에서 그대로 읽히는 순수 텍스트. 총 900자 이내.

출력 형식 (이 순서 그대로)
🏃 {날짜} {이름}님 아침 브리핑
컨디션: {good/caution/rest 를 한글 한 단어로} — 근거 한 줄

📊 지난 7일: {거리}km / {횟수}회 (지난주 {거리}km, 훈련량은 평소의 {ACWR×100}%)  ← "ACWR" 라는 용어는 쓰지 말 것
{어제 러닝 한 줄 평가 — 있을 때만}

🎯 오늘 훈련
{종류 · 거리/시간 · 페이스/심박 · 구성}

📅 이번 주 남은 일정
{요일별 한 줄, 남은 요일만}

💡 보완 포인트
- ...
- ...
"""


def _user_prompt(summary: dict, history: list) -> str:
    hist = "\n".join(f"[{b['date']}]\n{b['text']}" for b in history[:3])
    return (
        "## 오늘 분석 데이터\n" + json.dumps(summary, ensure_ascii=False, indent=1)
        + ("\n\n## 최근 브리핑 (같은 처방 반복 피하고 연속성 유지용)\n" + hist if hist else "")
        + "\n\n위 형식대로 오늘 브리핑을 작성하세요."
    )


def _claude_briefing(summary: dict, history: list) -> str:
    import anthropic

    client = anthropic.Anthropic()
    kwargs = dict(
        model=config.CLAUDE_MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _user_prompt(summary, history)}],
        thinking={"type": "adaptive"},
        output_config={"effort": config.COACH_EFFORT},
    )
    try:
        # 안전 분류기 거절 시 서버가 다른 모델로 자동 재시도 (server-side fallback)
        with client.beta.messages.stream(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
        ) as stream:
            msg = stream.get_final_message()
    except TypeError:  # 구버전 SDK 가 fallbacks 인자를 모를 때
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise RuntimeError("model refused")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("empty response")
    return text


def rule_based_briefing(summary: dict) -> str:
    """API 없이도 돌아가는 처방. 목표·주당 횟수·현재 페이스·회복 상태 기반 (plan.py)."""
    from . import plan as planner

    u, v, r, t = summary["user"], summary["volume"], summary["recovery"], summary["trend"]
    name = u["name"]
    ready = {"good": "좋음", "caution": "주의", "rest": "휴식 권장"}[r["readiness"]]
    reason = ", ".join(r["flags"]) if r["flags"] else "경고 지표 없음"
    weekly = v["last7_km"]
    pl = planner.build_plan(summary)
    p = pl["paces"]

    # 어제 평가
    yline = ""
    yest = summary["yesterday_runs"]
    if yest:
        y = yest[0]
        yp = planner.parse_pace(y.get("pace"))
        judge = ""
        if yp and p.get("tempo") and yp <= p["tempo"] + 5:
            judge = " → 강도 높은 러닝이었어요. 오늘은 회복이 우선."
        elif yp and p.get("easy") and yp <= p["easy"] - 20:
            judge = " → 쉬운 날치고는 빨랐어요. 편한 날은 더 느리게 뛰어도 됩니다."
        elif yp:
            judge = " → 편한 강도, 잘 지켰어요."
        if y.get("avg_hr") and u.get("max_hr") and y["avg_hr"] >= u["max_hr"] * 0.9:
            judge += f" 평균심박 {y['avg_hr']} 은 최대심박의 90% 이상이라 꽤 힘들었을 거예요."
        hr_part = f", 평균심박 {y['avg_hr']}" if y.get("avg_hr") else ""
        yline = f"\n어제: {y['km']}km {y['time_min']}분 (페이스 {y['pace']}{hr_part}){judge}"

    tips = []
    gp = planner.goal_progress_line(summary, pl)
    if gp:
        tips.append(gp)
    if v["acwr"] and v["acwr"] > 1.3:
        tips.append("이번 주 볼륨이 4주 평균보다 많이 늘었어요. 다음 주는 유지 또는 10% 줄이세요.")
    if t["hr_per_kmh_last14"] and t["hr_per_kmh_prev14"]:
        a, b = t["hr_per_kmh_last14"], t["hr_per_kmh_prev14"]
        tips.append("같은 속도에서 심박이 " + ("내려가고 있어요. 유산소 효율이 좋아지는 중입니다." if a < b else "올라갔어요. 피로 누적이나 수면을 점검하세요."))
    if v["runs_last7"] and v["longest_last28_km"] < weekly * 0.25 and weekly > 15:
        tips.append("주간 거리 대비 장거리가 짧습니다. 주 1회 장거리를 조금씩 늘려보세요.")
    if p.get("cur") and p.get("easy"):
        recent = [planner.parse_pace(x.get("pace")) for x in summary.get("recent_runs", [])[:6]]
        recent = [x for x in recent if x]
        if len(recent) >= 4 and sum(1 for x in recent if x < p["easy"] - 30) >= len(recent) * 0.75:
            tips.append("최근 러닝 대부분이 비슷한 중간 강도예요. 쉬운 날은 확실히 느리게, 강도 날은 확실히 빠르게 나눠야 늘어요.")
    if not tips:
        tips.append("꾸준함이 최고의 훈련입니다. 이번 주도 계획한 횟수를 채우는 데 집중하세요.")

    # 전문 분석 (VDOT · 예상 기록 · 강도 분포)
    fit = summary.get("fitness") or {}
    analysis_lines = []
    if fit.get("vdot"):
        pr = fit.get("predictions") or {}
        analysis_lines.append(f"VDOT {fit['vdot']} (기준: {fit.get('vdot_source')})")
        analysis_lines.append(f"예상 기록: 5K {pr.get('5K')} · 10K {pr.get('10K')} · 하프 {pr.get('하프')}")
        pz = fit.get("paces") or {}
        analysis_lines.append(f"훈련 페이스: 쉬운 {pz.get('E_slow')}~{pz.get('E')} · 템포 {pz.get('T')} · 인터벌 {pz.get('I')}")
    if fit.get("easy_share_28d") is not None:
        share = fit["easy_share_28d"]
        zone_note = ("좋은 배분이에요." if share >= 70 else
                     "쉬운 강도가 너무 적어요. 80/20 원칙상 러닝의 70~80%는 Z1~3(편한 대화 가능)이어야 회복되면서 늘어요.")
        analysis_lines.append(f"최근 28일 강도 분포: 쉬운 강도(Z1~3) {share}% → {zone_note}")
    if fit.get("max_hr"):
        z = fit.get("hr_zones") or {}
        z2, z4 = z.get(2) or z.get("2"), z.get(4) or z.get("4")
        if z2 and z4:
            analysis_lines.append(f"심박 존(최대 {fit['max_hr']}): 쉬운 Z2 {z2[0]}~{z2[1]} · 템포 Z4 {z4[0]}~{z4[1]}")
    analysis_text = "\n".join(analysis_lines) if analysis_lines else "러닝 기록이 더 쌓이면 VDOT·예상 기록이 표시됩니다."

    week = "\n".join(pl["week_lines"]) if pl["week_lines"] else "이번 주 남은 날 없음. 다음 주 계획은 월요일 브리핑에서."
    tips_text = "\n".join(f"- {x}" for x in tips[:2])
    load_part = f", 훈련량은 평소의 {round(v['acwr'] * 100)}%" if v.get("acwr") else ""
    return (
        f"🏃 {summary['date']}({summary['weekday']}) {name}님 아침 브리핑\n"
        f"컨디션: {ready} — {reason}\n\n"
        f"📊 지난 7일: {weekly}km / {v['runs_last7']}회 (지난주 {v['prev7_km']}km{load_part}){yline}\n\n"
        f"🎯 오늘 훈련\n{pl['today']}\n\n"
        f"📅 이번 주 남은 일정\n{week}\n\n"
        f"📈 분석\n{analysis_text}\n\n"
        f"💡 보완 포인트\n{tips_text}"
    )


def make_briefing(user: dict, summary: dict) -> tuple[str, str]:
    """(본문, 생성기) 반환. 생성기는 'claude' 또는 'rules'."""
    history = db.recent_briefings(user["id"], 3)
    use_claude = config.COACH_PROVIDER == "claude" or (config.COACH_PROVIDER == "auto" and config.ANTHROPIC_API_KEY)
    if use_claude:
        try:
            return _claude_briefing(summary, history), "claude"
        except Exception as e:  # noqa: BLE001
            log.warning("Claude briefing failed for %s: %s", user["name"], e)
    return rule_based_briefing(summary), "rules"
