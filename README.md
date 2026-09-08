# Flight Bot — Naver Flights SSE

네이버 항공권 SSE 검색 응답으로 **직항 왕복 TOP 5 가격을 감시/조회**하는 self-hosted 봇입니다. 브라우저 자동화나 DOM/CSS 파싱은 사용하지 않습니다.

## 핵심 기능

- Naver Flights SSE API 단일 **가격 소스**
- 성인 1명 / 이코노미 / 직항 / 왕복 / KRW
- 가격순 TOP 5 왕복 조합
- 가는편/오는편 항공사·편명·시간·실제 출도착 공항 표시
- **Telegram 채팅방마다 감시 슬롯 최대 20개**
- 한 Bot Token/서버 1개로 여러 개인·그룹채팅 동시 운영
- 슬롯 등록 없이 바로 검색
- 슬롯별 `지금 검색`
- 실제 IATA 검증 + 오타 추천
- **전세계 한글·영어·IATA 공항/도시 검색**
- 다공항 도시는 `도시 전체`와 개별 공항을 구분
- Telegram 버튼 UI
- 기본 2시간 주기 가격 감시
- 목표가 도달 알림은 목표가 설정당 최초 1회
- **하루 1회 채팅방별 통합 정기보고**
- SQLite 상태 저장 + host bind mount
- Docker/Compose 배포

## Telegram 사용

`/start`를 보내면 아래 메뉴가 고정됩니다.

```text
➕ 감시 등록     🔎 바로 검색
📋 내 슬롯       ❓ 도움말
```

### 도움말

사용자 화면에서는 복잡한 `/flight ...` 명령어를 안내하지 않습니다. 버튼 UI 기준으로 필요한 기능만 짧게 표시합니다.

```text
✈️ 항공권 감시봇

➕ 감시 등록 — 노선·날짜·목표가 등록
🔎 바로 검색 — 슬롯 없이 TOP 5 조회
📋 내 슬롯 — 검색·목표가·정지·삭제

🌍 한글 / 영어 / IATA 공항·도시 검색
👥 채팅방마다 감시 슬롯 최대 20개
🔔 기본 2시간마다 가격 확인
🔥 목표가 도달 알림은 목표가 설정당 1회
📊 하루 1회 정기보고
```

기존 `/flight ...` 명령은 하위 호환용으로 내부에 남아 있지만 Telegram 명령 메뉴/도움말에는 노출하지 않습니다.

## 전세계 공항·도시 입력

출발지/도착지 단계에서 특정 네 개 노선만 보여주는 고정 빠른선택 버튼은 사용하지 않습니다. 직접 입력이 기본입니다.

```text
🌍 출발 도시 또는 공항을 입력해 주세요.
한글 · 영어 · IATA 모두 가능합니다.
예: 히로시마 / Hiroshima / HIJ
```

입력 방식 예:

```text
히로시마  → HIJ 후보
Hiroshima → HIJ 후보
HIJ       → HIJ

도쿄      → 도쿄 전체 TYO / 나리타 NRT / 하네다 HND
New York  → 뉴욕 전체 NYC / JFK / LGA / EWR 등
```

정확한 공항 코드는 `airportsdata`로 검증합니다. 이름 검색은 오프라인 multilingual airport index를 사용하며, 현재 사용 버전은 재현성을 위해 upstream commit SHA에 고정되어 있습니다. 오타/모호한 입력은 자동 저장하지 않고 버튼 후보를 보여준 뒤 사용자가 선택해야 저장됩니다.

도시 전체를 선택하면 Naver 요청에도 `locationType=city`, 개별 공항을 선택하면 `locationType=airport`가 전달됩니다. 이 타입은 슬롯 DB에도 명시적으로 저장됩니다.

## 그룹채팅 운영

봇 서버는 여러 개 띄울 필요가 없습니다. **Bot Token 1개 + 서버 프로세스 1개**로 여러 Telegram 채팅방을 처리합니다.

`.env`에 허용할 Chat ID를 쉼표로 넣습니다.

```text
TELEGRAM_ALLOWED_CHAT_IDS=-1001111111111,-1002222222222
```

각 채팅방은 서로 독립적인 슬롯 번호 `#1 ~ #20`을 가집니다.

```text
그룹 A: #1 ... #20
그룹 B: #1 ... #20
개인채팅: #1 ... #20
```

DB 내부 Primary Key는 전역 ID를 유지하지만 사용자에게 보이는 `slot_no`는 `(platform, chat_id)`별로 분리됩니다. 한 그룹의 슬롯/정기보고/목표가 알림은 다른 그룹에 섞이지 않습니다.

등록 중 입력 흐름도 채팅방별로 분리되어 같은 사용자가 서로 다른 그룹에서 동시에 등록을 진행해도 상태가 덮이지 않습니다. 자유 텍스트 입력 단계는 Telegram 그룹 Privacy Mode에서도 안정적으로 동작하도록 `ForceReply`를 사용합니다. 일반 그룹 대화에는 봇이 자동으로 도움말을 답하지 않습니다.

## 감시 등록 후 알림 흐름

의도한 lifecycle은 다음과 같습니다.

```text
감시 등록
  ↓
현재 TOP 5 즉시 1회 조회
(이 조회에서는 목표가 알림을 소비하지 않음)
  ↓
2시간 정기 스캔 계속
  ↓
목표가 최초 충족 시 🔥 알림 1회
  ↓
같은 목표가로는 중복 목표가 알림 없음
  ↓
하루 1회 정기보고는 계속
```

목표가를 변경하면 목표가 알림 latch가 다시 `ARMED`되어 새 목표가 기준으로 1회 알림을 받을 수 있습니다.

## 슬롯 관리

`📋 내 슬롯`에서 슬롯을 누르면:

```text
🔎 지금 검색
🎯 목표가 변경   ⏸ 일시정지 / ▶️ 다시 시작
🗑 삭제           ⬅️ 목록
```

일시정지 슬롯은 슬롯 번호를 계속 점유하지만 정기 검색/보고에서는 제외됩니다.

## 정기보고

기본값은 `DAILY_SUMMARY_HOUR=8`, `TIMEZONE=Asia/Seoul`이므로 오전 8시 정기보고입니다. `SEARCH_INTERVAL_HOURS=2`이면 00/02/04/.../22시에 가격을 확인하되 정기보고 메시지는 설정된 시간에만 보냅니다.

각 채팅방은 슬롯 수와 관계없이 **정기보고 한 메시지**로 합칩니다.

```text
📊 09/08 항공권 정기 보고
활성 슬롯 4개 · 최저 왕복가 기준

#1 CJJ→TPE  319,620원  ▼12,000
#2 ICN→NRT  281,000원  ─
#3 SEL→TYO  294,300원  ▲4,500
#4 PUS→FUK  198,000원  🎯
```

`▼/▲/─`는 직전 관측 대비 변화이고 `🎯`는 현재 가격이 목표가 이하라는 뜻입니다. `#N 상세` 버튼을 누르면 해당 슬롯의 최신 TOP 5를 즉시 다시 검색합니다.

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

2026-09-07 검증된 실조회:

```text
CJJ → TPE → CJJ
2026-09-18 ~ 2026-09-20
최저 319,620 KRW
PASS

SEL:city → TYO:city → SEL:city
2026-09-22 ~ 2026-09-24
20 direct candidates
최저 450,400 KRW
Naver advertised lowest와 일치
PASS
```

## Docker 설치 / 업데이트

```bash
git clone https://github.com/junmohome92-code/flight-bot.git
cd flight-bot
cp .env.example .env
nano .env
bash install.sh
```

직접 재배포:

```bash
docker compose up -d --build
```

상태 확인:

```bash
docker compose ps
docker compose logs -f flight-bot
curl http://127.0.0.1:8080/health
```

실제 포트는 `.env`의 `HTTP_PORT`를 따릅니다. 현재 홈서버 운영값은 `8081`입니다.

## SQLite DB 보존 — 중요

Compose는 Docker named volume이 아니라 **호스트 bind mount**를 사용합니다.

```yaml
volumes:
  - ./data:/data
```

컨테이너 DB:

```text
/data/flight_bot.db
```

홈서버 repo `/data/flight-bot` 기준 실제 DB:

```text
/data/flight-bot/data/flight_bot.db
```

`docker compose up -d --build`, image rebuild, container recreate를 해도 이 호스트 DB를 유지합니다. **`data/` 또는 `data/flight_bot.db`를 삭제/초기화하지 마십시오.**

v0.6 DB 변경은 기존 DB를 재생성하지 않고 additive migration으로 `slot_no`, `origin_type`, `destination_type`을 추가/backfill합니다. 기존 offer/search/alert history와 내부 slot PK는 유지합니다.

## 주요 설정

```text
SLOT_ACTIVE_LIMIT=20        # 채팅방마다 적용
SEARCH_INTERVAL_HOURS=2
DAILY_SUMMARY_HOUR=8
ALERT_MAX_OFFERS=5
NAVER_API_TIMEOUT_SECONDS=30
NAVER_API_ATTEMPTS=3
NAVER_MIN_REQUEST_INTERVAL_SECONDS=3
```

Provider 내부 request lock과 최소 요청 간격으로 여러 그룹/슬롯 검색도 한꺼번에 폭주하지 않도록 직렬화합니다.

## HTTP 관리 엔드포인트

`ADMIN_SECRET`을 설정했을 때만 활성화됩니다.

```text
GET  /health
POST /admin/search
POST /admin/check-all
POST /admin/check-slot/{slot_id}
POST /admin/daily-summary
POST /admin/daily-summary/{slot_id}
POST /kakao/skill
```

`/health`의 v0.6 핵심 플래그:

```text
version=0.6.0
slot_limit_scope=per-conversation
city_search_enabled=true
worldwide_location_search_enabled=true
multilingual_location_search_enabled=true
iata_validation_enabled=true
daily_summary_mode=one-message-per-conversation
```

## 개발/CI 검증

```bash
python -m pip install -c constraints.txt -e '.[dev]'
pytest -q
python -m compileall -q src scripts tests
docker build -t flight-bot:test .
```

CI는 Linux 전체 테스트, Windows Naver SSE harness, DB additive migration/그룹별 20슬롯, multilingual 위치 검색, Telegram UI, Docker build, 실제 Compose `/health`, bind-mounted SQLite 보존을 검증합니다.

## 운영 경계

예약/결제 페이지 이동과 외부 판매처 checkout 최종가격 검증은 범위 밖입니다. Naver Flights SSE는 비공개 내부 인터페이스이므로 upstream 요청/응답 구조가 변경되면 live probe로 재검증해야 합니다. DOM/Playwright fallback은 두지 않습니다.
