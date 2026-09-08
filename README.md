# YRC Running Coach

아이폰 건강 데이터로 매일 아침 러닝 브리핑(어제 평가 · 오늘 훈련 · 이번 주 계획 · 보완점)을 폰으로 받는 개인/크루용 코치 서버입니다.

```
iPhone 건강앱 ──(Health Auto Export 앱, 매일 자동)──▶ POST /ingest/{token}
                                                            │  SQLite 저장
                        매일 07:00 ──▶ 분석(ACWR·페이스·회복지표) ──▶ Claude 코치 ──▶ 텔레그램 / 카톡(나에게) / ntfy 푸시
                                                                                   └▶ /brief/{token} 웹페이지
```

- 1단계(지금): 크루장 혼자. 2단계: `add-user` 로 크루원을 한 명씩 추가하면 각자 토큰으로 데이터를 보내고 각자 브리핑을 받습니다.
- Claude API 키가 없어도 규칙 기반 브리핑으로 동작합니다. 키를 넣으면 Claude Opus 5 가 코치 역할을 합니다.

---

## 1. 서버 띄우기

폰이 데이터를 보내려면 서버가 인터넷에 있어야 합니다. 가장 쉬운 방법은 Railway 입니다 (Fly.io, Render 도 동일).

1. 이 폴더를 GitHub 저장소에 올립니다.
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub → 이 저장소 선택. `Dockerfile` 이 있어서 자동 빌드됩니다.
3. Variables 탭에 `.env.example` 내용을 넣습니다. 최소:
   - `ANTHROPIC_API_KEY`
   - `PUBLIC_BASE_URL` = Railway 가 준 도메인 (Settings → Networking → Generate Domain)
   - `DB_PATH=/data/yrc.db` 그리고 Volume 을 `/data` 에 마운트 (데이터가 재배포 후에도 남도록)
   - 알림 채널 키 (아래 3장)
4. 배포 후 `https://<도메인>/health` 가 `{"ok": true}` 를 돌려주면 성공.

로컬에서 먼저 돌려보기:

```bash
pip install -r requirements.txt
cp .env.example .env        # 값 채우기
python -m app.cli demo      # 가짜 6주 데이터로 브리핑 생성해보기
uvicorn app.main:app --reload
```

> 내 PC 에서 계속 돌리고 싶다면 Cloudflare Tunnel(무료)로 공개 URL 을 만들면 됩니다. 단, PC 가 꺼지면 데이터 수신도 멈춥니다.

## 2. 사용자(나) 등록

```bash
python -m app.cli add-user --name 크루장 --channel telegram --chat-id <아래 3장에서 얻음> \
  --age 34 --goal "11월 하프 1:50" --weekly-days 4 --notes "왼쪽 무릎 과거 부상"
```

출력되는 두 URL 을 메모하세요.

- `.../ingest/<token>` : 폰이 데이터를 보낼 주소
- `.../brief/<token>`  : 오늘 브리핑 페이지 (홈 화면에 추가해두면 편함)

Railway 에서는 서비스의 Shell 탭에서 같은 명령을 실행하면 됩니다.

## 3. 알림 채널 고르기

| 채널 | 난이도 | 크루 확장 | 비고 |
|---|---|---|---|
| **Telegram 봇** (추천) | 5분 | 쉬움 (각자 봇에 /start) | 긴 글 그대로 도착 |
| **카카오톡 나에게 보내기** | 15분 | 어려움 (친구에게 보내기는 사업자 검수 필요) | 200자 + "전체 보기" 버튼 |
| **ntfy 푸시** | 2분 | 쉬움 (주제 이름만 공유) | 앱 설치 필요, 계정 불필요 |

### Telegram (기본 채널)
1. 텔레그램에서 `@BotFather` → `/newbot` → 봇 이름 지정 → 토큰을 `.env` 의 `TELEGRAM_BOT_TOKEN` 에.
2. 아래 명령을 실행하고, 폰에서 봇을 열어 `/start` 를 누르면 자동으로 등록되고 안내 메시지가 옵니다.
   ```bash
   python -m app.cli telegram-setup --name 김창희 --age 30 --goal "11월 하프 1:50" --weekly-days 4
   ```
   크루원도 같은 명령으로 한 명씩 추가합니다 (크루원이 /start 를 누른 직후 실행).
3. 수동으로 하려면 `python -m app.cli telegram-chats` 로 `chat_id` 를 보고 `add-user --chat-id` 에 넣습니다.

### 카카오톡 (나에게 보내기)
1. [developers.kakao.com](https://developers.kakao.com) → 내 애플리케이션 → 앱 추가 → 앱 키의 **REST API 키**를 `KAKAO_REST_API_KEY` 에.
2. 제품 설정 → 카카오 로그인 활성화, Redirect URI 에 `https://<도메인>/kakao/callback` 등록.
3. 동의항목에서 **카카오톡 메시지 전송(talk_message)** 을 "선택 동의"로 켭니다.
4. `python -m app.cli kakao-url <user_id>` 가 출력한 URL 을 폰에서 열고 동의 → 자동으로 토큰이 저장되고 채널이 kakao 로 바뀝니다.
   (refresh 토큰은 2달마다 자동 갱신됩니다. 2달 이상 서버가 멈춰 있으면 다시 4번을 하면 됩니다.)

### ntfy
1. App Store 에서 **ntfy** 설치, 주제 이름을 하나 만듭니다 (예: `yrc-hong-8f2k`, 아무나 못 맞추게 랜덤하게).
2. `add-user --channel ntfy --ntfy-topic yrc-hong-8f2k`

## 4. 아이폰에서 데이터 자동 전송

### 방법 A: Health Auto Export 앱 (추천, 가장 안정적)
App Store 의 **Health Auto Export - JSON+CSV** (유료, 1회 구매 또는 구독).

1. 앱 → Automations → `+` → **REST API**
2. URL: `https://<도메인>/ingest/<token>`  Method: POST, Format: JSON
3. Data 에서 체크: **Workouts**, Metrics 중 `Resting Heart Rate`, `Heart Rate Variability`, `Sleep Analysis`, `Step Count`, `VO2 Max`, `Weight`
4. Period: **Previous Day** (또는 Today + 하루 2회), Schedule: 매일 **06:30** (브리핑 07:00 보다 앞)
5. "Run Now" 로 한 번 보내보고 서버 로그에 `ingest 크루장: 1 workouts` 가 찍히는지 확인.

> 아이폰 자동화는 앱이 백그라운드에서 깨어나야 돌아갑니다. 앱 설정의 백그라운드 새로고침을 켜두고, 며칠 데이터가 안 오면 앱을 한 번 열어주세요. 지난 데이터는 Period 를 늘려서 한 번에 다시 보내면 됩니다 (중복은 서버가 알아서 합칩니다).

### 방법 B: 단축어(Shortcuts) 자동화 (무료)
1. 단축어 앱 → 새 단축어:
   - `건강 샘플 찾기` (유형: 운동, 어제 이후)  → 반복: 각 항목에 대해 `사전` 만들기 {type: "Running", start, end, distance_km, avg_hr}
   - `건강 샘플 찾기` (안정 시 심박수, 최근 1개) 등을 `metrics` 사전에
   - `URL 콘텐츠 가져오기` → POST, JSON 본문 `{"workouts": [...], "metrics": {...}}` → `https://<도메인>/ingest/<token>`
2. 자동화 → 매일 06:30 → 이 단축어 실행 (확인 없이 실행 켜기)

서버는 아래 단순 포맷도 받습니다:

```json
{"workouts": [{"type": "Running", "start": "2026-09-07T06:00:00", "end": "2026-09-07T06:35:00", "distance_km": 6.4, "avg_hr": 152}],
 "metrics": {"date": "2026-09-08", "resting_hr": 53, "hrv": 58, "sleep_h": 6.8}}
```

### 처음 한 번: 과거 데이터 넣기
분석은 최근 8주를 봅니다. Health Auto Export 의 Export 탭에서 지난 2~3달 Workouts 를 JSON 으로 내보내고 서버에 한 번 넣으면 첫날부터 제대로 된 처방이 나옵니다.

```bash
python -m app.cli ingest <user_id> export.json
```

## 5. 브리핑 확인 / 강제 실행

```bash
python -m app.cli brief <user_id> --force        # 지금 생성 + 전송
python -m app.cli brief <user_id> --no-send      # 전송 없이 내용만
python -m app.cli brief-all                      # 모든 활성 사용자
```

또는 `POST https://<도메인>/brief/<token>/run` 을 호출해도 됩니다. 매일 07:00(`BRIEF_HOUR`)에 자동으로 전원에게 나갑니다.

## 6. 크루원 추가 (2단계)

크루원마다 `add-user` 한 번. 각자 받은 `ingest` URL 을 본인 폰의 Health Auto Export 에 넣고, 텔레그램 봇에 `/start` 만 하면 끝입니다.

```bash
python -m app.cli add-user --name 민수 --channel telegram --chat-id 987654 --age 29 --goal "첫 10km 완주"
python -m app.cli set-user 3 --notes "야간 근무, 아침 러닝 불가"     # 나중에 수정
python -m app.cli set-user 3 --active 0                               # 잠시 중단
```

크루 단체 요약(주간 리더보드, 전체 볼륨 추세)은 데이터가 쌓이면 `pipeline.py` 에 `run_crew_summary` 를 추가해 텔레그램 그룹으로 보내면 됩니다.

## 7. 분석 로직 (analysis.py)

| 지표 | 의미 | 코치가 쓰는 기준 |
|---|---|---|
| 주간 거리 / 지난주 대비 | 볼륨 추세 | 주당 +10% 이내 |
| ACWR | 최근 7일 ÷ 최근 28일 주평균 | 0.8~1.3 안전, 1.5↑ 부상 위험 |
| 부하(TRIMP 근사) | 분 × 평균심박/최대심박 | 단조로움(monotony) 2.0↑ 주의 |
| 페이스 추세 | 최근 2주 vs 이전 2주 평균 페이스 | |
| 심박 효율 | 속도당 심박 | 낮아지면 유산소 능력 향상 |
| 회복 플래그 | 안정심박 +5%, HRV −15%, 수면 6h 미만, 5일 연속 러닝 | 1개 = 주의, 2개↑ = 휴식 권장 |

## 파일 구조

```
app/main.py       FastAPI 서버 + 07:00 스케줄러
app/ingest.py     아이폰 데이터 파서 (Health Auto Export / 단축어)
app/analysis.py   지표 계산 → 요약 JSON
app/coach.py      Claude 코치 프롬프트 + 규칙 기반 대체
app/notify.py     Telegram / Kakao / ntfy 전송
app/pipeline.py   분석→생성→전송→저장
app/cli.py        사용자 관리, 수동 실행, 데모
app/db.py         SQLite
samples/          Health Auto Export 샘플 JSON
tests/            pytest
```
