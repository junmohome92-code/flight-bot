# Flight Bot — NEW CHAT HANDOFF

기준 브랜치: `main`

시작할 때 먼저 읽기:

```text
README.md
docs/PROJECT_STATUS.md
docs/HANDOFF_NEW_CHAT.md
```

## 현재 한 줄 요약

**Google Flights 실제 transient flight-row 가격 capture는 사용자 Windows에서 성공했습니다. 첫 auto-click probe는 summary/results 전체 컨테이너를 실제 항공편 row로 오인해 `922,965 KRW`를 잘못 선택했고 귀국편으로 전환되지 않았습니다. 현재 코드는 exact compact flight row만 선택하도록 수정됐고, 다음 gate는 정확한 출국편 → 귀국편 → Google Booking options입니다.**

runtime `src/flight_bot/providers.py`는 아직 기존 v0.2 Provider이며 migration 완료가 아닙니다.

## 기준 acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate/self-transfer allowed
```

가격은 실시간이므로 특정 숫자를 고정 acceptance 값으로 사용하지 않습니다.

## 이미 폐기한 경로

- SerpApi Primary
- fast-flights parser 가격 source
- punitarani/fli direct API
- 기존 direct tfs URL Provider
- URL reload/new-tab을 계속 반복하는 전략

가격/수하물 추정은 금지합니다.

## observed-price gate — 통과

사용자 Windows transient probe:

```text
cheapest_fresh_transient_count=24
transient_lowest=337,056 KRW
11:40 PM → 1:10 AM+1
EASTAR JET
CJJ–TPE
Nonstop
round trip
seen_ms≈435
```

Google Flights가 약 0.4초 시점에 실제 가격 row를 DOM에 렌더링했고 `MutationObserver`가 사라지기 전에 보존했습니다.

```text
observed=TRANSIENT_FLIGHT_ROW_CAPTURED
verified=False
acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE
```

## 첫 auto-click probe에서 발견된 결함

사용자 Windows 결과:

```text
departure_click_count=1
departure_selected=922,965 KRW
return_click_count=0
```

하지만 `departure_row`에는 실제 한 항공편이 아니라:

```text
Best / Cheapest / Fetching results / Checking prices...
+ Aero K row
+ Korean Air/Asiana rows
+ 여러 CJJ-TPE 항공편
```

가 한꺼번에 들어 있었습니다.

즉 **출국 선택 성공이 아니라 broad results container 오클릭**입니다. 이 결과는 acceptance로 인정하지 않습니다.

## 현재 수정된 exact-row auto picker

script:

```text
scripts/google_booking_probe.py
```

Windows:

```text
flight-bot - test win/02-live-cjj-tpe-visible.cmd
```

후보 row 필수 조건:

```text
요청 route(CJJ-TPE 또는 TPE-CJJ) 정확히 1회
시간 표현 2~4개
row 내 KRW 가격 1~3개
row text <= 2200자
flight shape marker 존재
```

여러 항공편을 동시에 포함한 큰 container는 자동 탈락합니다.

transient price element에서 exact row를 찾는 순간:

```text
data-flight-bot-row-id
data-flight-bot-target-id
```

를 실제 DOM에 붙이고 그 동일 target을 클릭합니다. 클릭 시 ancestor를 다시 추정하지 않습니다.

추가 보강:

- candidate settle 약 70ms
- canonical Cheapest `tfu` URL 직접 open으로 acceptance startup 단축
- departure→returning phase와 click 기록을 `sessionStorage`에 유지
- full navigation이 발생해도 returning phase 복원
- broad-results-container 회귀 테스트 추가

## 다음 live 성공 기준

```text
departure_click_count=1
departure_row_shape=times:2 route_count:1 prices:1 ...
departure_selected=... KRW

auto target/row ID 출력

return_click_count=1
return_row_shape=times:2 route_count:1 prices:1 ...
return_selected=... KRW

booking_options_marker=True
booking_option_candidates=>0

=== SUMMARY ===
departure_observed=...
return_selection_price=...
google_booking_option=...
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_EXACT_TRANSIENT_ROWS
```

## 결과 분기

### A. exact 출국/귀국 선택 + Booking option 성공

다음 gate는 외부 판매처 checkout의 실제 final total 검증입니다. 그 전까지 `verified=False`와 `REQUIRE_VERIFIED_ALERTS=true` 유지.

### B. exact 출국 row가 0건

`departure-selection-failed.*`와 `auto-click-state-departure-failed.json`을 기준으로 exact-row 제한을 조정합니다. broad container fallback은 금지합니다.

### C. exact 출국은 선택되나 귀국 0건

`return-selection-failed.*` artifact로 실제 returning route/DOM 구조를 확인합니다. broad ancestor 방식으로 되돌리지 않습니다.

### D. 귀국까지 선택되나 Booking option 0건

Booking options CTA/price DOM만 보강합니다.

## GitHub hosted CI 정책

GitHub hosted Windows에서는 Google flight-row 가격 자체가 내려오지 않는 것이 확인됐으므로 live Google price는 blocking CI가 아닙니다.

일반 CI:

```text
Linux Python 3.12 → install → compileall → pytest
Windows Python 3.12 → install → compileall → pytest → Playwright Chromium launch
```

## 유지 요구사항

- 슬롯 정확히 3개
- pause 슬롯 점유 / delete 후 번호 재사용
- `target_price` 필수
- ARMED → 목표가 하향 돌파 1회 → ALERTED → 목표가 위 복귀 시 re-arm
- 동일 below-target 구간 반복 알림 금지
- notifier가 Provider 호출 금지
- SQLite WAL
- 검색 순차 실행
- `REQUIRE_VERIFIED_ALERTS=true`
- observed와 verified 구분
- 위탁수하물 미확인 = `정보 확인 불가`
