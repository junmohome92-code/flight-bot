# Flight Bot — Naver Flights SSE

네이버 항공권 SSE 검색 응답으로 **직항 왕복 TOP 5 가격을 감시/조회**하는 self-hosted 봇입니다. 브라우저 자동화나 DOM/CSS 파싱은 사용하지 않습니다.

## 핵심 기능

- Naver Flights SSE API 단일 가격 소스
- 성인 1명 / 이코노미 / 직항 / 왕복
- 가격순 TOP 5 왕복 조합
- 가는편/오는편 항공사·편명·시간·실제 출도착 공항 표시
- **감시 슬롯 최대 20개**
- **슬롯 등록 없이 바로 검색 가능** — 슬롯/DB 감시항목을 소비하지 않음
- **각 슬롯에서 `지금 검색` 버튼으로 즉시 재조회**
- **실제 IATA 공항 목록 검증 + 오타 추천**
- **도시 전체 검색 지원** — 예: `SEL:city ↔ TYO:city`
- Telegram 버튼 UI로 등록/검색/목표가 변경/정지/삭제
- 기본 2시간 주기 감시 + 목표가 알림
- **아침 정기 보고는 사용자당 메시지 1개로 통합**
- SQLite 상태 저장
- Docker/Compose 배포

## Telegram 사용

`/start`를 보내면 하단 메뉴가 고정됩니다.

```text
➕ 감시 등록     🔎 바로 검색
📋 내 슬롯       ❓ 도움말
```

### 공항/도시 입력

등록/바로검색에서 공항 코드만 외울 필요가 없습니다.

```text
청주
→ 청주 CJJ

도쿄
→ 도쿄 전체 TYO
→ 나리타 NRT
→ 하네다 HND

서울
→ 서울 전체 SEL
→ 인천 ICN
→ 김포 GMP
```

`CJX`처럼 존재하지 않는 코드를 입력하면 슬롯에 저장하지 않고 비슷한 실제 공항/도시를 버튼으로 추천합니다. 전체 IATA 공항 검증 데이터는 `airportsdata` 패키지에 포함된 로컬 카탈로그를 사용하므로 입력 검증 때 외부 API를 추가 호출하지 않습니다.

현재 도시 전체 검색으로 준비된 대표 코드:

```text
SEL 서울
TYO 도쿄
OSA 오사카
SPK 삿포로
NYC 뉴욕
LON 런던
PAR 파리
ROM 로마
MIL 밀라노
WAS 워싱턴
BJS 베이징
```

도시 전체를 선택하면 네이버 요청에도 `city` 타입을 사용합니다. 예:

```text
SEL:city → TYO:city
```

개별 공항을 선택하면 기존처럼 `airport` 타입을 사용합니다.

### 슬롯 관리

`📋 내 슬롯`에서 슬롯을 누르면:

```text
🔎 지금 검색
🎯 목표가 변경   ⏸ 일시정지 / ▶️ 다시 시작
🗑 삭제           ⬅️ 목록
```

도움말은 `/help` 또는 `/?`로 바로 볼 수 있습니다.

명령어 방식도 유지합니다.

```text
/flight search CJJ TPE 2026-09-18 2026-09-20
/flight search SEL TYO 2026-09-22 2026-09-24
/flight add CJJ TPE 2026-09-18 2026-09-20 350000
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
```

## 아침 정기 보고

슬롯이 10개 또는 20개여도 슬롯마다 Telegram 메시지를 따로 보내지 않습니다. **사용자당 정기 보고 1개**로 합칩니다.

예:

```text
📊 09/07 항공권 정기 보고
활성 슬롯 4개 · 최저 왕복가 기준

#1 CJJ→TPE  319,620원  ▼12,000
#2 ICN→NRT  281,000원  ─
#3 SEL→TYO  294,300원  ▲4,500
#4 PUS→FUK  198,000원  🎯

아래 상세 버튼을 누르면 해당 슬롯을 즉시 다시 검색합니다.
```

Telegram에서는 보고서 아래에:

```text
[ #1 상세 ] [ #2 상세 ]
[ #3 상세 ] [ #4 상세 ]
```

처럼 버튼이 붙습니다. `상세`를 누르면 해당 슬롯을 즉시 다시 검색해 최신 TOP 5를 보여줍니다. `▼/▲`는 직전 관측 가격 대비 변화이며, `🎯`는 현재 최저가가 목표가 이하라는 뜻입니다. 목표가 최초 도달 알림은 정기 보고와 별도의 중요 알림으로 계속 동작합니다.

일시정지 슬롯은 정기 검색/보고에서 제외됩니다.

## 가격 수집 구조

```text
flight-api.naver.com/flight/international/searchFlights
        ↓ POST JSON / Accept: text/event-stream
SSE 이벤트 수집
        ↓
itineraries + fareMappings 결합
        ↓
가는편/오는편 + 항공사 + 편명 + 시간 + 실제 공항 + 왕복 총액
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

`install.sh`가 Docker/Compose 확인 → `.env`/`data/` 준비 → compose 검증 → 이미지 build → 컨테이너 실행까지 수행합니다. 기존 `data/flight_bot.db`는 삭제·초기화하지 않습니다. IATA 카탈로그도 Docker 이미지 안에 함께 설치되므로 별도 파일 다운로드가 필요 없습니다.

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

### SQLite DB 보존 방식

Compose는 Docker named volume이 아니라 **호스트 bind mount**를 사용합니다.

```yaml
volumes:
  - ./data:/data
```

컨테이너 안의 DB 경로는 `/data/flight_bot.db`, 호스트에서는 `<repo>/data/flight_bot.db`입니다. 홈서버 repo가 `/data/flight-bot`이라면 실제 DB는:

```text
/data/flight-bot/data/flight_bot.db
```

`docker compose up -d --build`, 컨테이너 recreate, 이미지 rebuild를 해도 이 호스트 파일은 그대로 유지됩니다. **운영 중 `data/` 또는 `data/flight_bot.db`를 삭제하지 마십시오.**

이전 named-volume 배포에서 업그레이드하는 경우 기존 named volume 자체는 자동 삭제되지 않지만, bind mount로 전환하기 전에 DB를 `./data/flight_bot.db`로 옮겨야 기존 데이터가 이어집니다. 현재 홈서버는 이미 bind mount 경로로 전환되어 있습니다.

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

`/admin/search`도 슬롯을 생성하지 않는 1회 검색이며 `SEL`, `TYO` 같은 지원 도시 코드도 사용할 수 있습니다.

`/health`의 v0.5 핵심 플래그:

```text
version=0.5.0
city_search_enabled=true
iata_validation_enabled=true
daily_summary_mode=one-message-per-user
```

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

CI는 전체 단위/통합 테스트, 실제 IATA/도시 검색 계약, FastAPI 엔드포인트, Telegram 요약 버튼, 브라우저 자동화 의존성 부재, Docker build, **실제 Compose 기동 + `/health` + bind-mounted SQLite 파일 보존**을 검증합니다.

## 운영 경계

예약/결제 페이지 이동이나 외부 판매처 checkout 최종가격 검증은 현재 범위 밖입니다. Naver 내부 API 구조가 변경되면 SSE 요청/응답 계약을 다시 검증해야 하며 DOM fallback은 두지 않습니다.
