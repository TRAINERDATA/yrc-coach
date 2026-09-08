# 돈 안 쓰고 운영하기 (0원 구성)

| 구성요소 | 유료 안 | 무료 안 | 트레이드오프 |
|---|---|---|---|
| 코치 글쓰기 | Claude API (크레딧) | **규칙 기반 브리핑** (`COACH_PROVIDER=rules`) 또는 **Claude 구독 routine** | 규칙 기반은 문장이 정형화됨. 수치·처방 로직은 동일 |
| 서버 | Railway 등 | **Render 무료 웹서비스** 또는 **내 PC** | Render 무료는 15분 쉬면 잠들고, 재시작 때 DB가 지워짐 → 폰이 매일 8주치를 다시 보내면 해결 |
| 스케줄 | 서버 내부 07:00 | **cron-job.org** (무료) 로 07:00 에 `/brief/<token>/run` 호출 | 잠든 서버를 깨우는 역할도 함 |
| 폰 → 서버 | Health Auto Export (유료) | **단축어 자동화** (iOS 기본, 무료) | 단축어를 한 번 직접 만들어야 함 (아래 레시피) |
| 알림 | | **텔레그램 봇** (무료) | |

## A. Render 에 올리기 (10분)

1. GitHub 계정 만들고 이 폴더를 저장소로 올립니다 (GitHub Desktop 앱이 제일 쉬움).
2. [render.com](https://render.com) 가입 → New → **Blueprint** → 저장소 선택. `render.yaml` 이 읽혀 무료 웹서비스가 만들어집니다.
3. Environment 에서 `TELEGRAM_BOT_TOKEN`, `PUBLIC_BASE_URL`(=`https://yrc-coach.onrender.com` 처럼 Render 가 준 주소) 입력 → Deploy.
4. `https://<주소>/health` 가 열리면 성공.
5. 사용자 등록은 내 PC 에서 한 번:
   ```
   python -m app.cli telegram-setup --name 김창희 --age 30 --goal "목표"
   python -m app.cli export-seed
   ```
   (폰에서 봇에 /start 를 누르면 등록됩니다. `export-seed` 출력을 Render 의 `SEED_USERS` 에 넣고 재배포하면 서버에도 같은 사용자가 생깁니다. `ingest` URL 은 `https://<주소>/ingest/<token>` 입니다.)

> 무료 플랜은 재시작 시 DB 가 초기화되고 Shell 도 없습니다. 그래서 사용자 목록은 환경변수 `SEED_USERS` 에 넣어 두면 서버가 켜질 때마다 자동 복구합니다.
> 내 PC 에서 `python -m app.cli telegram-setup` 으로 등록한 뒤 `python -m app.cli export-seed` 가 출력한 JSON 한 줄을 Render Environment 의 `SEED_USERS` 값으로 붙여넣으세요. 크루원을 추가할 때도 같은 방법입니다.

## B. 07:00 브리핑 트리거 (cron-job.org, 5분)

1. [cron-job.org](https://cron-job.org) 가입 → Create cronjob
2. URL: `https://<주소>/brief/<token>/run`  Method: **POST**  Schedule: 매일 07:00 (시간대 Asia/Seoul)
3. 하나 더: URL `https://<주소>/health`, GET, 매일 06:50 → 잠든 서버를 미리 깨우는 용도

## C-0. 러닝 데이터는 Strava 로 (Apple Watch 운동 앱만 쓰는 경우 이 방법이 정답)

iOS 단축어의 "건강 샘플 찾기" 는 애플 기본 기능으로 **운동(Workout) 기록을 꺼낼 수 없습니다.** 걷기+달리기 거리 같은 합계만 나옵니다. 그래서 무료로 정확한 러닝 기록을 받는 가장 좋은 방법은 Strava 입니다.

1. 아이폰에 Strava 설치 → 무료 계정 → 워치에도 Strava 설치. 러닝할 때 워치에서 **Strava 앱으로** 시작합니다 (건강 앱에도 동일하게 저장됨).
2. PC 에서 [strava.com/settings/api](https://www.strava.com/settings/api) → 앱 만들기. Authorization Callback Domain 에 `yrc-coach.onrender.com` (https:// 없이). Client ID / Client Secret 을 Render Environment 의 `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` 에 넣고 저장.
3. 폰에서 `https://yrc-coach.onrender.com/strava/connect/<token>` 을 열고 동의. 최근 56일 러닝이 바로 들어오고, 이후 매일 아침 브리핑 직전에 자동으로 가져옵니다.
4. Render 무료 플랜이면 연결 완료 화면에 나오는 `strava_refresh_token` 값을 `SEED_USERS` JSON 안에 추가하세요 (재시작 후에도 연결 유지). `DATABASE_URL`(아래 E) 을 쓰면 이 단계는 필요 없습니다.

크루원 추가: `telegram-setup` 으로 등록 → 그 사람에게 `/strava/connect/<그 사람 token>` 링크를 보내면 끝.

### 과거 기록 한 번에 넣기 (Strava 쓰기 전 기록)
아이폰 건강 앱 → 프로필 → **모든 건강 데이터 내보내기** → zip 을 PC 로 옮긴 뒤:
```
python -m app.cli import-health 1 내보내기.zip --days 90
```
로컬 DB 에 들어갑니다. Render 서버 DB 에 넣으려면 `DATABASE_URL` 을 같은 값으로 설정한 뒤 실행하세요 (아래 E).

## E. 데이터 영구 보관 (선택, 무료): Supabase Postgres
Render 무료 플랜은 재시작 때 SQLite 가 지워집니다. [supabase.com](https://supabase.com) 무료 프로젝트를 만들고 Settings → Database → Connection string (URI, **Session pooler** 권장) 을 Render 의 `DATABASE_URL` 에 넣으면 사용자·러닝·브리핑이 모두 유지됩니다. 코드 변경 없음.

## C. 단축어 만들기 (Strava 를 안 쓰는 경우의 대안. 러닝 워크아웃은 못 가져옴)

단축어 앱 → `+` → 이름 "YRC 데이터 전송". 아래 동작을 순서대로 추가합니다.

1. **건강 샘플 찾기**
   - 유형: `운동`  /  필터: `시작 날짜` `이후` `56일 전` (날짜 계산: "날짜 조정" 동작으로 오늘 −56일을 먼저 만든 뒤 변수로 사용)
   - 정렬: 시작 날짜, 제한 없음
2. **각 항목에 대해 반복** (건강 샘플)
   - 안에 **사전** 동작: 키/값
     - `type` → 텍스트 `운동 유형` (반복 항목의 세부사항에서 "운동 유형" 선택)
     - `start` → `시작 날짜` (형식: ISO 8601)
     - `end` → `종료 날짜` (ISO 8601)
     - `distance_km` → `거리` (단위 km, 숫자)
     - `duration_s` → `기간` (초)
     - `avg_hr` → `평균 심박수` (있으면)
   - 반복 결과를 변수 `workouts` 로 저장 (반복 결과 = 사전 목록)
3. **건강 샘플 찾기**: 유형 `안정 시 심박수`, 정렬 최신순, 제한 1 → 변수 `rhr`
4. **건강 샘플 찾기**: 유형 `심박 변이도`, 최신 1개 → 변수 `hrv`
5. **건강 샘플 찾기**: 유형 `수면`, 어제 이후, 값 합계(시간) → 변수 `sleep` (수면은 합계가 까다로우면 생략해도 됨)
6. **사전** `metrics`: `date`=현재 날짜(yyyy-MM-dd), `resting_hr`=rhr, `hrv`=hrv, `sleep_h`=sleep
7. **사전** `body`: `workouts`=workouts 변수, `metrics`=metrics 사전
8. **URL 콘텐츠 가져오기**: URL = 텔레그램으로 받은 `ingest` 주소, 방식 POST, 요청 본문 **JSON** = body
9. (선택) **알림 보이기**: "전송 완료"

자동화: 단축어 앱 → 자동화 → `+` → 시간대 매일 **06:40** → "YRC 데이터 전송" → **즉시 실행** (확인 요청 끄기).

먼저 단축어를 손으로 한 번 실행해서 서버 로그(Render Logs)에 `ingest 김창희: N workouts` 가 찍히는지 확인하세요.

> 운동 유형 이름에 "Running/달리기/러닝" 이 들어간 것만 러닝으로 집계합니다. 서버는 어떤 키가 빠져도 받아주고, 같은 시작시각 기록은 덮어쓰기 하므로 매일 56일치를 통째로 보내도 됩니다. Render 재시작으로 DB 가 비어도 다음 날 아침 복구됩니다.

## D. 코치 글을 Claude 로 쓰되 크레딧 안 쓰기 (선택)

이미 쓰고 있는 Claude 구독(claude.ai / Claude Code)의 **예약 작업(routine)** 으로 매일 07:00 에 다음을 시키면 API 크레딧 없이 됩니다.

1. `GET https://<주소>/brief/<token>/json` 을 읽는다 (분석 JSON)
2. `app/coach.py` 의 SYSTEM_PROMPT 형식으로 브리핑을 쓴다
3. `POST https://<주소>/brief/<token>/publish` 에 `{"text": "..."}` 로 보낸다 → 서버가 텔레그램으로 전송

이 경우 cron-job.org 의 `/run` 호출은 만들지 않습니다(routine 이 대신함). 서버 쪽 `COACH_PROVIDER=rules` 는 그대로 두어도 됩니다.
