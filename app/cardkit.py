"""카드 공통 요소: 밝은 테마, 폰트, 이모지 스티커(Twemoji PNG), 둥근 패널, 출석 달력."""
from __future__ import annotations

from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Ellipse, FancyBboxPatch  # noqa: E402

from . import config  # noqa: E402

# ---- 밝은 팔레트 ----
BG, PANEL, PANEL2 = "#f4f7fb", "#ffffff", "#eef3f9"
TXT, TXT2, MUTED, GRID, LINE = "#1e2a44", "#4a5670", "#8b95a8", "#e6ebf3", "#dfe5ee"
CORAL, MINT, SKY, SUN, GRAPE = "#ff6b6b", "#20c9b0", "#4dabf7", "#ffb020", "#845ef7"
GOOD, WARN, BAD = "#2fb36f", "#f59f00", "#e03131"
ZONE_EASY, ZONE_MID, ZONE_HARD = SKY, SUN, CORAL
ACCENT_RUN, ACCENT_SWIM, HIST = CORAL, SKY, "#a5b4fc"
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

EMOJI = {"run": "1f3c3", "swim": "1f3ca", "fire": "1f525", "muscle": "1f4aa", "salad": "1f957", "check": "2705",
         "star": "1f31f", "zzz": "1f4a4", "medal": "1f3c5", "bolt": "26a1", "foot": "1f9b6", "rice": "1f35a",
         "calendar": "1f4c5", "bed": "1f6cc", "star2": "2b50", "clap": "1f44f", "target": "1f3af", "chart": "1f4c8",
         "drop": "1f4a7", "plate": "1f37d"}

_FONT_READY = False
FONT = "sans-serif"
_IMG_CACHE: dict = {}


def setup_font():
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
        plt.rcParams["font.family"] = [FONT] + [f for f in fams[1:] if f != FONT] + ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    _FONT_READY = True


def emoji(fig, name: str, x: float, y: float, size: float = 0.05, ax=None):
    """이모지 PNG 를 figure 좌표(x, y = 중심)에 그린다. size 는 figure 폭 기준 비율."""
    code = EMOJI.get(name, name)
    p = config.ASSETS_DIR / "emoji" / f"{code}.png"
    if not p.exists():
        return
    if code not in _IMG_CACHE:
        _IMG_CACHE[code] = mpimg.imread(str(p))
    img = _IMG_CACHE[code]
    w, h = fig.get_size_inches()
    sw = size
    sh = size * w / h
    if ax is not None:  # ax 좌표 → figure 좌표
        x, y = fig.transFigure.inverted().transform(ax.transAxes.transform((x, y)))
    ia = fig.add_axes([x - sw / 2, y - sh / 2, sw, sh])
    ia.imshow(img)
    ia.axis("off")


def panel(ax, title=None, sub=None, icon=None, fig=None):
    ax.set_facecolor("none")
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.03", transform=ax.transAxes,
                                facecolor=PANEL, edgecolor=LINE, linewidth=1, clip_on=False, zorder=-5))
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9.5, length=0)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.grid(False, axis="x")
    ax.set_axisbelow(True)
    tx = 0.0
    if icon and fig is not None:
        emoji(fig, icon, 0.02, 1.26, size=0.032, ax=ax)
        tx = 0.06
    if title:
        ax.text(tx, 1.20, title, color=TXT, fontsize=13.5, fontweight="bold", transform=ax.transAxes, va="bottom")
    if sub:
        ax.text(tx, 1.06, sub, color=MUTED, fontsize=8.5, transform=ax.transAxes, va="bottom")


def rounded(ax, x, y, w, h, color, r=0.02, edge="none"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", transform=ax.transAxes,
                                facecolor=color, edgecolor=edge, clip_on=False))


def header(fig, ax, title: str, date_str: str, ready: tuple, brand: str, mascot: str, eyebrow: str):
    ax.axis("off")
    emoji(fig, mascot, 0.045, 0.55, size=0.075, ax=ax)
    ax.text(0.10, 1.0, eyebrow, color=brand, fontsize=9.5, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.10, 0.62, title, color=TXT, fontsize=24, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.10, 0.12, date_str, color=MUTED, fontsize=11.5, va="top", transform=ax.transAxes)
    label, col = ready
    rounded(ax, 0.78, 0.55, 0.22, 0.34, col, r=0.12)
    ax.text(0.89, 0.72, label, color="white", fontsize=12.5, fontweight="bold", ha="center", va="center", transform=ax.transAxes)


def attendance(fig, ax, today: date, active_dates: set, sport: str, brand: str):
    """이번 주 월~일 출석 달력. 활동한 날은 도장(이모지), 오늘은 점선 테두리, 미래는 흐리게."""
    ax.axis("off")
    panel(ax, "이번 주 출석", None, icon="calendar", fig=fig)
    monday = today - timedelta(days=today.weekday())
    days = [monday + timedelta(days=i) for i in range(7)]
    n_active = sum(1 for d in days if d.isoformat() in active_dates)
    streak = 0
    d = today
    while d.isoformat() in active_dates:
        streak += 1
        d -= timedelta(days=1)
    if streak == 0:
        d = today - timedelta(days=1)
        while d.isoformat() in active_dates:
            streak += 1
            d -= timedelta(days=1)
    right = f"{n_active}/7"
    ax.text(1.0, 1.20, right, color=brand, fontsize=15, fontweight="bold", transform=ax.transAxes, va="bottom", ha="right")
    if streak >= 2:
        ax.text(0.90, 1.22, f"{streak}일 연속", color=SUN, fontsize=10.5, fontweight="bold", transform=ax.transAxes, va="bottom", ha="right")
        emoji(fig, "fire", 0.925, 1.26, size=0.022, ax=ax)
    fig.canvas.draw()
    bb = ax.get_window_extent()
    ratio = bb.width / bb.height if bb.height else 1
    rx = 0.034
    cy = 0.46
    for i, d in enumerate(days):
        cx = 0.07 + i * 0.145
        is_active = d.isoformat() in active_dates
        is_today = d == today
        is_future = d > today
        ax.text(cx, 0.88, WEEKDAYS[i], color=(brand if is_today else (MUTED if is_future else TXT2)), fontsize=10,
                fontweight="bold" if is_today else "normal", ha="center", va="center", transform=ax.transAxes)
        ax.text(cx, 0.08, str(d.day), color=MUTED if is_future else TXT2, fontsize=8.5, ha="center", va="center", transform=ax.transAxes)
        fill = PANEL2 if not is_active else ("#e6fbf6" if brand == MINT else "#fff1f0" if brand == CORAL else "#e8f4ff")
        ax.add_patch(Ellipse((cx, cy), 2 * rx, 2 * rx * ratio, transform=ax.transAxes, facecolor=fill,
                             edgecolor=(brand if is_today else (LINE if not is_active else "none")), linewidth=2 if is_today else 1,
                             linestyle="--" if (is_today and not is_active) else "-", clip_on=False))
        if is_active:
            emoji(fig, sport, cx, cy, size=0.040, ax=ax)
        elif is_future:
            ax.text(cx, cy, "·", color=LINE, fontsize=14, ha="center", va="center", transform=ax.transAxes)
        elif not is_today:
            ax.text(cx, cy, "—", color=LINE, fontsize=11, ha="center", va="center", transform=ax.transAxes)
    return n_active, streak
