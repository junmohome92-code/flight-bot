# Flight Bot — Google Flights 직항 가격 감시

개인 Ubuntu 홈서버에서 Docker로 실행하는 Google Flights 왕복 가격 감시봇입니다.

## 현재 제품 범위

현재 알람은 **Google Flights 검색결과 화면에 실제 표시된 왕복 가격**을 기준으로 합니다.

```text
Google Flights 왕복 검색
→ Cheapest/최저가
→ 직항(Nonstop) 행만 수집
→ 가격순 정렬
→ 최저가 + 추가 직항 후보를 설정 개수만큼 표시
→ Google Flights 검색결과 링크 1개 제공
```

하지 않는 것:

```text
Booking options 진입      NO
항공사 결제 페이지 진입   NO
OTA/여행사 링크 제공      NO
외부 checkout 검증        NO
```

알람에서 사용자에게 제공하는 URL은 **Google Flights 검색결과 링크 하나뿐**입니다.

## 알람 정책

기본값:

```text
ALERT_NONSTOP_ONLY=true
ALERT_MAX_OFFERS=4
REQUIRE_VERIFIED_ALERTS=false
```

- 경유편은 알람 후보에서 제외합니다.
- `ALERT_MAX_OFFERS=4`는 최대 표시 개수입니다. 직항이 2개뿐이면 2개만 표시합니다.
- 개수는 설정값이므로 코드 로직에 4개로 고정하지 않습니다.
- 목표가 비교는 Google Flights에 표시된 최저 직항 왕복가를 사용합니다.
- 수하물 정보가 화면에서 신뢰성 있게 확인되지 않으면 `정보 확인 불가`로 표시합니다.

예시:

```text
🔥 목표가 도달
✈️ CJJ → TPE 왕복
2026-09-18 ~ 2026-09-20
Google Flights 직항 왕복가
1. 308,545KRW · EASTAR JET · 11:40 PM → 1:10 AM
2. 381,095KRW · Aero K Airlines · 10:30 AM → 12:20 PM
목표가: 350,000KRW
위탁수하물: 정보 확인 불가
Google Flights 검색결과: <검색결과 URL>
```

## 슬롯 / 알림 상태

저장 슬롯은 정확히 1/2/3 세 개입니다.

- pause: 슬롯 유지
- delete: 슬롯 번호 해제/재사용
- target_price: 필수
- 검색과 슬롯 변경은 process 내에서 직렬화
- add마다 `generation` UUID 생성
- 설정/상태 변경마다 `revision` 증가
- 검색 저장 시 generation/revision 재검증

Alert latch:

```text
ARMED
→ Google 표시 최저 직항가 <= target
→ SENDING
→ ALERTED
→ 가격이 target 위로 복귀
→ ARMED
```

## 가격 의미

현재 제품 알람에서 쓰는 가격:

```text
observed_price = Google Flights flight row에 실제 표시된 왕복 가격
```

DB에는 기존 호환성을 위해 Booking/checkout 관련 column이 남아 있지만, 현재 알람 경로에서는 사용하지 않습니다.

```text
price_verified=False
verification_status=google_flights_displayed_round_trip
```

## Google Flights Provider

Runtime provider:

```text
src/flight_bot/providers.py
name = google-playwright-results-observed
accepted_for_alerts = True
```

가격은 fast-flights parser에서 가져오지 않습니다. `fast-flights`는 현재 URL builder 용도로만 사용합니다.

Live Windows 테스트에서 확인된 가격 로딩 순서를 runtime에도 반영합니다.

```text
검색 결과 진입
→ Cheapest 선택
→ full refresh 1회
→ Cheapest selected 상태 재확인
→ flight-row 가격 수집
```

page-wide KRW minimum이나 body-wide fallback은 사용하지 않습니다.

## Windows 실시간 acceptance

최초 1회 또는 dependency 변경 후:

```text
flight-bot - test win\01-setup-and-unit-test.cmd
```

실시간 테스트:

```text
flight-bot - test win\02-live-cjj-tpe-visible.cmd
```

현재 active live probe는 **검색결과 화면에서 끝납니다.** 출국편/귀국편/Booking을 클릭하지 않습니다.

성공 시 핵심 출력:

```text
=== DIRECT GOOGLE RESULTS ===
direct_offer_1=...
direct_offer_2=...

=== SUMMARY ===
connections_in_alert=0
booking_navigation_performed=False
external_checkout_navigation_performed=False
google_flights_result_url=...
acceptance=GOOGLE_RESULTS_DIRECT_ONLY_SINGLE_LINK
```

## 명령어

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

현재 add된 감시는 직항 기준으로 동작합니다.

## 보안

Production 기본 정책:

- Telegram token 설정 시 `TELEGRAM_ALLOWED_CHAT_IDS` 필수
- Discord token 설정 시 `DISCORD_ALLOWED_CHANNEL_IDS` 필수
- Kakao secret 설정 시 `KAKAO_ALLOWED_USER_IDS` 필수
- Kakao secret 없으면 `/kakao/skill` 404
- Admin secret 없으면 `/admin/check-all` 404
- Admin/Kakao secret 분리
- HTTP 기본 bind는 `127.0.0.1`
- Docker container는 non-root `app` user

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Health endpoint:

```text
GET /health
```

## CI

GitHub Actions:

```text
unit-linux
unit-windows
browser-contract
docker-smoke
```

실제 Google 가격은 hosted CI acceptance 값으로 고정하지 않습니다. 실시간 Google UI acceptance는 사용자 Windows 환경에서 visible Edge로 수행합니다.
