"""수영 브리핑 카드. charts.py 의 스타일 헬퍼를 재사용."""
from __future__ import annotations

import io
from datetime import date

import matplotlib.pyplot as plt

from . import swim
from .charts import ACCENT, BAD, BG, GOOD, HIST, MUTED, PANEL, TXT, TXT2, WARN, ZONE_EASY, ZONE_HARD, ZONE_MID, _panel, _rounded, _setup_font
from matplotlib.patches import FancyBboxPatch

WAVE = "#38bdf8"


def render_card(summary: dict) -> bytes:
    _setup_font()
    u, v, t, r = summary["user"], summary["volume"], summary["trend"], summary["recovery"]
    d = date.fromisoformat(summary["date"])
    diet = swim.diet_plan(summary)
    ef = swim.efficiency_plan(summary)
    sp = swim.session_plan(summary)

    fig = plt.figure(figsize=(9, 12.6), dpi=140, facecolor=BG)
    gs = fig.add_gridspec(5, 2, height_ratios=[0.42, 0.55, 1.3, 1.5, 1.35], hspace=0.72, wspace=0.26,
                          left=0.06, right=0.95, top=0.965, bottom=0.04)

    # 헤더
    hd = fig.add_subplot(gs[0, :])
    hd.axis("off")
    hd.text(0, 1.0, "Y R C   S W I M   B R I E F", color=WAVE, fontsize=9.5, fontweight="bold", va="top")
    hd.text(0, 0.62, f"{u['name']}님의 수영 브리핑", color=TXT, fontsize=24, fontweight="bold", va="top")
    hd.text(0, 0.12, f"{d.year}년 {d.month}월 {d.day}일 {summary['weekday']}요일", color=MUTED, fontsize=11.5, va="top")
    ready = {"good": ("컨디션 좋음", GOOD), "caution": ("오늘은 조심", WARN), "rest": ("휴식 권장", BAD)}[r["readiness"]]
    _rounded(hd, 0.80, 0.55, 0.20, 0.34, ready[1], r=0.12)
    hd.text(0.90, 0.72, ready[0], color=BG, fontsize=12.5, fontweight="bold", ha="center", va="center", transform=hd.transAxes)

    # KPI
    kp = fig.add_subplot(gs[1, :])
    kp.axis("off")
    dm = v["last7_m"] - v["prev7_m"]
    pd = None
    if t.get("pace100_last14_s") and t.get("pace100_prev14_s"):
        pd = round(t["pace100_last14_s"] - t["pace100_prev14_s"])
    tiles = [
        ("이번 주 수영 거리", f"{v['last7_m']:,} m", f"{v['sessions_last7']}회 · {'▲' if dm >= 0 else '▼'} {abs(dm):,}m vs 지난주", GOOD if dm >= 0 else WARN),
        ("100m 페이스 (2주 평균)", t.get("pace100_last14") or "-", (f"{'▼' if pd < 0 else '▲'} {abs(pd)}초 vs 그 전 2주" if pd is not None else "기록 쌓는 중"), (GOOD if (pd or 0) < 0 else (WARN if (pd or 0) > 0 else MUTED))),
        ("이번 주 소모 칼로리", f"{v['kcal_last7']:,} kcal", f"수영 {v['min_last7']}분 · 하루 목표 섭취 {diet['target_kcal']:,}kcal", MUTED),
    ]
    for i, (label, big, sub, subcol) in enumerate(tiles):
        x = i * 0.345
        _rounded(kp, x, 0, 0.31, 1.0, PANEL, r=0.06)
        kp.text(x + 0.03, 0.80, label, color=MUTED, fontsize=9.5, va="center", transform=kp.transAxes)
        kp.text(x + 0.03, 0.46, big, color=TXT, fontsize=21, fontweight="bold", va="center", transform=kp.transAxes)
        kp.text(x + 0.03, 0.15, sub, color=subcol, fontsize=8.8, va="center", transform=kp.transAxes)

    # 주간 거리
    ax = fig.add_subplot(gs[2, 0])
    weeks = summary["charts"]["weeks"]
    ms = [w["m"] for w in weeks]
    colors = [HIST] * len(ms)
    if colors:
        colors[-1] = ACCENT
    bars = ax.bar(range(len(ms)), ms, color=colors, width=0.6, zorder=3)
    for b, k in zip(bars, ms):
        if k:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + max(ms) * 0.03, f"{k / 1000:.1f}k", ha="center", color=TXT2, fontsize=9)
    ax.set_xticks(range(len(ms)))
    ax.set_xticklabels([w["label"] for w in weeks])
    ax.set_yticks([])
    ax.set_ylim(0, max(ms + [1000]) * 1.25)
    _panel(ax, "주간 수영 거리", "최근 8주 · m · 초록 = 이번 주")

    # 훈련량 게이지
    ax = fig.add_subplot(gs[2, 1])
    ax.axis("off")
    _panel(ax, "이번 주 훈련량", "지난 7일 거리 ÷ 최근 4주 평균 · 1.0 = 평소 수준")
    acwr = v.get("acwr")
    gx0, gx1, gy, gh = 0.05, 0.95, 0.60, 0.16
    scale = lambda val: gx0 + (gx1 - gx0) * min(max(val, 0), 2.0) / 2.0
    for lo, hi, col in ((0, 0.8, "#334155"), (0.8, 1.3, GOOD), (1.3, 1.5, WARN), (1.5, 2.0, BAD)):
        ax.add_patch(FancyBboxPatch((scale(lo), gy), scale(hi) - scale(lo), gh, boxstyle="round,pad=0,rounding_size=0.01",
                                    transform=ax.transAxes, facecolor=col, alpha=0.35 if col != "#334155" else 1, edgecolor="none"))
    for val in (0.8, 1.3, 1.5):
        ax.text(scale(val), gy - 0.06, str(val), color=MUTED, fontsize=8.5, ha="center", transform=ax.transAxes)
    if acwr:
        mx = scale(acwr)
        ax.plot([mx, mx], [gy - 0.02, gy + gh + 0.02], color=TXT, linewidth=3, transform=ax.transAxes, solid_capstyle="round")
        ax.text(0.05, 0.30, f"평소의 {round(acwr * 100)}%", color=TXT, fontsize=19, fontweight="bold", transform=ax.transAxes, va="center")
        ax.text(0.05, 0.12, "체중 감량엔 꾸준함이 최고. 급하게 늘리면 어깨 탈." if acwr > 1.3 else "적정 범위. 이 리듬 유지.", color=TXT2, fontsize=9.5, transform=ax.transAxes, va="center")
    else:
        ax.text(0.05, 0.30, "기록이 더 필요해요", color=MUTED, fontsize=12, transform=ax.transAxes, va="center")

    # 최근 세션 표
    ax = fig.add_subplot(gs[3, :])
    ax.axis("off")
    _panel(ax, "최근 수영", "최근 14일 · 막대 = 거리 · 100m 페이스 · 심박 · 25m당 스트로크 · 칼로리")
    rows = (summary.get("recent_sessions") or [])[:6]
    if rows:
        mx = max(x["m"] for x in rows) or 1
        top, bottom = 0.92, 0.04
        step = (top - bottom) / len(rows)
        for i, x in enumerate(rows):
            y = top - i * step - step / 2
            dd = date.fromisoformat(x["date"])
            ax.text(0.01, y, f"{dd.month}/{dd.day} {swim.WEEKDAYS[dd.weekday()]} {x['time']}", color=TXT2, fontsize=10, va="center", transform=ax.transAxes)
            bw = 0.28 * x["m"] / mx
            _rounded(ax, 0.20, y - 0.035, bw, 0.07, WAVE, r=0.01)
            ax.text(0.20 + bw + 0.012, y, f"{x['m']:,}m", color=TXT, fontsize=10.5, fontweight="bold", va="center", transform=ax.transAxes)
            ax.text(0.60, y, x["pace100"], color=TXT, fontsize=11, fontweight="bold", va="center", transform=ax.transAxes)
            ax.text(0.71, y, f"♥ {x['avg_hr']}" if x.get("avg_hr") else "♥ -", color=TXT2, fontsize=10, va="center", transform=ax.transAxes)
            spl_col = TXT2
            if x.get("spl") and ef.get("target"):
                spl_col = GOOD if x["spl"] <= ef["target"] else (WARN if x["spl"] > ef["target"] + 2 else TXT2)
            ax.text(0.81, y, f"{x['spl']}/25m" if x.get("spl") else "", color=spl_col, fontsize=10, va="center", transform=ax.transAxes)
            ax.text(0.99, y, f"{x['kcal']}kcal" if x.get("kcal") else f"{x['time_min']}분", color=MUTED, fontsize=10, va="center", ha="right", transform=ax.transAxes)
    else:
        ax.text(0.5, 0.5, "최근 14일 수영 기록이 없어요", color=MUTED, ha="center", transform=ax.transAxes)

    # 효율 + 오늘 세션
    ax = fig.add_subplot(gs[4, 0])
    ax.axis("off")
    _panel(ax, "스트로크 효율 (핵심 과제)", "25m 한 번 갈 때 스트로크 수 · 적을수록 효율적")
    if ef.get("spl"):
        ax.text(0.03, 0.78, f"{ef['spl']}", color=TXT, fontsize=30, fontweight="bold", transform=ax.transAxes, va="center")
        ax.text(0.30, 0.78, f"→ 목표 {ef['target']}", color=ACCENT, fontsize=14, fontweight="bold", transform=ax.transAxes, va="center")
        if ef.get("delta") is not None:
            ax.text(0.03, 0.55, f"2주 전 {ef['prev']} ({'+' if ef['delta'] >= 0 else ''}{ef['delta']}) · {ef['status']}", color=TXT2, fontsize=10, transform=ax.transAxes, va="center")
        ax.text(0.03, 0.36, "초보 22~25 · 중급 18~20 · 상급 14~16", color=MUTED, fontsize=9, transform=ax.transAxes, va="center")
    else:
        ax.text(0.03, 0.72, "스트로크 기록이 들어오면 표시", color=MUTED, fontsize=11, transform=ax.transAxes, va="center")
    fz = summary["fitness"]["fat_zone"]
    ax.text(0.03, 0.16, f"지방 연소 심박 {fz[0]}~{fz[1]} · 오늘 아침 {sp['base_m']:,}m 기술+지속", color=TXT2, fontsize=9.5, transform=ax.transAxes, va="center")

    # 식단
    ax = fig.add_subplot(gs[4, 1])
    ax.axis("off")
    _panel(ax, "오늘 식단", f"목표 {diet['target_kcal']:,}kcal · 단백질 {diet['protein_g']}g · 탄수 {diet['carbs_g']}g · 지방 {diet['fat_g']}g" + ("" if diet["personalized"] else " (기본값)"))
    for i, (k, val) in enumerate(diet["meals"].items()):
        y = 0.84 - i * 0.24
        _rounded(ax, 0.03, y - 0.05, 0.012, 0.1, [ZONE_EASY, ZONE_MID, ZONE_HARD][i], r=0.005)
        ax.text(0.07, y + 0.035, k, color=MUTED, fontsize=9, transform=ax.transAxes, va="center")
        ax.text(0.07, y - 0.045, val, color=TXT, fontsize=9.5, transform=ax.transAxes, va="center", wrap=True)
    if diet.get("to_goal_kg") is not None:
        ax.text(0.03, 0.06, f"목표 체중까지 {diet['to_goal_kg']}kg · 주 0.5kg 기준 약 {diet['weeks_to_goal']}주", color=ACCENT, fontsize=9.5, fontweight="bold", transform=ax.transAxes, va="center")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
