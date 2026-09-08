"""브리핑 카드 이미지 (matplotlib). 텔레그램 사진 + 웹페이지에 사용."""
from __future__ import annotations

import io
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from . import config  # noqa: E402

BG, PANEL, TXT, MUTED, GRID = "#0f1115", "#181b22", "#e8e8e8", "#8a919c", "#262b35"
ACCENT, GOOD, WARN, BAD = "#5cc8ff", "#3ddc97", "#ffb84d", "#ff6b6b"

_FONT_READY = False


def _setup_font():
    global _FONT_READY
    if _FONT_READY:
        return
    path = config.ASSETS_DIR / "NanumGothic.ttf"
    if path.exists():
        font_manager.fontManager.addfont(str(path))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    _FONT_READY = True


def _pace_label(sec):
    m, s = divmod(int(round(sec)), 60)
    return f"{m}'{s:02d}"


def _style(ax, title=None):
    ax.set_facecolor(PANEL)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=TXT, fontsize=12, loc="left", pad=8, fontweight="bold")


def render_card(summary: dict) -> bytes:
    """요약 JSON → PNG bytes"""
    _setup_font()
    u, v, r, fit, ch = summary["user"], summary["volume"], summary["recovery"], summary.get("fitness", {}), summary.get("charts", {})
    fig = plt.figure(figsize=(9, 11.5), dpi=130, facecolor=BG)
    gs = fig.add_gridspec(4, 2, height_ratios=[0.9, 1.6, 1.6, 1.5], hspace=0.55, wspace=0.28,
                          left=0.07, right=0.97, top=0.96, bottom=0.05)

    # ---- 헤더 ----
    hd = fig.add_subplot(gs[0, :])
    hd.axis("off")
    d = date.fromisoformat(summary["date"])
    ready_txt = {"good": ("컨디션 좋음", GOOD), "caution": ("주의", WARN), "rest": ("휴식 권장", BAD)}[r["readiness"]]
    hd.text(0, 0.95, f"YRC 러닝 브리핑", color=ACCENT, fontsize=13, fontweight="bold", va="top")
    hd.text(0, 0.62, f"{u['name']}님 · {d.month}/{d.day}({summary['weekday']})", color=TXT, fontsize=20, fontweight="bold", va="top")
    hd.text(0.995, 0.62, ready_txt[0], color=ready_txt[1], fontsize=15, fontweight="bold", va="top", ha="right")
    stats = [
        ("지난 7일", f"{v['last7_km']} km / {v['runs_last7']}회"),
        ("ACWR", f"{v['acwr'] if v['acwr'] else '-'}"),
        ("VDOT", f"{fit.get('vdot') or '-'}"),
        ("예상 10K", (fit.get("predictions") or {}).get("10K", "-")),
        ("최근 14일 페이스", summary["trend"]["avg_pace_last14"]),
    ]
    for i, (k, val) in enumerate(stats):
        x = i / len(stats)
        hd.text(x, 0.18, val, color=TXT, fontsize=13, fontweight="bold", va="center")
        hd.text(x, -0.08, k, color=MUTED, fontsize=9, va="center")

    # ---- 주간 거리 8주 ----
    ax = fig.add_subplot(gs[1, 0])
    weeks = ch.get("weeks") or []
    labels = [w["label"] for w in weeks]
    kms = [w["km"] for w in weeks]
    colors = [ACCENT] * len(kms)
    if colors:
        colors[-1] = GOOD
    bars = ax.bar(range(len(kms)), kms, color=colors, width=0.62)
    for b, k in zip(bars, kms):
        if k:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.3, f"{k:.0f}", ha="center", color=TXT, fontsize=8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    _style(ax, "주간 거리 (km) · 최근 8주")
    ax.text(1, 1.02, "이번 주(진행 중)", color=GOOD, fontsize=8, transform=ax.transAxes, ha="right")

    # ---- ACWR 28일 ----
    ax = fig.add_subplot(gs[1, 1])
    series = ch.get("acwr_series") or []
    xs = list(range(len(series)))
    ys = [s["acwr"] for s in series]
    ax.axhspan(0.8, 1.3, color=GOOD, alpha=0.12)
    ax.axhspan(1.3, 1.5, color=WARN, alpha=0.10)
    ax.axhspan(1.5, 2.5, color=BAD, alpha=0.10)
    ax.plot(xs, [y if y is not None else float("nan") for y in ys], color=ACCENT, linewidth=2)
    if ys and ys[-1] is not None:
        ax.scatter([xs[-1]], [ys[-1]], color=TXT, zorder=5, s=30)
        ax.text(xs[-1], ys[-1] + 0.07, f"{ys[-1]}", color=TXT, fontsize=9, ha="right")
    ax.set_ylim(0, max(2.0, max((y for y in ys if y), default=1) + 0.3))
    ticks = [i for i in range(0, len(series), 7)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([series[i]["date"][5:].replace("-", "/") for i in ticks] if series else [])
    _style(ax, "부하비 ACWR · 최근 28일")
    ax.text(0.01, 0.9, "0.8~1.3 안전 구간", color=GOOD, fontsize=8, transform=ax.transAxes)

    # ---- 페이스 & 심박 산점 ----
    ax = fig.add_subplot(gs[2, :])
    pts = ch.get("runs_28d") or []
    if pts:
        days = [(date.fromisoformat(p["date"]) - d).days for p in pts]
        paces = [p["pace_s"] for p in pts]
        hrs = [p["avg_hr"] or 0 for p in pts]
        sizes = [max(40, p["km"] * 22) for p in pts]
        sc = ax.scatter(days, paces, c=[h if h else 0 for h in hrs], cmap="plasma", s=sizes, vmin=130, vmax=max(hrs + [180]),
                        edgecolors=BG, linewidths=0.8, zorder=3)
        for x, y, p in zip(days, paces, pts):
            ax.text(x, y - 9, f"{p['km']:.1f}k", color=MUTED, fontsize=7, ha="center")
        ax.invert_yaxis()
        lo, hi = min(paces), max(paces)
        ax.set_ylim(hi + 40, lo - 40)
        yt = list(range(int(lo // 30 * 30) - 30, int(hi // 30 * 30) + 61, 30))
        ax.set_yticks(yt)
        ax.set_yticklabels([_pace_label(t) for t in yt])
        cb = fig.colorbar(sc, ax=ax, pad=0.01, fraction=0.03)
        cb.set_label("평균 심박", color=MUTED, fontsize=8)
        cb.ax.yaxis.set_tick_params(color=MUTED, labelcolor=MUTED, labelsize=8)
        cb.outline.set_visible(False)
        pz = fit.get("paces_sec") or {}
        for key, name, col in (("E", "E 쉬운", GOOD), ("T", "T 템포", WARN), ("I", "I 인터벌", BAD)):
            if pz.get(key):
                ax.axhline(pz[key], color=col, linewidth=1, linestyle="--", alpha=0.7)
                ax.text(-27.5, pz[key] - 4, name, color=col, fontsize=8)
        ax.set_xlim(-28.5, 0.8)
        ax.set_xlabel("일 전 (오늘 = 0)", color=MUTED, fontsize=9)
    else:
        ax.text(0.5, 0.5, "최근 28일 러닝 없음", color=MUTED, ha="center", transform=ax.transAxes)
    _style(ax, "최근 28일 러닝 · 페이스(분/km) · 점 크기=거리 · 색=평균심박 · 점선=권장 훈련 페이스")

    # ---- 심박 존 분포 ----
    ax = fig.add_subplot(gs[3, 0])
    zm = fit.get("zone_minutes_28d") or {}
    zones = [1, 2, 3, 4, 5]
    mins = [zm.get(str(z), zm.get(z, 0)) for z in zones]
    zcol = ["#7fd1ff", GOOD, "#c6e377", WARN, BAD]
    ax.barh([f"Z{z}" for z in zones], mins, color=zcol, height=0.62)
    tot = sum(mins) or 1
    for i, m in enumerate(mins):
        ax.text(m + tot * 0.01, i, f"{m}분 ({m / tot * 100:.0f}%)", va="center", color=TXT, fontsize=8)
    ax.set_xlim(0, max(mins + [1]) * 1.35)
    ax.invert_yaxis()
    zb = fit.get("hr_zones") or {}
    _style(ax, "심박 존 분포 · 28일 (Z1~3 = 쉬운 강도)")
    if zb:
        z2 = zb.get("2") or zb.get(2)
        z4 = zb.get("4") or zb.get(4)
        if z2 and z4:
            ax.text(0.99, 0.02, f"최대심박 {fit.get('max_hr')} · Z2 {z2[0]}~{z2[1]} · Z4 {z4[0]}~{z4[1]}", color=MUTED,
                    fontsize=7.5, transform=ax.transAxes, ha="right")

    # ---- 훈련 페이스 & 예상 기록 ----
    ax = fig.add_subplot(gs[3, 1])
    ax.axis("off")
    ax.set_facecolor(PANEL)
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, color=PANEL))
    ax.text(0, 1.06, "훈련 페이스 (VDOT 기준)", color=TXT, fontsize=12, fontweight="bold", va="bottom", transform=ax.transAxes)
    p = fit.get("paces") or {}
    rows = [("E 쉬운 러닝", f"{p.get('E_slow', '-')} ~ {p.get('E', '-')}", GOOD), ("M 마라톤", p.get("M", "-"), ACCENT),
            ("T 템포(역치)", p.get("T", "-"), WARN), ("I 인터벌", p.get("I", "-"), BAD), ("R 반복", p.get("R", "-"), "#d18cff")]
    for i, (k, val, col) in enumerate(rows):
        y = 0.88 - i * 0.14
        ax.text(0.04, y, k, color=col, fontsize=10, transform=ax.transAxes, va="center")
        ax.text(0.96, y, val, color=TXT, fontsize=10.5, fontweight="bold", transform=ax.transAxes, va="center", ha="right")
    pr = fit.get("predictions") or {}
    ax.text(0.04, 0.16, "예상 기록", color=MUTED, fontsize=9, transform=ax.transAxes, va="center")
    ax.text(0.96, 0.16, f"5K {pr.get('5K', '-')}  ·  10K {pr.get('10K', '-')}  ·  하프 {pr.get('하프', '-')}", color=TXT,
            fontsize=9, transform=ax.transAxes, va="center", ha="right")
    if fit.get("vdot_source"):
        ax.text(0.04, 0.03, f"기준: {fit['vdot_source']} (VDOT {fit.get('vdot')})", color=MUTED, fontsize=7.5,
                transform=ax.transAxes, va="center")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
