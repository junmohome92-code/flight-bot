# Flight Bot — Naver Flights SSE

네이버 항공권 SSE 검색 응답으로 **직항 왕복 TOP 5 가격을 감시/조회**하는 self-hosted 봇입니다. 브라우저 자동화나 DOM/CSS 파싱은 사용하지 않습니다.

## 핵심 기능

- Naver Flights SSE API 단일 가격 소스
- 성인 1명 / 이코노미 / 직항 / 왕복
- 가격순 TOP 5 왕복 조합
- 가는편/오는편 항공사·편명·시간 표시
- **감시 슬롯 최대 20개**
- **슬롯 등록 없이 바로 검색 가능** — 슬롯을 소비하거나 DB에 감시항목을 만들지 않음
- **각 슬롯에서 `지금 검색` 버튼으로 즉시 재조회**
- Telegram 버튼 UI로 등록/검색/목표가 변경/정지/삭제
- 기본 2시간 주기 감시 + 목표가 알림 + 일일 요약
- SQLite 상태 저장
- Docker/Compose 배포

## Telegram 사용

`/start`를 보내면 하단에 메뉴가 고정됩니다.

```text
➕ 감시 등록     🔎 바로 검색
📋 내 슬롯       ❓ 도움말
```

`➕ 감시 등록`은 출발지 → 도착지 → 출발일 → 귀국일 → 목표가 순서로 안내하고 마지막에 확인 버튼으로 저장합니다. 주요 공항과 대표 목표가는 버튼으로 바로 선택할 수 있고, 다른 값은 직접 입력할 수 있습니다.

`📋 내 슬롯`에서 슬롯을 누르면 다음 관리 버튼이 나옵니다.

```text
🔎 지금 검색
🎯 목표가 변경   ⏸ 일시정지 / ▶️ 다시 시작
🗑 삭제           ⬅️ 목록
```

도움말은 `/help` 또는 `/?`로 바로 볼 수 있습니다.

명령어 방식도 유지합니다.

```text
/flight search CJJ TPE 2026-09-18 2026-09-20
/flight add CJJ TPE 2026-09-18 2026-09-20 350000
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
```

## 가격 수집 구조

```text
flight-api.naver.com/flight/international/searchFlights
        ↓ POST JSON / Accept: text/event-stream
SSE 이벤트 수집
        ↓
itineraries + fareMappings 결합
        ↓
가는편/오는편 + 항공사 + 편명 + 시간 + 왕복 총액
        ↓
동일 왕복 조합 중복 제거
        ↓
가격 오름차순 TOP 5
```

2026-09-07 Windows 실조회에서 `CJJ → TPE → CJJ`, `2026-09-18 ~ 2026-09-20` 조건으로 HTTP `201`, `text/event-stream`, SSE 20개 이벤트를 수신했고 최저 왕복가 **319,620원**을 확인했습니다. 같은 시점 네이버 항공권 화면 표시 가격과 일치했습니다.

## 가장 쉬운 Docker 설치

```bash
git clone https://github.com/junmohome92-code/flight-bot.git
cd flight-bot
cp .env.example .env
nano .env
```

`.env`에서 최소한 아래 두 값을 넣습니다.

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=...
```

그 다음:

```bash
bash install.sh
```

`install.sh`가 Docker/Compose 확인 → compose 검증 → 이미지 build → 컨테이너 실행까지 수행합니다.

직접 실행하려면:

```bash
docker compose up -d --build
```

상태 확인:

```bash
docker compose ps
docker compose logs -f flight-bot
curl http://127.0.0.1:8080/health
```

SQLite 데이터는 Compose named volume `flight_bot_data`에 저장되어 이미지 rebuild 후에도 유지됩니다.

## 주요 설정

```text
SLOT_ACTIVE_LIMIT=20
SEARCH_INTERVAL_HOURS=2
DAILY_SUMMARY_HOUR=8
ALERT_MAX_OFFERS=5
NAVER_API_TIMEOUT_SECONDS=30
NAVER_API_ATTEMPTS=3
NAVER_MIN_REQUEST_INTERVAL_SECONDS=3
```

20개 슬롯을 순차 조회해도 Provider 내부 request lock과 최소 요청 간격으로 과도한 동시 요청을 만들지 않습니다. 바로 검색 역시 같은 요청 제어를 통과합니다.

## HTTP 관리 엔드포인트

`ADMIN_SECRET`을 설정했을 때만 활성화됩니다. `X-Flight-Bot-Secret` 헤더가 필요합니다.

```text
GET  /health
POST /admin/search
POST /admin/check-all
POST /admin/check-slot/{slot_id}
POST /admin/daily-summary
POST /admin/daily-summary/{slot_id}
POST /kakao/skill
```

`/admin/search`도 슬롯을 생성하지 않는 1회 검색입니다.

## Windows 실조회 테스트

`flight-bot - test win` 폴더에서:

```text
01-setup-and-unit-test.cmd
02-NAVER-flight-test.bat
03-NAVER-TELEGRAM-E2E.bat
```

## 개발/CI 검증

```bash
python -m pip install -c constraints.txt -e '.[dev]'
pytest -q
python -m compileall -q src scripts tests
docker build -t flight-bot:test .
```

CI는 전체 단위/통합 테스트, FastAPI 엔드포인트 테스트, 브라우저 자동화 의존성 부재 검사, Docker build, 실제 컨테이너 `/health` 확인을 수행합니다.

## 운영 경계

예약/결제 페이지 이동이나 외부 판매처 checkout 최종가격 검증은 현재 범위 밖입니다. Naver 내부 API 구조가 변경되면 SSE 요청/응답 계약을 다시 검증해야 하며 DOM fallback은 두지 않습니다.
