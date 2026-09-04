# Flight Bot — NEW CHAT HANDOFF

기준 브랜치: `main`

시작할 때 먼저 읽기:

```text
README.md
docs/PROJECT_STATUS.md
docs/HANDOFF_NEW_CHAT.md
```

## 현재 한 줄 요약

**Google transient observed-price capture는 성공. 최근 922,965원 오선택은 transient 최저 price span이 사라진 뒤 `isConnected` 필터에 의해 버려지고 안정적으로 남은 비싼 row가 선택된 lifecycle bug로 원인이 확정됐습니다. 현재 active probe는 transient snapshot을 DOM 생존 여부와 분리해 보존하고, capture window 완료 후 최저 후보를 선택하며, Returning flights에서 route 문자열이 생략되는 UI도 제한적으로 지원합니다. 다음 gate는 최저 출국 → 귀국 → Google Booking options입니다.**

## acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate/self-transfer allowed
```

가격은 실시간이므로 특정 금액 고정 금지.

## observed gate — PASSED

사용자 Windows에서 약 435ms 시점에 실제 row capture:

```text
337,056 KRW
EASTAR JET
11:40 PM → 1:10 AM+1
CJJ–TPE
Nonstop
round trip
```

```text
observed=True
verified=False
```

## 최근 pointer run에서 확인된 사실

사용자 결과:

```text
departure_selected=922,965 KRW
departure_pointer_click_sent=True
body_has_returning=True
current_url=selected-departure Google Flights URL
```

따라서 **pointer click/navigation은 성공**했습니다.

오선택 원인:

```text
후보 확정 시 source.isConnected + anchor.isConnected + visible 요구
→ 33만원대 transient price span 소멸
→ cheap candidate 탈락
→ 오래 남은 922,965원 candidate 선택
```

새 후보마다 settle timer를 다시 시작한 것도 transient lowest에 불리했습니다.

귀국 0건 원인:

```text
return_selection_failed=True
body_has_returning=True
```

Returning flights 화면은 실제로 로드됐지만 detector가 카드 안에 `TPE-CJJ` literal을 강제했습니다. 현재는 Returning flights marker를 먼저 확인한 경우에만 route-less compact return card를 허용합니다. `CJJ-TPE`가 섞인 card는 계속 거부합니다.

## 현재 active 구조

공통 정책:

```text
src/flight_bot/google_ui_contract.py
```

active live script:

```text
scripts/google_booking_pointer_probe.py
```

Windows:

```text
flight-bot - test win/02-live-cjj-tpe-visible.cmd
```

현재 probe는 standalone입니다. 이전 `pointer → booking → transient → ui` importlib 체인을 제거했습니다.

obsolete current-tree files 제거:

```text
scripts/google_booking_probe.py
scripts/google_cheapest_fresh_probe.py
tests/test_google_booking_probe.py
```

## 현재 selection 정책

```text
canonical Cheapest URL
→ early direct-price rows snapshot
→ price/row/anchor coordinate를 즉시 보존
→ 원 price span이 사라져도 snapshot 유지
→ 출국 첫 후보 후 900ms capture window 완료까지 대기
→ Cheapest advertised price를 seen-minimum(low-water) guard로 유지
→ preserved snapshots 중 최저 trustworthy row 선택
→ advertised보다 비싼 fallback만 있으면 FAIL, 절대 클릭 안 함
→ real Playwright mouse click
→ Returning flights marker 확인
→ return first candidate 후 650ms capture
→ return card 최저 pointer click
→ Booking CTA-scoped prices
```

성공 출력 핵심:

```text
departure_selected=...
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
acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_PRESERVED_TRANSIENT_SNAPSHOTS
external_checkout_verified=False
verified=False
```

만약 Cheapest가 약 335k를 광고하는데 snapshot에 922k만 있다면 예상 failure는:

```text
Cheapest tab advertised a lower price than every captured departure row;
refusing expensive fallback
```

이 경우 922k를 선택하면 안 됩니다.

## 실패 artifact

```text
artifacts/google-ui-win/snapshot-departure-state.json
artifacts/google-ui-win/snapshot-return-state.json
artifacts/google-ui-win/snapshot-error-state.json
artifacts/google-ui-win/*.png/.txt/.html
```

특히 return 실패 시 `snapshot-return-state.json`의:

```text
returningMarker
candidates[].price
candidates[].rowText
candidates[].sourceText
```

를 확인합니다.

## runtime 안전 상태

`src/flight_bot/providers.py`는 아직 최종 migration 전입니다.

현재 legacy runtime:

```text
name=google-playwright-legacy-unverified
accepted_for_alerts=False
```

- page-wide KRW min 금지
- row-scoped observed만 허용
- seller checkout 미구현 → 항상 `price_verified=False`
- 기본 `REQUIRE_VERIFIED_ALERTS=true`이므로 legacy runtime 가격으로 threshold alert 불가
- baggage 미확인 = `정보 확인 불가`

최종 live gate 통과 후 accepted transient flow로 Provider migration.

## Core audit에서 같이 패치된 항목

- full check transaction global lock: scheduler/admin/manual overlap에서도 검색 + alert latch 직렬화
- overlapping `check_all` scan 방지
- notifier 실패 시 ALERTED latch 금지
- 없는 slot `/flight target` 성공 오표시 수정
- return date < departure date 거부
- legacy DB migration 누락(`last_verified_price`, currency, offers fields) 보강
- `FlightOffer.observed_price` / `verified_price` 명시
- `/health`가 실제 provider + alert acceptance 상태 표시

## verified 경계

```text
Google row             = observed
Google Booking option  = booking option visible
external seller final total = verified
```

외부 checkout 전에는 항상:

```text
external_checkout_verified=False
verified=False
```

## 다음 액션

사용자가 최신 ZIP을 받은 뒤 **01은 생략하고 `02-live-cjj-tpe-visible.cmd`만 실행**합니다.

A. 최저 출국 + 귀국 + Booking option 성공 → external seller checkout gate 설계

B. 출국에서 fail-closed → `snapshot-departure-state.json`으로 missing cheapest capture 원인 확인

C. Returning page는 True인데 return candidate 0 → `snapshot-return-state.json`으로 실제 return-card DOM 조정

D. return click까지 성공, Booking 0 → Booking CTA/price scope만 보강

## 유지 요구사항

- exactly 3 slots
- pause occupies / delete reuses
- target_price mandatory
- ARMED/ALERTED latch semantics
- no repeated below-target alerts
- notifier never invokes Provider
- SQLite WAL
- searches globally sequential
- `REQUIRE_VERIFIED_ALERTS=true`
- never synthesize price/baggage
- unknown baggage = `정보 확인 불가`
