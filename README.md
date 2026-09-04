# Flight Bot v0.2 — Google Flights 가격 감시

개인 Ubuntu/WSL 홈서버에서 Docker로 실행할 항공권 가격 감시봇입니다.

## 현재 상태 — 2026-09-04

Bot Core/DB/알림 구조는 유지되고 있으며 Google Flights Provider migration은 진행 중입니다.

사용자 Windows에서 Google Flights가 약 0.4초 동안 실제 최저가 flight row를 렌더링한 뒤 `Price unavailable`로 바꾸는 현상을 확인했고, 사라지기 전 transient row snapshot을 보존하는 데 성공했습니다.

확인된 실제 예:

```text
337,056 KRW
EASTAR JET
11:40 PM → 1:10 AM+1
CJJ–TPE
Nonstop
round trip
```

가격은 실시간이므로 특정 숫자를 고정 acceptance 값으로 사용하지 않습니다.

현재 live gate는 **보존된 transient 최저 row → 실제 pointer click → 귀국편 → Google Booking options**입니다. 외부 판매처 checkout final total 확인 전에는 `verified=False`입니다.

runtime `src/flight_bot/providers.py`는 아직 migration 전 legacy Provider입니다. 안전을 위해 현재 legacy Provider는 row-scoped observed 가격만 반환하고 절대 `price_verified=True`를 만들지 않습니다.

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
searches globally sequential
never synthesize price/baggage data
unknown baggage = 정보 확인 불가
```

Alert latch:

```text
ARMED
→ verified price <= target : 1 alert
→ ALERTED
→ price > target : re-arm
→ next downward crossing : 1 new alert
```

동일 below-target 구간에서 반복 알림하지 않습니다. 스케줄러/관리 API/수동 check가 겹쳐도 전체 check transaction을 lock해서 Provider 호출과 alert latch가 순차 처리됩니다.

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

## 폐기한 가격 경로

- SerpApi Primary
- direct tfs URL + Playwright
- fast-flights parser를 가격 source로 사용
- punitarani/fli direct API
- Cheapest tfu URL을 반복 fresh-open
- 큰 results container에 DOM `.click()`을 보내는 auto picker

`fast-flights`는 현재 legacy runtime의 URL builder에만 남아 있고 가격 parser로는 사용하지 않습니다. 새 Provider migration 완료 후 제거 대상입니다.

## 왜 922,965원을 잘못 골랐나

최근 pointer probe는 클릭 자체는 성공했습니다. 실제 URL이 출국편 선택 URL로 바뀌었고 `Returning flights` 화면에도 진입했습니다.

하지만 후보 확정 직전에 다음 조건을 사용했습니다.

```text
price source isConnected
anchor isConnected
anchor visible
```

약 33만원대 최저가 price span은 Google 후속 JS에 의해 빠르게 사라졌으므로 후보에서 탈락했고, 오래 남아 있던 922,965원 row가 대신 선택됐습니다. 후보 timer도 새 후보마다 다시 밀려 transient 최저가에 불리한 구조였습니다.

즉 **Google 가격이 갑자기 92만원으로 변한 것이 아니라 후보 생명주기 설계 결함**이었습니다.

## 현재 구조

공통 순수 계약:

```text
src/flight_bot/google_ui_contract.py
```

여기서 다음을 담당합니다.

- KRW 가격 parsing (`₩335,906`, `335906 South Korean won`)
- 한 flight card인지 판정
- broad results container 거부
- preserved snapshots 중 최저가 선택
- Cheapest 탭이 더 싼 가격을 광고하는데 그 row를 못 잡았으면 비싼 fallback 금지
- Returning flights 화면이 별도로 확인된 경우에만 귀국 card의 route 문자열 생략 허용

현재 Windows live probe:

```text
scripts/google_booking_pointer_probe.py
```

이 script는 이전 probe들을 importlib로 연쇄 로딩하지 않는 standalone 실행 경로입니다.

흐름:

```text
canonical Cheapest acceptance URL open
→ 페이지 초기 시점부터 transient 가격 row snapshot 보존
→ 출국 후보를 900ms capture window 동안 수집
→ 사라진 price span도 후보 snapshot에서 유지
→ Cheapest advertised 가격을 low-water guard로 사용
→ 최저 출국 row에 실제 Playwright mouse click
→ Returning flights 화면 진입을 별도로 확인
→ 귀국 후보를 650ms capture window 동안 수집
→ 귀국 row pointer click
→ Google Booking options의 Book/Continue CTA 주변 가격만 수집
```

page-wide KRW minimum은 사용하지 않습니다.

Cheapest 탭이 예를 들어 약 335,000원을 표시했는데 922,965원 row만 잡혔다면 클릭하지 않고 실패합니다.

```text
Cheapest tab advertised a lower price than every captured departure row;
refusing expensive fallback
```

## Windows 테스트

```text
flight-bot - test win\01-setup-and-unit-test.cmd
flight-bot - test win\02-live-cjj-tpe-visible.cmd
```

`.venv-win`이 이미 있으면 최신 ZIP을 받은 뒤 `02`만 실행하면 됩니다.

새 live 출력에서 핵심 필드:

```text
departure_selected=... KRW
departure_selection_policy=advertised-guarded-lowest 또는 captured-lowest
departure_advertised=...
departure_candidate_prices=...
departure_pointer_click_mode=live-marked-anchor 또는 captured-coordinate
departure_navigation_confirmed=True

return_selected=... KRW
return_selection_policy=captured-lowest
return_candidate_prices=...
return_pointer_click_sent=True

booking_options_marker=True
booking_option_candidates=>0
```

최종 live 성공 기준:

```text
=== SUMMARY ===
departure_observed=...
return_selection_price=...
google_booking_option=...
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_PRESERVED_TRANSIENT_SNAPSHOTS
```

실패 시 주요 artifact:

```text
artifacts/google-ui-win/snapshot-departure-state.json
artifacts/google-ui-win/snapshot-return-state.json
artifacts/google-ui-win/snapshot-error-state.json
artifacts/google-ui-win/*.png
artifacts/google-ui-win/*.txt
artifacts/google-ui-win/*.html
```

## observed vs verified

- Google flight row = `observed_price`
- Google Booking option = 예약 선택 단계 가격
- 외부 판매처 checkout final total = 향후 `verified_price` 경계

`FlightOffer`은 기존 `total_price` 호환성을 유지하면서 `observed_price`와 `verified_price` property를 명시적으로 제공합니다.

현재 legacy runtime Provider는 외부 seller checkout을 구현하지 않았으므로 항상 `verified=False`입니다. 따라서 기본 `REQUIRE_VERIFIED_ALERTS=true`에서는 잘못된 legacy 가격으로 목표가 알림을 보내지 않습니다.

## Core 검수에서 함께 수정한 항목

- 전체 slot check transaction 전역 직렬화: 중복 Provider 호출/동시 alert latch race 방지
- 겹치는 `check_all` full scan 중복 실행 방지
- notifier 전송 실패 시 ALERTED로 잘못 latch하지 않음
- 없는 slot의 `/flight target` 성공 오표시 수정
- 귀국일 < 출발일 입력 거부
- legacy SQLite migration에 `last_verified_price`, currency 및 offers 누락 column 보강
- `/health`가 실제 runtime Provider 이름과 alert safety 상태를 표시

## CI

blocking CI:

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

GitHub hosted Windows에서는 실제 Google flight-row 가격 DOM이 내려오지 않는 것이 확인됐으므로 live Google 가격 acceptance는 blocking CI가 아닙니다. 실제 live gate는 사용자 일반 회선 Windows에서 수행합니다.

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

## Docker

실가격 Provider migration gate가 끝난 뒤 운영 배포를 권장합니다.

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose logs -f
```

Google Flights는 공개 개발자 API가 아니므로 UI/DOM/session/IP 조건으로 자동화가 깨질 수 있습니다. 가격이나 수하물 정보를 확인하지 못하면 값을 만들어내지 않습니다.
