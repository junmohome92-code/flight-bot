# Flight Bot — Google Flights 직항 가격 감시

개인 Ubuntu 홈서버에서 Docker로 실행하는 Google Flights 왕복 가격 감시봇입니다.

## 현재 제품 범위

알람은 **Google Flights 검색결과 화면에 실제 표시된 왕복 가격**을 기준으로 합니다.

```text
Google Flights 왕복 검색
→ Cheapest/최저가
→ 강제 전체 새로고침 1회
→ Price unavailable이면 추가 복구 새로고침 최대 2회
→ 직항(Nonstop) 행만 수집
→ 중복 제거
→ 가격순 정렬
→ 최저가 + 추가 직항 후보 표시
→ Google Flights 검색결과 링크 1개 제공
```

하지 않는 것:

```text
Booking options 진입      NO
항공사 결제 페이지 진입   NO
OTA/여행사 링크 제공      NO
외부 checkout 검증        NO
```

## 단일 Google 검색 계약

Windows의 `02-live-cjj-tpe-visible.cmd`, 실제 Telegram 알림, 2시간 스케줄러, Ubuntu/Docker가 모두 같은 검색 계약을 사용합니다.

```text
google_query_contract=accepted-tfs-v1
```

이 계약은 실제 Windows acceptance에서 가격이 정상 표시된 TFS 형식을 코드로 생성합니다. 예전처럼 runtime만 `fast-flights`가 다른 URL을 생성하지 않습니다. 직항 제한도 TFS URL을 변형해서 넣지 않고, 정상 왕복 결과 화면을 연 뒤 **실제 결과 행의 `Nonstop/직항` 표시로 필터링**합니다.

## 검색 / 알림 주기

기본값:

```text
SEARCH_INTERVAL_HOURS=2
SEARCH_CONCURRENCY=2
SEARCH_STAGGER_SECONDS=5
DAILY_SUMMARY_HOUR=8
```

- 가격 검색은 `00, 02, 04, ... 22시`처럼 2시간마다 수행합니다.
- 슬롯은 10개지만 Google 검색은 **동시에 최대 2개**만 실행합니다.
- 검색 시작은 기본 5초씩 분산하여 한 순간에 요청을 몰지 않습니다.
- 각 검색은 독립적인 **새 BrowserContext**를 사용합니다.
- 따라서 다른 슬롯/이전 2시간 검색의 cookie, HTTP cache, localStorage, IndexedDB, service worker 상태를 상속하지 않습니다.
- 오전 08시 검색은 하루 1회 **정기 가격 알림**도 전송합니다.
- 정기 알림 때문에 별도 Google 조회를 추가하지 않습니다.
- `SEARCH_CONCURRENCY`는 코드상 최대 2까지만 허용합니다.

## 목표가 알림

목표가 도달 알림은 **목표가 설정당 최초 1회만** 전송합니다.

```text
ARMED
→ 최저 직항 왕복가 <= target
→ SENDING
→ ALERTED
```

`ALERTED` 이후 가격이 다시 위/아래로 움직여도 자동 재무장하지 않습니다.

다시 목표가 알림을 받고 싶으면:

```text
/flight target <슬롯번호> <새 목표가>
```

를 사용합니다.

정기 알림 시각과 목표가 최초 도달이 겹치면 같은 슬롯에 메시지가 2개 오지 않도록 **목표가 도달 알림만 전송**하고 그날 정기알림은 생략합니다.

## 하루 1회 정기 가격 알림

항상 현재 직항 최저가 창을 보여줍니다.

```text
📊 정기 가격 알림
✈️ CJJ → TPE 왕복
2026-09-18 ~ 2026-09-20
Google Flights 직항 왕복가
1. 308,545KRW · EASTAR JET · 11:40 PM → 1:10 AM
2. 381,095KRW · Aero K Airlines · 10:30 AM → 12:20 PM
목표가: 350,000KRW
위탁수하물: 정보 확인 불가
Google Flights 검색결과: <검색결과 URL>
```

## 슬롯

```text
SLOT_ACTIVE_LIMIT=10
```

실제 슬롯 `1~10` 총 10개를 사용할 수 있습니다.

- pause: 슬롯 유지
- delete: 번호 해제/재사용
- target_price: 필수
- add마다 `generation` UUID 생성
- 설정/상태 변경마다 `revision` 증가
- 검색 저장 시 generation/revision 재검증
- 같은 슬롯의 검색/수정은 직렬화되어 target/pause/delete와 검색 결과 저장이 충돌하지 않음

DB/schema도 1~10 슬롯을 기본 지원하므로 기존 5슬롯 DB를 그대로 사용해도 별도 schema migration 없이 6~10번 슬롯을 추가할 수 있습니다.

## 알람 표시 정책

```text
ALERT_NONSTOP_ONLY=true
ALERT_MAX_OFFERS=4
REQUIRE_VERIFIED_ALERTS=false
```

- 경유편 제외
- 기본 최대 4개 직항 표시
- 실제 직항이 2개면 2개만 표시
- 동일 항공편이 DOM에서 중복 노출돼도 사용자 메시지에서는 한 번만 표시
- 수하물이 확실히 확인되지 않으면 `정보 확인 불가`
- 사용자에게 주는 URL은 Google Flights 검색결과 1개뿐

## Telegram 명령

```text
/flight add CJJ TPE 2026-09-18 2026-09-20 350000
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
/help
```

`/flight check`는 수동 조회만 하며 목표가 알림 latch를 소비하지 않습니다.

## Windows 테스트

최초 1회:

```text
flight-bot - test win\01-setup-and-unit-test.cmd
```

실제 Google Flights 가격 acceptance:

```text
flight-bot - test win\02-live-cjj-tpe-visible.cmd
```

이 acceptance는 더 이상 별도의 하드코딩 TFS URL을 사용하지 않고 production `accepted-tfs-v1` query builder를 그대로 사용합니다.

실제 Telegram 목표가/정기알림 테스트:

```text
flight-bot - test win\03-notification-test-menu.cmd
```

`03` 메뉴는 Windows PowerShell 5.1에서도 UTF-8 JSON을 raw bytes로 읽어 명시적으로 UTF-8 decode합니다. 따라서 API 응답의 한국어가 `ì...` 형태로 깨지는 것을 방지합니다.

## Ubuntu 홈서버 배포 — 추천

서버에서 저장소 루트로 이동한 뒤 `.env`를 준비합니다.

```bash
cp .env.example .env
nano .env
```

최소 설정:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=...
ADMIN_SECRET=긴_랜덤문자열
```

그 다음 한 번에:

```bash
bash deploy/ubuntu-deploy.sh
```

이 스크립트가 다음을 수행합니다.

```text
.env 사전검증
→ docker / compose 확인
→ compose config 검증
→ production image build
→ container up
→ health 대기
→ accepted-tfs-v1 확인
→ 10슬롯 확인
→ 2시간 주기 확인
→ 최대 동시검색 2 확인
→ BrowserContext 격리 확인
→ Cheapest/recovery 정책 확인
→ Telegram 연결 확인
→ admin API 확인
```

그 뒤 Telegram에서 슬롯을 추가하고 실제 Ubuntu IP에서 Google 가격/알림까지 검증합니다.

```text
/flight add CJJ TPE 2026-09-18 2026-09-20 999999
```

Ubuntu에서:

```bash
bash deploy/ubuntu-live-check.sh 1 target
```

정기알림 강제 테스트:

```bash
bash deploy/ubuntu-live-check.sh 1 daily
```

상세: `deploy/README.md`

## 관리자 테스트 API

`ADMIN_SECRET`이 설정된 경우에만 활성화됩니다.

```text
POST /admin/check-all
POST /admin/daily-summary
POST /admin/check-slot/{slot_id}
POST /admin/daily-summary/{slot_id}
```

`/admin/check-slot/1`은 실제 production Google 검색 후 목표가 one-shot 알림을 검사합니다. `/admin/daily-summary/1`은 실제 검색 후 정기알림만 강제로 보내며 목표가 latch는 건드리지 않습니다.

모든 admin endpoint는 `X-Flight-Bot-Secret` 헤더가 필요합니다.

## Docker

일반 실행:

```bash
docker compose up -d --build
```

기본 compose는 HTTP를 host loopback에만 노출합니다.

```text
http://127.0.0.1:8080
```

중지:

```bash
docker compose down
```

SQLite는 named volume `/data`를 사용하므로 일반적인 image rebuild 및 `down/up`으로 데이터가 사라지지 않습니다.

Health 핵심 필드:

```text
provider=google-playwright-results-observed-accepted-flow
google_query_contract=accepted-tfs-v1
search_interval_hours=2
search_concurrency=2
search_stagger_seconds=5
browser_search_storage_isolated=true
browser_block_assets=false
cheapest_selected_full_reload=true
price_unavailable_recovery_reloads=2
slots_max=10
slots_design_capacity=10
```

Docker image는 non-root `app` 사용자로 실행됩니다.

## CI

GitHub Actions:

```text
unit-linux
unit-windows
browser-contract
docker-smoke
```

CI는 exact accepted TFS token, 최대 동시검색 2, 독립 BrowserContext, Windows PowerShell 5.1/7 parser, production Docker Compose 설정, runtime health/admin surface를 검증합니다.
