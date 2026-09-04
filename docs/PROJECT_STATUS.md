# Flight Bot — PROJECT STATUS

최종 정리일: 2026-09-04

## 1. 현재 단계

**Google Flights Provider Migration — transient observed gate PASSED / preserved-snapshot departure→return→Booking gate ACTIVE**

Bot Core/DB/알림 구조를 전체 재검수했고, 최근 922,965원 오선택의 직접 원인과 runtime 안전성 결함을 패치했습니다.

runtime `src/flight_bot/providers.py`는 아직 최종 migration 전 legacy Provider입니다. 현재는 fail-closed 상태이며 verified alert용 Provider로 인정하지 않습니다.

## 2. 유지되는 Core 요구사항

- Python 3.12+
- FastAPI / APScheduler
- SQLite WAL
- Telegram / Discord / Kakao reactive skill
- 슬롯 정확히 3개(1/2/3)
- pause 슬롯 점유, delete 후 번호 재사용
- `target_price` 필수
- ARMED → 목표가 하향 돌파 시 1회 → ALERTED → 목표가 위 복귀 시 re-arm
- 동일 below-target 구간 반복 알림 금지
- notifier가 Provider 호출 금지
- 검색 전역 순차 실행
- `REQUIRE_VERIFIED_ALERTS=true`
- 가격/수하물 추정 금지
- 위탁수하물 미확인 = `정보 확인 불가`
- observed / verified 의미 분리
- `verified=True`는 외부 판매처 checkout final total 검증 이후에만 허용

## 3. 기준 acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
stops unrestricted
mixed airlines / separate/self-transfer allowed
```

실시간 가격이므로 특정 금액을 고정 acceptance로 사용하지 않습니다.

## 4. 반복하지 않을 실패 경로

- SerpApi Primary
- direct tfs URL + Playwright
- fast-flights parser 가격 source
- punitarani/fli direct API
- Cheapest tfu URL 반복 fresh-open
- page-wide KRW minimum
- broad results container DOM `.click()` auto picker

## 5. 사용자 Windows transient observed gate — PASSED

Google이 가격을 짧게 렌더링한 뒤 `Price unavailable`로 바꾸는 현상을 확인했습니다.

`MutationObserver` 기반 probe가 사라지기 전 실제 flight-row를 보존했습니다.

```text
transient_lowest=337,056 KRW
seen_ms≈435
11:40 PM → 1:10 AM+1
EASTAR JET
CJJ–TPE
Nonstop
round trip
```

다른 실제 row들도 동시에 포착됐습니다.

```text
415,400
417,960
423,092
430,624
433,972
434,005 KRW
```

따라서 실제 Google flight-row observed price 확보는 성공입니다.

## 6. 최근 922,965원 오선택 — 원인 확정

최근 사용자 pointer run:

```text
departure_selected=922,965 KRW
departure_source_text=922965 South Korean won / ₩922,965
departure_pointer_click_sent=True
body_has_returning=True
current_url=선택된 출국편을 포함하는 새 Google Flights URL
```

이 결과에서 **pointer click 자체는 성공**했습니다. URL이 실제 selected-departure 상태로 변경되고 Returning flights 화면까지 진입했습니다.

가격이 망가진 직접 원인은 이전 JS의 후보 생명주기입니다.

```text
후보 확정 시
source.isConnected
anchor.isConnected
visible(anchor)
```

를 다시 요구했습니다.

33만원대 transient price span은 Google 후속 JS에 의해 빨리 사라져 후보에서 탈락했고, 오래 살아 있던 922,965원 span만 남아 선택됐습니다. 또한 새 후보가 나타날 때마다 settle timer를 다시 시작해 빠르게 사라지는 최저가에 구조적으로 불리했습니다.

즉 **실제 Google 최저가가 922,965원으로 변한 것이 아니라 selection lifecycle bug**였습니다.

## 7. 귀국편 0건 — 원인

같은 실행에서:

```text
return_selection_failed=True
body_has_returning=True
```

였습니다.

출국 선택은 성공했지만 detector가 귀국 카드 안에 literal `TPE-CJJ`가 반드시 있어야 한다고 가정했습니다. Google Returning flights UI는 카드에서 route 문자열을 생략할 수 있으므로 detector가 실제 귀국 카드를 거부할 수 있었습니다.

현재는:

1. 페이지 자체가 `Returning flights` / `귀국 항공편`인지 별도로 확인
2. 그 상태에서만 route 문자열이 없는 compact return card 허용
3. 이전 출국 방향 `CJJ-TPE`가 섞인 card는 계속 거부

으로 변경했습니다.

## 8. 현재 Google UI 구조

공통 순수 계약:

```text
src/flight_bot/google_ui_contract.py
```

담당:

- KRW parsing (`₩335,906`, `335906 South Korean won`)
- compact single-flight card 판정
- broad results container 거부
- preserved snapshot 중 최저 후보 선택
- Cheapest advertised price보다 비싼 fallback 거부
- Returning page 확인 후에만 route-less return card 허용

현재 active live probe:

```text
scripts/google_booking_pointer_probe.py
```

이제 standalone이며 과거 probe를 `importlib`로 연쇄 로딩하지 않습니다.

폐기된 active 경로는 현재 트리에서 제거했습니다.

```text
scripts/google_booking_probe.py          삭제
scripts/google_cheapest_fresh_probe.py   삭제
tests/test_google_booking_probe.py       삭제
```

Git history에는 남아 있습니다.

## 9. preserved-snapshot selection 정책

현재 흐름:

```text
1. canonical Cheapest acceptance URL open
2. Google JS 초기 시점부터 direct-price element 감시
3. 가격/row/anchor 좌표를 snapshot으로 즉시 보존
4. 원 price span이 DOM에서 사라져도 snapshot은 유지
5. 출국 candidate를 첫 후보 이후 900ms 동안 수집
6. Cheapest advertised 가격은 low-water(minimum seen) guard로 유지
7. capture window 완료 후 최저 trustworthy snapshot 선택
8. advertised 값보다 비싼 row만 있으면 클릭하지 않고 fail-closed
9. 실제 Playwright mouse pointer click
10. Returning flights page 진입 확인
11. 귀국 후보 650ms 수집 후 최저 snapshot pointer click
12. Google Booking options CTA 주변 KRW 가격만 확인
```

중요: 광고값이 335,906원인데 922,965원만 잡혔다면 더 이상 922,965원을 선택하지 않습니다.

```text
Cheapest tab advertised a lower price than every captured departure row;
refusing expensive fallback
```

## 10. runtime Provider 안전성 검수

기존 `src/flight_bot/providers.py`에서 다음 결함을 확인했습니다.

### 기존 결함

- page body 전체의 KRW 중 `min()` 사용 가능
- Google Booking page 가격만으로 `price_verified=True` 가능
- 현재 정의한 external checkout verification 경계와 불일치

### 현재 패치

runtime legacy Provider:

```text
name=google-playwright-legacy-unverified
accepted_for_alerts=False
```

- row-scoped flight price만 observed로 허용
- page-wide KRW minimum 금지
- 외부 seller checkout 미구현이므로 항상 `price_verified=False`
- carry-on / checked baggage 미확인 = `정보 확인 불가`
- raw에 verification_status 기록

따라서 기본 `REQUIRE_VERIFIED_ALERTS=true`에서 legacy Provider가 잘못된 verified 알림을 만들 수 없습니다.

`fast-flights`는 현재 legacy URL builder에만 남아 있으며 가격 source가 아닙니다. 최종 Provider migration 후 제거 예정입니다.

## 11. Core 전체 검수에서 수정된 항목

### 검색/알림 동시성

기존 `check_all()` 내부는 순차였지만 scheduler/admin/manual `check`가 겹칠 수 있었습니다.

현재:

- 전체 slot check transaction에 `_check_lock`
- slot state read → Provider → DB save → alert latch까지 직렬화
- 동일 ARMED snapshot을 두 요청이 동시에 읽어 중복 알림하는 race 차단
- `_scan_lock`으로 겹치는 full `check_all` scan 중복 실행 차단

### 알림 실패

notifier 전송 실패 시 `ALERTED`로 latch하지 않습니다. 전송 성공 후에만 alert history와 ALERTED 상태를 기록합니다.

### DB / command

- 없는 slot의 `/flight target` 성공 오표시 수정
- `set_target`, `set_enabled` rowcount 검증
- 귀국일 < 출발일 입력 거부
- 동일 origin/destination 입력 거부
- legacy SQLite migration에 `last_verified_price`, currency 및 offers 관련 누락 column 보강

### 모델

`FlightOffer.total_price` 호환성을 유지하면서:

```text
observed_price
verified_price
```

property를 추가해 가격 의미를 명시했습니다.

### health

`/health`가 실제 runtime provider 이름, `provider_accepted_for_alerts`, `require_verified_alerts`를 표시합니다.

## 12. 현재 live 성공 기준

```text
departure_selected=현재 실제 최저가
departure_selection_policy=advertised-guarded-lowest 또는 captured-lowest
departure_advertised=...
departure_candidate_prices=...
departure_pointer_click_mode=live-marked-anchor 또는 captured-coordinate
departure_navigation_confirmed=True

return_selected=...
return_selection_policy=captured-lowest
return_candidate_prices=...
return_pointer_click_sent=True

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
acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_PRESERVED_TRANSIENT_SNAPSHOTS
```

## 13. verified 경계

Google flight row = observed.

Google Booking options 가격도 아직 final seller checkout 검증이 아닙니다.

최종 alert용:

```text
verified=True
```

는 외부 판매처 checkout에서 실제 final total을 검증하는 설계가 구현된 뒤에만 허용합니다.

## 14. GitHub hosted CI 정책

GitHub hosted Windows에서는 Google flight-row 가격 DOM 자체가 내려오지 않는 것이 확인됐으므로 live Google price는 blocking CI로 사용하지 않습니다.

blocking CI:

```text
Linux Python 3.12 → install → compileall → pytest
Windows Python 3.12 → install → compileall → pytest → Playwright Chromium launch
```

실가격 live acceptance는 사용자 일반 회선 Windows에서 수행합니다.

## 15. 다음 순서

1. 최신 `main`으로 Windows `02-live-cjj-tpe-visible.cmd` 재실행
2. preserved snapshot이 실제 33만원대 최저 출국 row를 선택하는지 확인
3. Returning flights에서 귀국 row 선택 확인
4. Google Booking option CTA/가격 확인
5. 외부 seller checkout final total verification 설계/구현
6. accepted transient flow를 runtime Provider로 migration
7. fast-flights dependency 제거
8. Docker/Ubuntu browser-sidecar 운영 구조 확정
9. 최종 Windows/Linux + live acceptance
