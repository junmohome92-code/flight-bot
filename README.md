# Flight Bot — Google Flights 직항 가격 감시

개인 Ubuntu 홈서버에서 Docker로 실행하는 Google Flights 왕복 가격 감시봇입니다.

## 현재 제품 범위

알람은 **Google Flights 검색결과 화면에 실제 표시된 왕복 가격**을 기준으로 합니다.

```text
Google Flights 왕복 검색
→ Cheapest/최저가
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

## 검색 / 알림 주기

기본값:

```text
SEARCH_INTERVAL_HOURS=2
DAILY_SUMMARY_HOUR=8
```

- 가격 검색은 `00, 02, 04, ... 22시`처럼 2시간마다 수행합니다.
- 오전 08시 검색은 하루 1회 **정기 가격 알림**도 전송합니다.
- 정기 알림 때문에 별도 Google 조회를 추가하지 않습니다.
- 각 검색은 **새 BrowserContext**를 사용하여 이전 검색의 cookie/cache/localStorage/IndexedDB 등을 다음 검색에 넘기지 않습니다.

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

기본값:

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

실제 Telegram 목표가/정기알림 테스트:

```text
flight-bot - test win\03-notification-test-menu.cmd
```

`03` 메뉴는 실행 중인 봇이 없으면 **Windows 로컬 실행 또는 Docker Compose 실행**을 선택할 수 있고, 다음을 즉시 테스트할 수 있습니다.

```text
슬롯 1개 목표가 알림
슬롯 1개 정기알림
전체 슬롯 일반 검색
전체 슬롯 강제 정기알림
```

정기알림 강제 테스트는 목표가 one-shot 상태를 소비하거나 재무장하지 않습니다.

## 관리자 테스트 API

`ADMIN_SECRET`이 설정된 경우에만 활성화됩니다.

```text
POST /admin/check-all
POST /admin/daily-summary
POST /admin/check-slot/{slot_id}
POST /admin/daily-summary/{slot_id}
```

의미:

```text
/admin/check-slot/1
→ 슬롯 1 실제 Google 검색
→ 목표가 조건을 만족하고 ARMED면 목표가 알림 1회

/admin/daily-summary/1
→ 슬롯 1 실제 Google 검색
→ 정기알림 즉시 전송
→ 목표가 latch는 건드리지 않음
```

모든 admin endpoint는 `X-Flight-Bot-Secret` 헤더가 필요합니다.

## Docker

`.env` 준비:

```bash
cp .env.example .env
```

최소 Telegram 알림 테스트 설정:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=...
ADMIN_SECRET=긴_랜덤문자열
```

실행:

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

Health:

```text
GET /health
```

핵심 필드:

```text
search_interval_hours=2
daily_summary_hour=8
browser_search_storage_isolated=true
slots_max=10
slots_design_capacity=10
```

Docker image는 non-root `app` 사용자로 실행되고 `/data` SQLite volume을 사용합니다.

## CI

GitHub Actions:

```text
unit-linux
unit-windows
browser-contract
docker-smoke
```

Docker smoke는 10슬롯 health 값과 admin 수동 테스트 route가 실제 production image에서 동작하는지까지 확인합니다.
