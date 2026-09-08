"""FastAPI 서버.

POST /ingest/{token}        iPhone(Health Auto Export / 단축어)이 러닝·건강 데이터를 보내는 곳
GET  /brief/{token}         오늘 브리핑 (폰에서 열어보는 페이지)
GET  /brief/{token}/json    분석 요약 JSON
POST /brief/{token}/run     지금 바로 브리핑 생성+전송 (테스트용)
GET  /kakao/callback        카카오 OAuth 콜백
GET  /health                상태 확인
"""
from __future__ import annotations

import html
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import config, db, ingest, notify, pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("yrc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    sched = BackgroundScheduler(timezone=config.TZ)
    sched.add_job(lambda: pipeline.run_all(send=True), CronTrigger(hour=config.BRIEF_HOUR, minute=config.BRIEF_MINUTE),
                  id="morning_brief", misfire_grace_time=3600)
    sched.start()
    log.info("scheduler started: daily %02d:%02d %s", config.BRIEF_HOUR, config.BRIEF_MINUTE, config.TZ)
    yield
    sched.shutdown(wait=False)


app = FastAPI(title="YRC Running Coach", lifespan=lifespan)


def _user_or_404(token: str) -> dict:
    u = db.get_user_by_token(token)
    if not u:
        raise HTTPException(404, "unknown token")
    return u


@app.get("/health")
def health():
    return {"ok": True, "users": len(db.list_users())}


@app.post("/ingest/{token}")
async def ingest_data(token: str, request: Request):
    user = _user_or_404(token)
    body = await request.body()
    payload = ingest.parse_body(body)
    if not isinstance(payload, dict):
        raise HTTPException(400, "JSON object or ##section text expected")
    workouts, metrics = ingest.parse_payload(payload)
    nw = db.upsert_workouts(user["id"], workouts)
    nm = db.upsert_metrics(user["id"], metrics)
    db.save_raw_payload(user["id"], payload)  # 단축어 디버깅용 (마지막 1건만 보관)
    log.info("ingest %s: %d workouts, %d metric-days", user["name"], nw, nm)
    return {"ok": True, "workouts": nw, "metric_days": nm,
            "runs": [{"start": w["start"], "km": w["distance_km"]} for w in workouts[-5:]],
            "hourly_hours": ingest.hourly_counts(payload)}


@app.get("/ingest/{token}/last")
def ingest_last(token: str):
    """마지막으로 받은 원본 데이터 (단축어가 뭘 보냈는지 확인용)."""
    user = _user_or_404(token)
    return db.last_raw_payload(user["id"]) or {"note": "아직 받은 데이터 없음"}


UPLOAD_PAGE = """<!doctype html><html lang=ko><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>러닝 기록 올리기</title><style>body{font-family:-apple-system,system-ui,sans-serif;background:#0b1220;color:#eef2f8;margin:0;padding:24px}
main{max-width:520px;margin:0 auto}h1{font-size:20px;margin:0 0 6px}p{color:#c7d0df;line-height:1.6}
.box{background:#141c2e;border-radius:14px;padding:18px;margin-top:14px}input[type=file]{width:100%;color:#c7d0df}
button{margin-top:14px;width:100%;padding:14px;border:0;border-radius:12px;background:#2dd4bf;color:#0b1220;font-size:16px;font-weight:700}
.ok{color:#34d399}.bad{color:#f87171}code{background:#1b2540;padding:2px 6px;border-radius:6px}</style></head>
<body><main><h1>🏃 러닝 기록 올리기</h1><p>{name}님 · 삼성 헬스 "개인 데이터 다운로드" zip 파일이나 exercise CSV, 또는 아이폰 건강 앱 내보내기 zip 을 올리면 러닝 기록이 서버에 저장됩니다.</p>
<div class=box><form method=post enctype=multipart/form-data><input type=file name=file accept=".zip,.csv,.xml" required>
<button type=submit>올리기</button></form></div>{result}
<p style="font-size:13px;color:#8b97ad">같은 러닝을 여러 번 올려도 중복되지 않습니다. 브리핑 페이지: <a style="color:#2dd4bf" href="/brief/{token}">열기</a></p></main></body></html>"""


@app.get("/upload/{token}", response_class=HTMLResponse)
def upload_page(token: str):
    user = _user_or_404(token)
    return UPLOAD_PAGE.replace("{name}", html.escape(user["name"])).replace("{token}", token).replace("{result}", "")


@app.post("/upload/{token}", response_class=HTMLResponse)
async def upload_file(token: str, request: Request):
    from . import samsung
    user = _user_or_404(token)
    form = await request.form()
    f = form.get("file")
    if f is None:
        raise HTTPException(400, "file missing")
    data = await f.read()
    name = (f.filename or "").lower()
    try:
        if name.endswith(".xml") or (name.endswith(".zip") and len(data) > 30_000_000):
            # 아이폰 건강 앱 내보내기 (크면 애플 형식일 가능성이 높음)
            import tempfile
            from . import health_export
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip" if name.endswith(".zip") else ".xml") as tmp:
                tmp.write(data)
                path = tmp.name
            workouts, metrics = health_export.parse(path, days=120)
            db.upsert_metrics(user["id"], metrics)
        else:
            workouts = samsung.parse_upload(name, data)
            if not workouts and name.endswith(".zip"):
                import tempfile
                from . import health_export
                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                    tmp.write(data)
                    path = tmp.name
                try:
                    workouts, metrics = health_export.parse(path, days=120)
                    db.upsert_metrics(user["id"], metrics)
                except Exception:  # noqa: BLE001
                    workouts = []
        n = db.upsert_workouts(user["id"], workouts)
        recent = sorted(workouts, key=lambda w: w["start"], reverse=True)[:5]
        rows = "".join(f"<li>{w['start'][:16].replace('T', ' ')} · {w['distance_km']:.2f} km · {round(w['duration_s'] / 60)}분"
                       + (f" · 평균심박 {round(w['avg_hr'])}" if w.get("avg_hr") else "") + "</li>" for w in recent)
        if n:
            result = f"<div class=box><p class=ok>✅ 러닝 {n}건을 저장했습니다.</p><ul>{rows}</ul></div>"
        else:
            result = ("<div class=box><p class=bad>러닝 기록을 찾지 못했습니다.</p><p>삼성 헬스 zip 안에 exercise CSV 가 있는지, "
                      "또는 건강 앱 내보내기 zip 이 맞는지 확인해 주세요. 파일을 크루장에게 보내주시면 확인해 드립니다.</p></div>")
    except Exception as e:  # noqa: BLE001
        log.exception("upload failed")
        result = f"<div class=box><p class=bad>처리 중 오류: {html.escape(str(e))[:200]}</p></div>"
    return UPLOAD_PAGE.replace("{name}", html.escape(user["name"])).replace("{token}", token).replace("{result}", result)


@app.get("/brief/{token}/json")
def brief_json(token: str):
    user = _user_or_404(token)
    from . import analysis
    return analysis.build_summary(user)


@app.get("/brief/{token}/card.png")
def brief_card(token: str):
    from fastapi.responses import Response
    from . import analysis, charts
    user = _user_or_404(token)
    png = charts.render_card(analysis.build_summary(user))
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/brief/{token}/run")
def brief_run(token: str, send: bool = True):
    user = _user_or_404(token)
    res = pipeline.run_for_user(user, send=send, force=True)
    res.pop("summary", None)
    return res


@app.post("/run-all/{admin_key}")
def run_all_users(admin_key: str):
    """cron-job 이 07:00 에 호출: 활성 크루원 전원에게 브리핑. ADMIN_KEY 환경변수와 일치해야 함."""
    import os
    key = os.getenv("ADMIN_KEY", "").strip()
    if not key or admin_key != key:
        raise HTTPException(403, "bad admin key")
    results = pipeline.run_all(send=True)
    return [{k: v for k, v in r.items() if k not in ("text", "summary")} for r in results]


@app.post("/brief/{token}/publish")
async def brief_publish(token: str, request: Request):
    """외부(예: Claude 구독 routine)가 써준 브리핑 본문을 받아 저장하고 전송. body: {"text": "..."}"""
    from datetime import date
    from . import analysis
    user = _user_or_404(token)
    body = await request.json()
    text = (body or {}).get("text", "").strip()
    if not text:
        raise HTTPException(400, "text missing")
    delivered = notify.deliver(user, text)
    db.save_briefing(user["id"], config.local_today().isoformat(), analysis.build_summary(user), text, user.get("channel"), delivered)
    return {"ok": True, "delivered": delivered}


@app.get("/strava/connect/{token}")
def strava_connect(token: str):
    from fastapi.responses import RedirectResponse
    from . import strava
    user = _user_or_404(token)
    if not strava.enabled():
        raise HTTPException(503, "STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET 이 설정되지 않았습니다")
    return RedirectResponse(strava.authorize_url(user))


@app.get("/strava/callback")
def strava_callback(code: str = "", state: str = "", error: str = ""):
    from . import strava
    if error or not code:
        return HTMLResponse(f"<h3>Strava 연결 취소됨: {html.escape(error or 'code missing')}</h3>", status_code=400)
    user = db.get_user_by_token(state) if state else None
    if not user:
        raise HTTPException(400, "state(user token) missing")
    tok = strava.exchange_code(code)
    strava.save_tokens(user, tok)
    user = db.get_user(user["id"])
    try:
        n = strava.sync(user)
    except Exception as e:  # noqa: BLE001
        n = f"동기화 실패: {e}"
    seed_hint = html.escape(user["strava_refresh_token"])
    return HTMLResponse(
        f"<div style='font-family:sans-serif;padding:20px;line-height:1.6'><h3>✅ Strava 연결 완료</h3>"
        f"<p>{html.escape(user['name'])}님, 최근 56일 러닝 {n}건을 가져왔습니다.</p>"
        f"<p style='color:#666;font-size:13px'>Render 무료 플랜을 쓰면 SEED_USERS 에 아래 값을 추가해야 재시작 후에도 연결이 유지됩니다:<br>"
        f"<code>\"strava_refresh_token\":\"{seed_hint}\"</code></p></div>")


@app.post("/strava/sync/{token}")
def strava_sync(token: str):
    from . import strava
    user = _user_or_404(token)
    return {"ok": True, "runs": strava.sync(user)}


@app.get("/kakao/callback")
def kakao_callback(code: str = "", state: str = ""):
    """state 에 사용자 token 을 넣어 호출: /kakao/callback?code=...&state=<user token>"""
    if not code:
        raise HTTPException(400, "code missing")
    tok = notify.kakao_exchange_code(code)
    if state:
        user = db.get_user_by_token(state)
        if user:
            db.update_user(user["id"], channel="kakao", kakao_access_token=tok["access_token"],
                           kakao_refresh_token=tok.get("refresh_token"))
            return HTMLResponse("<h3>카카오 연결 완료. 이 창을 닫아도 됩니다.</h3>")
    return JSONResponse(tok)


PAGE = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>YRC 아침 브리핑</title>
<style>body{font-family:-apple-system,system-ui,sans-serif;background:#0f1115;color:#e8e8e8;margin:0;padding:20px}
main{max-width:520px;margin:0 auto}pre{white-space:pre-wrap;line-height:1.55;font:16px/1.55 -apple-system,system-ui,sans-serif;background:#181b22;padding:18px;border-radius:14px}
h1{font-size:18px;color:#8fd3ff;margin:4px 0 14px}small{color:#888}.g{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px}
.c{background:#181b22;border-radius:12px;padding:12px}.c b{display:block;font-size:22px;color:#fff}.c span{color:#999;font-size:12px}</style></head>
<body><main><h1>🏃 YRC 러닝 코치</h1><img src="card.png?t={created}" alt="브리핑 카드" style="width:100%;border-radius:14px;margin-bottom:12px"><pre>{text}</pre>
<div class=g><div class=c><b>{km7}</b><span>지난 7일 km</span></div><div class=c><b>{runs7}</b><span>지난 7일 러닝 횟수</span></div>
<div class=c><b>{acwr}</b><span>ACWR (0.8~1.3 안전)</span></div><div class=c><b>{rhr}</b><span>안정심박 (평소 {rhr_base})</span></div></div>
<p><small>생성 {created} · 채널 {channel} · 데이터: 러닝 {runs56}회/56일</small></p></main></body></html>"""


@app.get("/brief/{token}", response_class=HTMLResponse)
def brief_page(token: str):
    import json
    user = _user_or_404(token)
    b = db.latest_briefing(user["id"])
    if not b:
        return HTMLResponse("<p style='font-family:sans-serif;padding:20px'>아직 브리핑이 없습니다. 데이터가 들어오면 다음 아침에 생성됩니다.</p>")
    s = json.loads(b["summary"])
    rec = s["recovery"]
    fmt = lambda v: "-" if v is None else (f"{v:.0f}" if isinstance(v, float) else str(v))
    return PAGE.replace("{text}", html.escape(b["text"])).replace("{created}", b["created_at"]) \
        .replace("{km7}", fmt(s["volume"]["last7_km"])).replace("{runs7}", fmt(s["volume"]["runs_last7"])) \
        .replace("{acwr}", fmt(s["volume"]["acwr"])).replace("{rhr}", fmt(rec["today"].get("resting_hr"))) \
        .replace("{rhr_base}", fmt(rec["baseline30d"].get("resting_hr"))) \
        .replace("{created}", b["created_at"]).replace("{channel}", str(b.get("channel"))) \
        .replace("{runs56}", str(s["data_points"]["runs_56d"]))
