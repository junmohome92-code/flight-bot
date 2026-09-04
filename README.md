# Flight Bot v0.2 — Google Flights 가격 감시

개인 Ubuntu/WSL 홈서버에서 Docker로 실행할 항공권 가격 감시봇입니다.

## 현재 상태 — 2026-09-04

봇 Core/DB/알림 구조는 동작합니다. Google Flights Provider migration은 진행 중입니다.

**중요한 최신 상태:** 사용자 Windows에서 실제 Google Flights 최저가 flight-row를 약 0.4초 시점에 transient DOM으로 포착하는 데 성공했습니다. 현재 gate는 그 row를 사라지기 전에 자동 클릭하고, 귀국편도 선택해 Google Booking options까지 내려가는 것입니다.

runtime `src/flight_bot/providers.py`는 아직 기존 v0.2 Provider입니다. migration 완료가 아닙니다.

## 유지 요구사항

```text
Python 3.12+
FastAPI / APScheduler
SQLite WAL
Telegram / Discord
Kakao reactive skill
slots = exactly 1/2/3
pause keeps slot occupied
delete frees slot number
target_price required
REQUIRE_VERIFIED_ALERTS=true
searches sequential
never synthesize price/baggage data
```

Alert latch:

```text
ARMED
→ verified price <= target : 1 alert
→ ALERTED
→ price > target : re-arm
→ next downward crossing : 1 new alert
```

동일 below-target 구간에서 반복 알림하지 않습니다.

## 기준 acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops allowed
mixed airlines allowed
separate/self-transfer allowed
```

실시간 가격이므로 특정 숫자를 고정 acceptance 값으로 사용하지 않습니다.

## 이미 폐기한 가격 Source

- SerpApi Primary: 일반 Google Flights 대비 비싼 결과/저렴한 혼합 결과 누락 사례
- direct tfs URL + Playwright: `Price unavailable`
- fast-flights parser: 현재 payload와 불일치 / `IndexError`
- punitarani/fli direct API: CJJ↔TPE no-results
- Cheapest tfu URL을 새 탭으로 계속 반복하는 방식: 사용자 Windows 3회 실패

## transient observed gate — 성공

script:

```text
scripts/google_transient_price_probe.py
```

Google page script보다 먼저 `MutationObserver`를 설치하고, 실제 flight-row ancestor가 있는 KRW price만 snapshot합니다. page-wide KRW minimum은 사용하지 않습니다.

사용자 Windows 실측:

```text
transient_lowest=337,056 KRW
seen_ms≈435
EASTAR JET
11:40 PM → 1:10 AM+1
CJJ–TPE
Nonstop
round trip
```

최종:

```text
observed=TRANSIENT_FLIGHT_ROW_CAPTURED
verified=False
acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE
```

즉 Google이 실제로 렌더링한 observed price 확보는 성공했습니다.

## 현재 Windows live gate

```text
flight-bot - test win
└─ 02-live-cjj-tpe-visible.cmd
```

현재 `02`는:

```text
scripts/google_booking_probe.py
```

를 실행합니다.

흐름:

```text
Cheapest tfu URL 확보
→ 새 문서를 Google JS 이전부터 감시
→ CJJ→TPE transient rows 수집
→ 약 140ms 동안 후보를 모아 lowest 출국 row 자동 클릭
→ TPE→CJJ transient rows 감시
→ lowest 귀국 row 자동 클릭
→ Google Booking options의 Book/Continue CTA 주변 KRW 가격 수집
```

page-wide 가격 minimum은 사용하지 않습니다.

성공 출력 예:

```text
departure_click_count=1
departure_selected=... KRW

teturn_click_count=1
return_selected=... KRW

booking_option_candidates=...
booking_option_1=... KRW | ...

=== SUMMARY ===
google_booking_option=... KRW
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_TRANSIENT_ROWS
```

`return_click_count`가 실제 필드명이며 위 예의 `teturn` 오타는 문서상 의미에 영향이 없습니다.

## observed vs verified

- transient flight row = `observed`
- Google Booking option = 실제 예약 CTA/가격 확인 단계
- 외부 판매처 checkout 최종 total 확인 전에는 `verified=False`

따라서 현재도 `REQUIRE_VERIFIED_ALERTS=true`를 유지합니다.

## 명령 예

```text
/flight add CJJ TPE 2026-09-18 2026-09-20 350000
/flight add CJJ TPE 2026-09-18 2026-09-20 350000 nonstop
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
```

## Windows 테스트

```text
01-setup-and-unit-test.cmd
02-live-cjj-tpe-visible.cmd
```

`.venv-win`이 이미 있으면 `01`은 다시 실행할 필요 없습니다.

`02` 실패 시:

```text
artifacts/google-ui-win/auto-click-state*.json
artifacts/google-ui-win/booking-options.json
artifacts/google-ui-win/booking-*.png
artifacts/google-ui-win/booking-*.txt
artifacts/google-ui-win/booking-*.html
```

을 확인합니다.

## CI

일반 blocking CI:

```text
Linux Python 3.12
→ install
→ compileall src/scripts/tests
→ pytest

Windows Python 3.12
→ install
→ compileall src/scripts/tests
→ pytest
→ Playwright Chromium launch
```

GitHub hosted Windows에서는 실제 Google flight-row 가격 DOM이 내려오지 않는 것이 확인됐으므로 live price acceptance는 blocking CI가 아닙니다.

## Docker

실가격 Provider migration gate가 끝난 뒤 운영 배포를 권장합니다.

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose logs -f
```

## 주의

Google Flights는 공개 개발자 API가 아닙니다. UI/DOM 변경, session/IP 조건으로 자동화가 깨질 수 있습니다.

가격을 못 읽었을 때 가짜 값이나 0원을 만들지 않습니다. 위탁수하물 정보가 확인되지 않으면 `없음`이 아니라 `정보 확인 불가`로 표시합니다.

새 채팅에서는 `docs/PROJECT_STATUS.md`와 `docs/HANDOFF_NEW_CHAT.md`를 먼저 읽으세요.
