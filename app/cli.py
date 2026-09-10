"""관리용 CLI.

python -m app.cli add-user --name 홍길동 --channel telegram --chat-id 12345678 --goal "11월 하프 1:50" --age 34
python -m app.cli users
python -m app.cli set-user 1 --goal "..." --weekly-days 4 --notes "왼쪽 무릎 주의"
python -m app.cli telegram-setup --name 김창희 --age 30 --goal "..."   # 봇에 /start 한 사람을 자동 등록 (추천)
python -m app.cli telegram-chats            # 봇에 말 건 사람들의 chat_id 확인
python -m app.cli kakao-url 1               # 카카오 나에게보내기 연결 URL 출력
python -m app.cli ingest 1 samples/health_auto_export.json
python -m app.cli brief 1 [--no-send] [--force]
python -m app.cli brief-all
python -m app.cli demo                      # 가짜 데이터 6주치로 전체 흐름 테스트
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config, db, ingest, notify, pipeline


def cmd_add_user(a):
    fields = {k: v for k, v in dict(telegram_chat_id=a.chat_id, ntfy_topic=a.ntfy_topic, goal=a.goal,
                                   age=a.age, max_hr=a.max_hr, weekly_days=a.weekly_days, notes=a.notes,
                                   sport=a.sport, weight_kg=a.weight_kg, height_cm=a.height_cm, sex=a.sex,
                                   target_weight_kg=a.target_weight_kg, activity=a.activity, diet_notes=a.diet_notes).items() if v is not None}
    u = db.add_user(a.name, a.channel, token=a.token, **fields)
    print(f"사용자 추가됨: id={u['id']} name={u['name']} channel={u['channel']}")
    print(f"  데이터 전송 URL (Health Auto Export / 단축어에 넣기):\n  {config.PUBLIC_BASE_URL}/ingest/{u['token']}")
    print(f"  브리핑 페이지:\n  {config.PUBLIC_BASE_URL}/brief/{u['token']}")


def cmd_users(a):
    for u in db.list_users(active_only=False):
        print(f"[{u['id']}] {u['name']:8s} ch={u['channel']:8s} goal={u.get('goal') or '-'}  active={u['active']}")
        print(f"      ingest: {config.PUBLIC_BASE_URL}/ingest/{u['token']}")


def cmd_export_seed(a):
    """Render 환경변수 SEED_USERS 에 넣을 JSON 출력 (DB 초기화 대비)."""
    keys = ("name", "token", "channel", "telegram_chat_id", "ntfy_topic", "age", "max_hr", "goal", "weekly_days", "notes",
            "strava_refresh_token", "sport", "weight_kg", "height_cm", "sex", "target_weight_kg", "activity", "diet_notes")
    users = [{k: u[k] for k in keys if u.get(k) is not None} for u in db.list_users()]
    print(json.dumps(users, ensure_ascii=False, separators=(",", ":")))


def cmd_set_user(a):
    fields = {k: v for k, v in dict(channel=a.channel, telegram_chat_id=a.chat_id, ntfy_topic=a.ntfy_topic, goal=a.goal,
                                   age=a.age, max_hr=a.max_hr, weekly_days=a.weekly_days, notes=a.notes,
                                   active=a.active, sport=a.sport, weight_kg=a.weight_kg, height_cm=a.height_cm, sex=a.sex,
                                   target_weight_kg=a.target_weight_kg, activity=a.activity, diet_notes=a.diet_notes).items() if v is not None}
    db.update_user(a.user_id, **fields)
    print("수정됨:", db.get_user(a.user_id))


def cmd_telegram_chats(a):
    ups = notify.telegram_updates()
    if not ups:
        print("아직 봇에게 메시지를 보낸 사람이 없습니다. 텔레그램에서 봇을 찾아 '/start' 를 보내세요.")
    for u in ups:
        print(f"chat_id={u['chat_id']}  name={u['name']}  last='{u['text']}'")


def cmd_telegram_setup(a):
    """봇에 /start 를 보낸 사람을 찾아 사용자로 등록 (텔레그램 원스텝 온보딩)."""
    import time

    if not config.TELEGRAM_BOT_TOKEN:
        print(".env 의 TELEGRAM_BOT_TOKEN 이 비어 있습니다. @BotFather 에서 토큰을 받아 넣어주세요.")
        return
    me = notify.requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe", timeout=20).json()
    if not me.get("ok"):
        print("봇 토큰이 잘못됐습니다:", me)
        return
    bot = me["result"]["username"]
    print(f"봇 @{bot} 확인. 폰 텔레그램에서 https://t.me/{bot} 을 열고 '시작(/start)' 을 누르세요.")
    print("기다리는 중... (최대 3분)")
    chat = None
    for _ in range(36):
        ups = notify.telegram_updates()
        if ups:
            chat = ups[-1]
            break
        time.sleep(5)
    if not chat:
        print("메시지를 받지 못했습니다. /start 를 보낸 뒤 다시 실행하세요.")
        return
    existing = [u for u in db.list_users(active_only=False) if u.get("telegram_chat_id") == chat["chat_id"]]
    if existing:
        u = existing[0]
        print(f"이미 등록된 사용자입니다: id={u['id']} {u['name']}")
    else:
        fields = {k: v for k, v in dict(goal=a.goal, age=a.age, max_hr=a.max_hr, weekly_days=a.weekly_days, notes=a.notes).items() if v is not None}
        u = db.add_user(a.name or chat["name"] or "러너", "telegram", telegram_chat_id=chat["chat_id"], **fields)
        print(f"사용자 등록 완료: id={u['id']} name={u['name']} chat_id={chat['chat_id']}")
    notify.send_telegram(chat["chat_id"], f"✅ YRC 러닝 코치 연결 완료! {u['name']}님, 매일 아침 {config.BRIEF_HOUR:02d}:{config.BRIEF_MINUTE:02d}에 브리핑을 보내드릴게요.\n\n"
                                          f"데이터 전송 URL (Health Auto Export 에 등록):\n{config.PUBLIC_BASE_URL}/ingest/{u['token']}\n\n"
                                          f"브리핑 페이지:\n{config.PUBLIC_BASE_URL}/brief/{u['token']}")
    print("텔레그램으로 안내 메시지를 보냈습니다.")
    print(f"  데이터 전송 URL: {config.PUBLIC_BASE_URL}/ingest/{u['token']}")
    print(f"  브리핑 페이지:  {config.PUBLIC_BASE_URL}/brief/{u['token']}")


def cmd_kakao_url(a):
    u = db.get_user(a.user_id)
    print("아래 URL 을 폰/PC 브라우저에서 열고 동의하세요 (state 로 사용자 토큰 전달):")
    print(notify.kakao_authorize_url() + f"&state={u['token']}")


def cmd_ingest(a):
    with open(a.file, encoding="utf-8") as f:
        payload = json.load(f)
    w, m = ingest.parse_payload(payload)
    print(f"파싱: 러닝 {len(w)}건, 지표 {len(m)}일")
    print(" ->", db.upsert_workouts(a.user_id, w), "workouts,", db.upsert_metrics(a.user_id, m), "metric-days 저장")


def cmd_import_health(a):
    """건강 앱 내보내기(zip/xml)에서 러닝·지표 가져오기."""
    from . import health_export
    w, m = health_export.parse(a.file, days=a.days)
    print(f"파싱: 러닝 {len(w)}건, 지표 {len(m)}일 (최근 {a.days}일)")
    print(" ->", db.upsert_workouts(a.user_id, w), "workouts,", db.upsert_metrics(a.user_id, m), "metric-days 저장")
    for x in w[-5:]:
        print(f"   {x['start'][:16]}  {x['distance_km']}km  {round(x['duration_s']/60)}분  HR {x['avg_hr'] and round(x['avg_hr'])}")


def cmd_strava_url(a):
    u = db.get_user(a.user_id)
    print("폰이나 PC 브라우저에서 이 주소를 열고 Strava 에 동의하세요:")
    print(f"{config.PUBLIC_BASE_URL}/strava/connect/{u['token']}")


def cmd_brief(a):
    u = db.get_user(a.user_id)
    res = pipeline.run_for_user(u, send=not a.no_send, force=a.force)
    if res.get("skipped"):
        print("오늘 브리핑이 이미 있습니다. --force 로 다시 생성하세요.")
        return
    print(f"[generator={res['generator']} delivered={res['delivered']}]\n")
    print(res["text"])


def cmd_brief_all(a):
    for r in pipeline.run_all(send=not a.no_send):
        print(r.get("user"), "->", {k: v for k, v in r.items() if k not in ("text", "summary", "user")})


def cmd_demo(a):
    """6주치 가짜 데이터로 파이프라인 확인."""
    import random
    from datetime import date, datetime, timedelta

    random.seed(7)
    u = db.add_user("데모러너", "none", goal="11월 하프마라톤 1시간 55분", age=34, weekly_days=4)
    today = date.today()
    workouts, metrics = [], []
    for i in range(42, 0, -1):
        d = today - timedelta(days=i)
        weekly_km = 22 + (42 - i) * 0.35
        metrics.append({"date": d.isoformat(), "resting_hr": 52 + random.randint(-2, 3), "hrv": 55 + random.randint(-8, 8),
                        "sleep_h": round(6.2 + random.random() * 1.6, 1), "steps": 6000 + random.randint(0, 5000)})
        if d.weekday() in (1, 3, 5, 6):
            if d.weekday() == 6:
                km, pace = weekly_km * 0.35, 385
            elif d.weekday() == 3:
                km, pace = weekly_km * 0.22, 330
            else:
                km, pace = weekly_km * 0.2, 372
            km = round(km + random.uniform(-0.6, 0.6), 2)
            pace += random.randint(-8, 8) - (42 - i) * 0.4
            start = datetime.combine(d, datetime.min.time()).replace(hour=6, minute=random.randint(0, 40))
            dur = km * pace
            workouts.append({"start": start.isoformat(timespec="seconds"), "end": (start + timedelta(seconds=dur)).isoformat(timespec="seconds"),
                             "duration_s": dur, "distance_km": km, "avg_hr": 148 + (10 if pace < 340 else 0) + random.randint(-4, 4),
                             "max_hr": 172 + random.randint(0, 8), "energy_kcal": km * 62, "elev_gain_m": random.randint(10, 80),
                             "source": "demo", "raw": {}})
    db.upsert_workouts(u["id"], workouts)
    db.upsert_metrics(u["id"], metrics)
    print(f"데모 사용자 id={u['id']} 생성, 러닝 {len(workouts)}건 / 지표 {len(metrics)}일 저장\n")
    res = pipeline.run_for_user(u, send=False, force=True)
    print(f"[generator={res['generator']}]\n")
    print(res["text"])
    print("\n브리핑 페이지:", f"{config.PUBLIC_BASE_URL}/brief/{u['token']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="yrc-coach")
    sp = p.add_subparsers(dest="cmd", required=True)

    def user_fields(q):
        q.add_argument("--channel", choices=["telegram", "kakao", "ntfy", "none"])
        q.add_argument("--chat-id"); q.add_argument("--ntfy-topic"); q.add_argument("--goal")
        q.add_argument("--age", type=int); q.add_argument("--max-hr", type=int)
        q.add_argument("--weekly-days", type=int); q.add_argument("--notes")
        q.add_argument("--sport", choices=["run", "swim"]); q.add_argument("--weight", type=float, dest="weight_kg")
        q.add_argument("--height", type=float, dest="height_cm"); q.add_argument("--sex", choices=["M", "F"])
        q.add_argument("--target-weight", type=float, dest="target_weight_kg")
        q.add_argument("--activity", choices=["sedentary", "light", "active"]); q.add_argument("--diet-notes")

    q = sp.add_parser("add-user"); q.add_argument("--name", required=True); q.add_argument("--token", help="기존 토큰 재사용 (DB 초기화 후 복구용)")
    user_fields(q); q.set_defaults(channel="telegram", fn=cmd_add_user)
    q = sp.add_parser("users"); q.set_defaults(fn=cmd_users)
    q = sp.add_parser("export-seed"); q.set_defaults(fn=cmd_export_seed)
    q = sp.add_parser("set-user"); q.add_argument("user_id", type=int); user_fields(q); q.add_argument("--active", type=int); q.set_defaults(fn=cmd_set_user)
    q = sp.add_parser("telegram-chats"); q.set_defaults(fn=cmd_telegram_chats)
    q = sp.add_parser("telegram-setup"); q.add_argument("--name"); q.add_argument("--goal"); q.add_argument("--age", type=int)
    q.add_argument("--max-hr", type=int); q.add_argument("--weekly-days", type=int); q.add_argument("--notes"); q.set_defaults(fn=cmd_telegram_setup)
    q = sp.add_parser("kakao-url"); q.add_argument("user_id", type=int); q.set_defaults(fn=cmd_kakao_url)
    q = sp.add_parser("ingest"); q.add_argument("user_id", type=int); q.add_argument("file"); q.set_defaults(fn=cmd_ingest)
    q = sp.add_parser("import-health"); q.add_argument("user_id", type=int); q.add_argument("file"); q.add_argument("--days", type=int, default=90); q.set_defaults(fn=cmd_import_health)
    q = sp.add_parser("strava-url"); q.add_argument("user_id", type=int); q.set_defaults(fn=cmd_strava_url)
    q = sp.add_parser("brief"); q.add_argument("user_id", type=int); q.add_argument("--no-send", action="store_true"); q.add_argument("--force", action="store_true"); q.set_defaults(fn=cmd_brief)
    q = sp.add_parser("brief-all"); q.add_argument("--no-send", action="store_true"); q.set_defaults(fn=cmd_brief_all)
    q = sp.add_parser("demo"); q.set_defaults(fn=cmd_demo)

    a = p.parse_args(argv)
    db.init()
    a.fn(a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
