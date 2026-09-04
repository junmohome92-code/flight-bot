# Flight Bot — PROJECT STATUS

최종 정리일: 2026-09-04

## 1. 현재 단계

**Google Flights Provider Migration — observed gate PASSED / selection + booking gate ACTIVE**

Bot Core/DB/알림 구조는 유지합니다. runtime `src/flight_bot/providers.py`는 아직 기존 v0.2 Provider이며 교체 전입니다.

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
- 검색 순차 실행
- `REQUIRE_VERIFIED_ALERTS=true`
- 가격/수하물 추정 금지
- 위탁수하물 미확인 = `정보 확인 불가`

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

- SerpApi Primary: 일반 Google Flights보다 비싸거나 저렴한 혼합/별도티켓 결과 누락 사례
- direct tfs URL + Playwright: `Price unavailable`
- fast-flights parser: 현재 payload와 불일치 / `IndexError`
- punitarani/fli direct API: CJJ↔TPE no-results
- Cheapest tfu URL을 새 탭으로 반복 재오픈하는 전략: 사용자 Windows 3회 실패

## 5. GitHub hosted Windows 실테스트

실제 `windows-latest` + native Edge에서도 generated URL / Cheapest 클릭 / tfu URL fresh open을 테스트했습니다.

hosted 데이터센터 환경에서는 flight-row 가격 DOM 자체가 내려오지 않았습니다. 따라서 Google live price는 hosted CI의 blocking gate로 사용하지 않습니다.

일반 CI만 유지합니다.

## 6. 사용자 Windows transient capture — 성공

사용자가 Chromium/Edge에서 가격이 처음 잠깐 나타났다 사라지는 현상을 관찰해, Google page script보다 먼저 `MutationObserver`를 설치하는 probe를 구현했습니다.

script:

```text
scripts/google_transient_price_probe.py
```

2026-09-04 사용자 실측 성공:

```text
cheapest_fresh_transient_count=24
transient_lowest=337,056 KRW
phase=document-init
seen_ms≈435

11:40 PM → 1:10 AM+1
EASTAR JET
CJJ–TPE
Nonstop
₩337,056 round trip
```

다른 실제 row도 함께 포착됐습니다.

```text
415,400 KRW Aero K Airlines Nonstop
417,960 KRW Aero K Airlines + Jin Air 1 stop
423,092 KRW Jeju Air + Jin Air 1 stop
430,624 KRW Aero K Airlines + EASTAR JET 1 stop
433,972 KRW T'Way Air + EASTAR JET 1 stop
434,005 KRW EASTAR JET 1 stop
```

최종:

```text
observed=TRANSIENT_FLIGHT_ROW_CAPTURED
verified=False
acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE
```

따라서 **실제 Google flight-row observed price 확보는 성공**으로 판정합니다.

`final_dom_price_candidates=0`은 gate 실패가 아닙니다. 목적이 최종 DOM이 아니라 Google 후속 상태변경 전에 실제 row snapshot을 보존하는 것이기 때문입니다.

## 7. 현재 gate — transient row 자동 선택 → Booking options

새 script:

```text
scripts/google_booking_probe.py
```

Windows `02-live-cjj-tpe-visible.cmd`가 이 script를 실행합니다.

흐름:

```text
1. fixed acceptance canonical URL에서 Cheapest tfu URL 확보
2. 새 Cheapest 문서를 Google JS 이전부터 감시
3. CJJ→TPE transient rows를 짧게 모아 최저가 row 자동 클릭
4. TPE→CJJ returning rows가 나타나면 최저 row 자동 클릭
5. Google Booking options / Book / Continue CTA 주변의 KRW 가격 수집
6. page-wide KRW minimum 사용 금지
```

현재 auto-click debounce는 약 140ms입니다. 사용자 실측에서 실제 출국 row가 약 435~470ms 구간에 함께 나타난 것을 근거로 후보 여러 개를 짧게 모은 뒤 lowest를 선택합니다.

성공 기준:

```text
departure_click_count=1
departure_selected=... KRW
return_click_count=1
return_selected=... KRW
booking_option_candidates=>0

=== SUMMARY ===
google_booking_option=... KRW
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_TRANSIENT_ROWS
```

## 8. verified 경계

transient flight row는 **observed**입니다.

Google Booking option에 실제 예약 CTA와 가격이 확인돼도 현재 gate에서는 외부 판매처 checkout을 열지 않으므로:

```text
external_checkout_verified=False
verified=False
```

를 유지합니다.

최종 alert용 `verified=True`는 외부 판매처 checkout/최종 total 검증 설계를 확정한 뒤에만 허용합니다.

## 9. 현재 runtime 경계

`src/flight_bot/providers.py`는 아직 기존 v0.2 `tfs URL + Playwright` 구현입니다.

selection/Booking gate가 안정적으로 통과하기 전에는 runtime Provider migration을 완료했다고 말하지 않습니다.

## 10. 이후 순서

1. transient 출국 row 자동 선택 검증
2. returning TPE→CJJ row 자동 선택 검증
3. Google Booking option 가격/CTA 검증
4. 외부 판매처 checkout final total 검증 범위 결정
5. observed / verified 모델 반영
6. runtime Provider 교체
7. fast-flights dependency 제거
8. Docker/Ubuntu 또는 browser-sidecar 운영구조 결정
9. Windows/Linux tests + live acceptance

## 11. CI

```text
Linux Python 3.12
→ install
→ compileall
→ pytest

Windows Python 3.12
→ install
→ compileall
→ pytest
→ Playwright Chromium launch
```

Google live price는 사용자 일반 회선 Windows에서 검증합니다.
