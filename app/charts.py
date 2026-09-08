"""브리핑 카드 이미지 (matplotlib). 텔레그램 사진 + 웹페이지에 사용.

한눈에 읽히도록: 큰 숫자 3개 → 주간 거리 → 훈련량 게이지 → 최근 러닝 표 → 강도 분포 → 훈련 페이스.
"""
from __future__ import annotations

import io
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from . import config  # noqa: E402

# 팔레트 (딥 네이비 + 틸 포인트, 상태색은 별도)
BG, PANEL, PANEL2 = "#0b1220", "#141c2e", "#1b2540"
TXT, TXT2, MUTED, GRID = "#eef2f8", "#c7d0df", "#8b97ad", "#243050"
ACCENT, HIST = "#2dd4bf", "#3b82f6"
GOOD, WARN, BAD = "#34d399", "#fbbf24", "#f87171"
ZONE_EASY, ZONE_MID, ZONE_HARD = "#38bdf8", "#fbbf24", "#f87171"

_FONT_READY = False
FONT = "sans-serif"


def _setup_font():
    global _FONT_READY, FONT
    if _FONT_READY:
        return
    fams = []
    for name in ("Pretendard-Regular.otf", "Pretendard-SemiBold.otf", "Pretendard-Bold.otf", "NanumGothic.ttf"):
        p = config.ASSETS_DIR / name
        if p.exists():
            font_manager.fontManager.addfont(str(p))
            fams.append(font_manager.FontProperties(fname=str(p)).get_name())
    if fams:
        FONT = fams[0]
        plt.rcParams["font.family"] = [FONT] + [f for f in fams[1:] if f != FONT]
    plt.rcParams["axes.unicode_minus"] = False
    _FONT_READY = True


def _pace_label(sec):
    if not sec:
        return "-"
    m, s = divmod(int(round(sec)), 60)
    return f"{m}'{s:02d}\""


def _panel(ax, title=None, sub=None):
    """둥근 패널 배경 + 제목/부제. 축이 꺼진 패널에도 배경이 보이도록 패치로 그린다."""
    ax.set_facecolor("none")
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.03", transform=ax.transAxes,
                                facecolor=PANEL, edgecolor="none", clip_on=False, zorder=-5))
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9.5, length=0)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.grid(False, axis="x")
    ax.set_axisbelow(True)
    if title:
        ax.text(0, 1.20, title, color=TXT, fontsize=13.5, fontweight="bold", transform=ax.transAxes, va="bottom")
    if sub:
        ax.text(0, 1.06, sub, color=MUTED, fontsize=8.5, transform=ax.transAxes, va="bottom")


def _rounded(ax, x, y, w, h, color, r=0.02):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", transform=ax.transAxes,
                                facecolor=color, edgecolor="none", clip_on=False))


def _delta_text(cur, prev, unit="", lower_is_better=False, fmt=lambda x: f"{x:g}"):
    if cur is None or prev is None:
        return "", MUTED
    diff = cur - prev
    if abs(diff) < 1e-9:
        return "지난번과 같음", MUTED
    better = (diff < 0) if lower_is_better else (diff > 0)
    arrow = "▲" if diff > 0 else "▼"
    return f"{arrow} {fmt(abs(diff))}{unit} vs 지난주", (GOOD if better else WARN)


def render_card(summary: dict) -> bytes:
    _setup_font()
    u, v, r, t = summary["user"], summary["volume"], summary["recovery"], summary["trend"]
    fit, ch = summary.get("fitness", {}) or {}, summary.get("charts", {}) or {}
    d = date.fromisoformat(summary["date"])

    fig = plt.figure(figsize=(9, 12.6), dpi=140, facecolor=BG)
    gs = fig.add_gridspec(5, 2, height_ratios=[0.42, 0.55, 1.3, 1.5, 1.25], hspace=0.72, wspace=0.26,
                          left=0.06, right=0.95, top=0.965, bottom=0.04)

    # ================= 헤더 =================
    hd = fig.add_subplot(gs[0, :])
    hd.axis("off")
    hd.text(0, 1.0, "YRC RUNNING BRIEF", color=ACCENT, fontsize=10.5, fontweight="bold", va="top", letterspacing=2) if False else \
        hd.text(0, 1.0, "Y R C   R U N N I N G   B R I E F", color=ACCENT, fontsize=9.5, fontweight="bold", va="top")
    hd.text(0, 0.62, f"{u['name']}님의 아침 브리핑", color=TXT, fontsize=24, fontweight="bold", va="top")
    hd.text(0, 0.12, f"{d.year}년 {d.month}월 {d.day}일 {summary['weekday']}요일", color=MUTED, fontsize=11.5, va="top")
    ready = {"good": ("컨디션 좋음", GOOD), "caution": ("오늘은 조심", WARN), "rest": ("휴식 권장", BAD)}[r["readiness"]]
    _rounded(hd, 0.80, 0.55, 0.20, 0.34, ready[1], r=0.12)
    hd.text(0.90, 0.72, ready[0], color=BG, fontsize=12.5, fontweight="bold", ha="center", va="center", transform=hd.transAxes)

    # ================= KPI 타일 3개 =================
    kp = fig.add_subplot(gs[1, :])
    kp.axis("off")
    pace_now = t.get("avg_pace_last14")
    pace_prev = t.get("avg_pace_prev14")
    pd = t.get("pace_delta_sec_per_km")
    pace_delta = ("", MUTED)
    if pd is not None:
        pace_delta = (f"{'▼' if pd < 0 else '▲'} {abs(pd)}초/km vs 그 전 2주", GOOD if pd < 0 else WARN)
    km_delta = _delta_text(v["last7_km"], v["prev7_km"], "km", fmt=lambda x: f"{x:.1f}")
    pred10 = (fit.get("predictions") or {}).get("10K")
    tiles = [
        ("이번 주 거리 (7일)", f"{v['last7_km']} km", f"{v['runs_last7']}회 러닝 · " + km_delta[0], km_delta[1]),
        ("최근 2주 평균 페이스", pace_now or "-", pace_delta[0] or f"그 전 2주 {pace_prev}", pace_delta[1]),
        ("예상 10K 기록", pred10 or "-", f"체력 지수 VDOT {fit.get('vdot')}" if fit.get("vdot") else "기록이 더 필요해요", MUTED),
    ]
    for i, (label, big, sub, subcol) in enumerate(tiles):
        x = i * 0.345
        _rounded(kp, x, 0, 0.31, 1.0, PANEL, r=0.06)
        kp.text(x + 0.03, 0.80, label, color=MUTED, fontsize=9.5, va="center", transform=kp.transAxes)
        kp.text(x + 0.03, 0.46, big, color=TXT, fontsize=21, fontweight="bold", va="center", transform=kp.transAxes)
        kp.text(x + 0.03, 0.15, sub, color=subcol, fontsize=8.8, va="center", transform=kp.transAxes)

    # ================= 주간 거리 8주 =================
    ax = fig.add_subplot(gs[2, 0])
    weeks = ch.get("weeks") or []
    labels = [w["label"] for w in weeks]
    kms = [w["km"] for w in weeks]
    colors = [HIST] * len(kms)
    if colors:
        colors[-1] = ACCENT
    bars = ax.bar(range(len(kms)), kms, color=colors, width=0.6, zorder=3)
    for b, k in zip(bars, kms):
        if k:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + max(kms) * 0.03, f"{k:.0f}", ha="center", color=TXT2, fontsize=9)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_yticks([])
    ax.set_ylim(0, max(kms + [10]) * 1.25)
    _panel(ax, "주간 거리", "최근 8주 · km · 초록 = 이번 주(진행 중)")

    # ================= 훈련량 게이지 =================
    ax = fig.add_subplot(gs[2, 1])
    ax.axis("off")
    _panel(ax, "이번 주 훈련량", "지난 7일 거리 ÷ 최근 4주 평균 · 1.0 = 평소 수준")
    ax.set_facecolor(PANEL)
    acwr = v.get("acwr")
    gx0, gx1, gy, gh = 0.05, 0.95, 0.60, 0.16
    scale = lambda val: gx0 + (gx1 - gx0) * min(max(val, 0), 2.0) / 2.0
    for lo, hi, col in ((0, 0.8, "#334155"), (0.8, 1.3, GOOD), (1.3, 1.5, WARN), (1.5, 2.0, BAD)):
        ax.add_patch(FancyBboxPatch((scale(lo), gy), scale(hi) - scale(lo), gh, boxstyle="round,pad=0,rounding_size=0.01",
                                    transform=ax.transAxes, facecolor=col, alpha=0.35 if col != "#334155" else 1, edgecolor="none"))
    for val, name in ((0.8, "0.8"), (1.3, "1.3"), (1.5, "1.5")):
        ax.text(scale(val), gy - 0.06, name, color=MUTED, fontsize=8.5, ha="center", transform=ax.transAxes)
    ax.text(scale(1.05), gy + gh + 0.05, "안전", color=GOOD, fontsize=9, ha="center", transform=ax.transAxes)
    ax.text(scale(1.4), gy + gh + 0.05, "주의", color=WARN, fontsize=9, ha="center", transform=ax.transAxes)
    ax.text(scale(1.75), gy + gh + 0.05, "부상 위험", color=BAD, fontsize=9, ha="center", transform=ax.transAxes)
    if acwr:
        mx = scale(acwr)
        ax.plot([mx, mx], [gy - 0.02, gy + gh + 0.02], color=TXT, linewidth=3, transform=ax.transAxes, solid_capstyle="round")
        pct = round(acwr * 100)
        state = "평소보다 많이 뛰었어요" if acwr > 1.3 else ("적정 범위예요" if acwr >= 0.8 else "평소보다 적게 뛰었어요")
        ax.text(0.05, 0.30, f"평소의 {pct}%", color=TXT, fontsize=19, fontweight="bold", transform=ax.transAxes, va="center")
        ax.text(0.05, 0.12, state + ("  → 다음 주는 유지/감량" if acwr > 1.3 else ""), color=TXT2, fontsize=9.5, transform=ax.transAxes, va="center")
    else:
        ax.text(0.05, 0.30, "기록이 더 필요해요", color=MUTED, fontsize=12, transform=ax.transAxes, va="center")

    # ================= 최근 러닝 표 =================
    ax = fig.add_subplot(gs[3, :])
    ax.axis("off")
    _panel(ax, "최근 러닝", "최근 14일 · 막대 = 거리 · 페이스 · 평균 심박")
    runs = (summary.get("recent_runs") or [])[:6]
    pz = fit.get("paces_sec") or {}
    if runs:
        maxkm = max(x["km"] for x in runs) or 1
        rows = len(runs)
        top, bottom = 0.92, 0.04
        step = (top - bottom) / max(rows, 1)
        for i, x in enumerate(runs):
            y = top - i * step - step / 2
            dd = date.fromisoformat(x["date"])
            wd = ["월", "화", "수", "목", "금", "토", "일"][dd.weekday()]
            ax.text(0.01, y, f"{dd.month}/{dd.day} {wd}", color=TXT2, fontsize=10.5, va="center", transform=ax.transAxes)
            bw = 0.36 * x["km"] / maxkm
            pace_s = None
            try:
                mm, ss = x["pace"].replace('"', "").split("'")
                pace_s = int(mm) * 60 + int(ss)
            except Exception:  # noqa: BLE001
                pass
            col = HIST
            if pace_s and pz.get("T") and pace_s <= pz["T"] + 5:
                col = BAD
            elif pace_s and pz.get("E") and pace_s >= pz["E"] - 20:
                col = ZONE_EASY
            _rounded(ax, 0.16, y - 0.035, bw, 0.07, col, r=0.01)
            ax.text(0.16 + bw + 0.012, y, f"{x['km']:.1f} km", color=TXT, fontsize=10.5, fontweight="bold", va="center", transform=ax.transAxes)
            ax.text(0.66, y, x["pace"], color=TXT, fontsize=11, fontweight="bold", va="center", transform=ax.transAxes)
            ax.text(0.66, y - 0.035 * 2.2, "페이스", color=MUTED, fontsize=7.5, va="center", transform=ax.transAxes) if i == 0 and False else None
            hr_txt = f"♥ {x['avg_hr']}" if x.get("avg_hr") else "♥ -"
            ax.text(0.80, y, hr_txt, color=TXT2, fontsize=10.5, va="center", transform=ax.transAxes)
            ax.text(0.93, y, f"{x['time_min']:.0f}분", color=MUTED, fontsize=10, va="center", transform=ax.transAxes)
        ax.text(0.99, -0.06, "막대 색: 빨강 = 강도 높음 · 파랑 = 보통 · 하늘 = 쉬운 강도", color=MUTED, fontsize=8, transform=ax.transAxes, va="top", ha="right")
    else:
        ax.text(0.5, 0.5, "최근 14일 러닝 기록이 없어요", color=MUTED, ha="center", transform=ax.transAxes)

    # ================= 강도 분포 =================
    ax = fig.add_subplot(gs[4, 0])
    ax.axis("off")
    _panel(ax, "강도 분포", "최근 28일 러닝 시간 · 심박 존 기준")
    zm = fit.get("zone_minutes_28d") or {}
    g = lambda z: zm.get(str(z), zm.get(z, 0))
    easy, mid, hard = g(1) + g(2) + g(3), g(4), g(5)
    tot = easy + mid + hard
    if tot:
        x = 0.03
        for val, col, name in ((easy, ZONE_EASY, "쉬움"), (mid, ZONE_MID, "보통"), (hard, ZONE_HARD, "강함")):
            w = 0.94 * val / tot
            if w > 0:
                _rounded(ax, x, 0.62, max(w - 0.006, 0.004), 0.2, col, r=0.01)
                if w > 0.08:
                    ax.text(x + w / 2, 0.72, f"{name} {val / tot * 100:.0f}%", color=BG, fontsize=9.5, fontweight="bold",
                            ha="center", va="center", transform=ax.transAxes)
                x += w
        share = round(easy / tot * 100)
        ax.text(0.03, 0.40, f"쉬운 강도 {share}%", color=TXT, fontsize=18, fontweight="bold", transform=ax.transAxes, va="center")
        ax.text(0.03, 0.20, "권장 70~80%. 대부분의 러닝은 대화가 가능한 편한 속도로,", color=TXT2, fontsize=9, transform=ax.transAxes, va="center")
        ax.text(0.03, 0.08, "주 1~2회만 강하게 뛰어야 부상 없이 빨라져요.", color=TXT2, fontsize=9, transform=ax.transAxes, va="center")
        zb = fit.get("hr_zones") or {}
        z2 = zb.get("2") or zb.get(2)
        if z2:
            ax.text(0.97, 0.40, f"쉬운 강도 = 심박 {z2[0]}~{zb.get('3', zb.get(3))[1] if (zb.get('3') or zb.get(3)) else z2[1]}",
                    color=MUTED, fontsize=8.5, ha="right", transform=ax.transAxes, va="center")
    else:
        ax.text(0.5, 0.5, "심박 기록이 더 필요해요", color=MUTED, ha="center", transform=ax.transAxes)

    # ================= 훈련 페이스 & 예상 기록 =================
    ax = fig.add_subplot(gs[4, 1])
    ax.axis("off")
    _panel(ax, "권장 훈련 페이스", "최근 최고 기록으로 계산 (VDOT)")
    p = fit.get("paces") or {}
    rows = [("쉬운 러닝", f"{p.get('E_slow', '-')} ~ {p.get('E', '-')}", ZONE_EASY),
            ("템포 (20분 유지)", p.get("T", "-"), ZONE_MID),
            ("인터벌 (1km 반복)", p.get("I", "-"), ZONE_HARD)]
    for i, (k, val, col) in enumerate(rows):
        y = 0.80 - i * 0.2
        _rounded(ax, 0.03, y - 0.035, 0.012, 0.07, col, r=0.005)
        ax.text(0.07, y, k, color=TXT2, fontsize=10.5, transform=ax.transAxes, va="center")
        ax.text(0.97, y, val, color=TXT, fontsize=12, fontweight="bold", transform=ax.transAxes, va="center", ha="right")
    pr = fit.get("predictions") or {}
    if pr:
        ax.text(0.03, 0.17, "지금 체력으로 예상되는 기록", color=MUTED, fontsize=8.5, transform=ax.transAxes, va="center")
        ax.text(0.03, 0.04, f"5K {pr.get('5K')}   ·   10K {pr.get('10K')}   ·   하프 {pr.get('하프')}", color=TXT, fontsize=10,
                fontweight="bold", transform=ax.transAxes, va="center")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
