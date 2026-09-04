# Flight Bot — NEW CHAT HANDOFF

기준 브랜치: `main`

시작할 때 먼저 읽기:

```text
README.md
docs/PROJECT_STATUS.md
docs/HANDOFF_NEW_CHAT.md
```

## 현재 한 줄 요약

**Google Flights의 실제 최저가 flight-row를 사라지기 전에 캡처하는 1차 acceptance는 사용자 Windows에서 성공했습니다. 현재 gate는 그 transient 최저 출국편을 즉시 클릭하고, 귀국편도 같은 방식으로 선택해 Google Booking options까지 도달하는 것입니다.**

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

## 중요한 실제 실험 결과

사용자 Windows transient probe에서 다음이 확인됐습니다.

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

즉 Google Flights가 약 0.4초 시점에 실제 가격 row를 DOM에 렌더링했고, 이후 DOM 상태가 바뀌더라도 `MutationObserver`가 해당 row를 보존했습니다.

최종 출력:

```text
observed=TRANSIENT_FLIGHT_ROW_CAPTURED
verified=False
acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE
```

따라서 **observed-price gate는 통과**했습니다.

## 현재 Windows live test

```text
flight-bot - test win/02-live-cjj-tpe-visible.cmd
```

현재 `02`는 다음 script를 실행합니다.

```text
scripts/google_booking_probe.py
```

흐름:

```text
1. canonical CJJ/TPE acceptance URL로 Cheapest tfu URL 확보
2. 새 문서를 Google JS보다 먼저 감시
3. CJJ→TPE transient flight rows를 약 140ms debounce 동안 수집
4. 최저 출국 row를 사라지기 전에 자동 클릭
5. 화면이 TPE→CJJ rows로 바뀌면 같은 observer가 최저 귀국 row 자동 클릭
6. Google Booking options / Book/Continue CTA 주변의 KRW 가격만 수집
7. page-wide KRW minimum은 사용하지 않음
```

성공 시 예상 출력:

```text
departure_click_count=1
departure_selected=... KRW
departure_row=...

return_click_count=1
return_selected=... KRW
return_row=...

booking_options_marker=True
booking_option_candidates=...
booking_option_1=... KRW | ...

=== SUMMARY ===
departure_observed=...
return_selection_price=...
google_booking_option=...
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_TRANSIENT_ROWS
```

## 결과 분기

### A. 출국/귀국 모두 자동 선택 + Booking option 성공

다음 gate는 외부 판매처 checkout을 열어 **실제 판매 가능한 최종 total**을 검증하는 것입니다. 그 전까지 `verified=False`와 `REQUIRE_VERIFIED_ALERTS=true`를 유지합니다.

### B. 출국 transient는 잡히지만 `departure_click_count=0`

row click target/DOM 구조 문제입니다. `auto-click-state-error.json` + `booking-probe-error.*` artifact를 분석해 click target만 수정합니다.

### C. 출국은 선택되나 귀국 `return_click_count=0`

returning page의 실제 route/row DOM을 artifact로 분석해 TPE→CJJ selector를 보강합니다.

### D. 귀국까지 선택되나 booking option 0건

Booking options page의 CTA/price DOM selector를 artifact 기준으로 보강합니다.

## GitHub hosted CI 정책

GitHub hosted Windows에서는 Google flight-row 가격 자체가 내려오지 않는 것이 확인됐습니다. 따라서 live Google price는 blocking CI가 아닙니다.

일반 CI만 유지:

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
