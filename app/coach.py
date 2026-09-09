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


def date_idx(summary: dict) -> int:
    """날짜별로 팁이 돌아가도록 하는 인덱스."""
    from datetime import date
    try:
        return date.fromisoformat(summary["date"]).toordinal()
    except Exception:  # noqa: BLE001
        return 0


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

    # ---- 짧은 형식: 숫자·그래프는 카드 이미지에 있으므로 글은 판단과 지시만 ----
    d = summary["date"]
    head = f"🏃 {int(d[5:7])}/{int(d[8:10])}({summary['weekday']}) 브리핑 · 컨디션 {ready}"
    if r["flags"]:
        head += f" · {r['flags'][0]}"

    # 어제 한 줄
    yline = ""
    yest = summary["yesterday_runs"]
    if yest:
        y = yest[0]
        yp = planner.parse_pace(y.get("pace"))
        judge = ""
        if yp and p.get("tempo") and yp <= p["tempo"] + 5:
            judge = " → 힘든 러닝, 오늘은 회복"
        elif yp and p.get("easy") and yp <= p["easy"] - 20:
            judge = " → 쉬운 날치곤 빨랐어요"
        hr_part = f" ♥{y['avg_hr']}" if y.get("avg_hr") else ""
        cad_part = f" 케이던스 {y['cadence']}" if y.get("cadence") else ""
        yline = f"어제 {y['km']}km {y['pace']}{hr_part}{cad_part}{judge}"

    # 케이던스 두 줄
    cad = pl.get("cadence") or {}
    cad_line, tip_line = "", ""
    if cad.get("avg"):
        avg, target, delta = cad["avg"], cad["target"], cad.get("delta")
        trend = f" (2주 전보다 {'+' if delta >= 0 else ''}{delta})" if delta is not None else ""
        status = {"reached": "목표 도달, 유지", "improving": "잘 올라오는 중", "dropping": "떨어졌어요, 보폭 점검",
                  "flat": "정체, 첫 5분은 메트로놈"}.get(cad.get("status"), "")
        cad_line = f"🦶 케이던스 {avg}{trend} → 이번 주 목표 {target} · {status}"
        drills = [
            "메트로놈 앱을 목표 bpm에 맞추고 첫 5분만 박자에 맞춰 딛기",
            "속도는 그대로, 보폭만 살짝 줄여서 발이 몸 아래에 떨어지게",
            "팔을 짧고 빠르게 흔들면 다리가 따라와요",
            "러닝 끝에 20초 스트라이드 4회, 180 느낌 (전력 질주 아님)",
            "오르막 30초 × 4회, 케이던스가 저절로 올라갑니다",
        ]
        tip_line = "💡 " + drills[date_idx(summary) % len(drills)]
    else:
        cad_line = "🦶 케이던스 기록 없음 (단축어 보폭 동작 확인)"

    # 남은 주 한 줄
    week_short = " · ".join(x.replace(": ", " ") for x in pl["week_lines"] if "휴식" not in x)
    week_line = f"📅 {week_short}" if week_short else "📅 이번 주 남은 러닝 없음"

    # 부하 경고는 한 줄만
    warn_line = ""
    if v.get("acwr") and v["acwr"] > 1.3:
        warn_line = "⚠️ 훈련량이 평소보다 많아요 → 다음 주는 유지/감량"

    lines = [head]
    if yline:
        lines.append(yline)
    lines.append("")
    lines.append(f"🎯 오늘: {pl['today']}")
    lines.append(cad_line)
    if tip_line:
        lines.append(tip_line)
    lines.append(week_line)
    if warn_line:
        lines.append(warn_line)
    return "\n".join(lines)


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
