"""하루 한 번 도는 파이프라인: 분석 → 브리핑 생성 → 전송 → 저장."""
from __future__ import annotations

import logging
from datetime import date

from . import analysis, coach, db, notify, strava

log = logging.getLogger(__name__)


def run_for_user(user: dict, send: bool = True, force: bool = False) -> dict:
    from . import config
    today = config.local_today().isoformat()
    existing = db.latest_briefing(user["id"])
    if existing and existing["date"] == today and not force:
        return {"user": user["name"], "skipped": True, "reason": "already briefed today"}

    try:
        strava.sync(user)
    except Exception as e:  # noqa: BLE001
        log.warning("strava sync failed for %s: %s", user["name"], e)
    png = None
    if (user.get("sport") or "run") == "swim":
        from . import charts_swim, swim
        summary = swim.build_summary(user)
        text, generator = swim.briefing_text(summary), "rules-swim"
        try:
            png = charts_swim.render_card(summary)
        except Exception as e:  # noqa: BLE001
            log.warning("swim chart render failed for %s: %s", user["name"], e)
    else:
        summary = analysis.build_summary(user)
        text, generator = coach.make_briefing(user, summary)
        try:
            from . import charts
            png = charts.render_card(summary)
        except Exception as e:  # noqa: BLE001
            log.warning("chart render failed for %s: %s", user["name"], e)
    delivered = False
    if send:
        try:
            delivered = notify.deliver(user, text, png=png)
        except Exception as e:  # noqa: BLE001
            log.exception("delivery failed for %s: %s", user["name"], e)
    db.save_briefing(user["id"], today, summary, text, user.get("channel"), delivered)
    return {"user": user["name"], "generator": generator, "delivered": delivered, "text": text, "summary": summary}


def run_all(send: bool = True) -> list:
    results = []
    for u in db.list_users():
        try:
            results.append(run_for_user(u, send=send))
        except Exception as e:  # noqa: BLE001
            log.exception("briefing failed for %s", u["name"])
            results.append({"user": u["name"], "error": str(e)})
    return results
