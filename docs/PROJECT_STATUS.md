# Flight Bot — PROJECT STATUS

최종 정리일: 2026-09-04

## 1. 현재 단계

**Provider Migration Gate — ACTIVE**

Bot Core/DB/목표가 latch/채널 구조는 유지합니다. 현재 막힌 부분은 Google Flights 실제 브라우저 최저가를 신뢰성 있게 얻는 Provider입니다.

운영 Ubuntu 서버로 최종 배포하기 전에 CJJ↔TPE acceptance test를 통과해야 합니다.

## 2. 유지되는 Core

- Python 3.12+
- FastAPI / APScheduler
- SQLite WAL
- Telegram / Discord
- Kakao reactive skill
- 슬롯 정확히 3개(1/2/3)
- pause는 슬롯 점유, delete 후 번호 재사용
- target_price 필수
- alert latch: ARMED → 목표가 하향 돌파 시 1회 → ALERTED → 목표가 위로 복귀 시 re-arm
- `REQUIRE_VERIFIED_ALERTS=true` 기본
- Provider와 notifier 분리
- 검색은 슬롯별 순차 실행
- 가격/수하물 미확인 시 추정값 생성 금지

## 3. 기준 acceptance 시나리오

```text
Origin: CJJ
Destination: TPE
Departure: 2026-09-18
Return: 2026-09-20
Adult: 1
Cabin: Economy
Currency: KRW
Stops: unrestricted
Mixed airlines: allowed
Separate/self-transfer style results: allowed
```

사용자 일반 브라우저에서 같은 조건으로 약 33만 원대 왕복 결과가 관찰된 적이 있습니다. 가격은 실시간이므로 정확한 숫자를 acceptance 조건으로 고정하지 않습니다.

## 4. 이미 거부한 Provider 경로

### SerpApi

브라우저 직접 Google Flights보다 비싸고 저렴한 혼합/별도티켓 스타일 결과가 누락된 사례가 있어 Primary로 복귀시키지 않습니다.

### tfs 직링크 + Playwright

GitHub hosted runner와 사용자 Windows 일반 회선 모두 route/date는 로드했지만 `Price unavailable`이 발생했습니다. 이 경로는 사용하지 않습니다.

### fast-flights 3.1.0 parser

현재 Google payload와 맞지 않아 `IndexError`가 발생했고, RF511/ZE781 등 일부 후보는 `[[], token]` 형태였습니다. 독립 편도 최저가 합은 724,650 KRW로 사용자 일반 브라우저 왕복 최저가와 달랐습니다. 가격 Provider로 사용하지 않습니다.

### punitarani/fli direct service

검증 commit `121d34fea056dc513258958c4262cb5a4cc033c1`. `get_booking_options()` 존재는 확인했으나 CJJ↔TPE는 `Fli returned no round-trip results`였습니다. upstream no-results / BotGuard 관련 제한도 있어 Primary로 채택하지 않습니다.

## 5. 실제 Google Flights UI 실험 결과

### 5.1 Playwright-launched Edge persistent profile — 실패

UI에서 직접 CJJ/TPE/날짜를 입력했고 결과 URL은 정상적으로 `.../travel/flights/search?...&hl=en&gl=kr&curr=KRW`를 생성했지만 `price_candidates=0`, `Price unavailable`이었습니다.

### 5.2 Native Edge + CDP attach 첫 검색 탭 — 실패

실제 `msedge.exe`를 native process로 띄우고 Playwright는 CDP attach만 했지만 자동 검색 결과 탭은 `Price unavailable`이었습니다.

### 5.3 같은 결과 URL을 사용자가 새 창에서 직접 열면 가격 표시

사용자 확인:

```text
자동화가 만든 Google Flights 검색 URL
→ 해당 URL을 복사
→ 새 브라우저 창/탭에서 직접 열기
→ 가격 정상 표시
```

이 관찰 때문에 generated URL을 fresh tab에서 다시 여는 방식으로 gate를 전환했습니다.

### 5.4 자동 fresh tab 가격 렌더링 — 성공, 최저가 탭 선택은 실패 확인

2026-09-04 사용자 Windows 실측:

```text
fresh_tab_attempt=1
navigator_webdriver=False
footer_location=South Korea
footer_currency=KRW
price_candidates=2
887,003 KRW
1,270,502 KRW
```

즉 **Playwright/CDP가 붙은 fresh tab에서도 실제 KRW flight-row 가격 렌더링은 성공**했습니다. 따라서 이전의 `Price unavailable` 문제는 fresh navigation으로 우회 가능한 근거가 생겼습니다.

하지만 같은 화면에서 사용자가 확인한 Google Flights UI에는 별도 `추천` / `최저가` 탭이 있었고 `최저가` 탭에는 약 `₩338,121부터`가 표시됐습니다. 기존 probe는 `get_by_text("Cheapest", exact=True)`만 사용했기 때문에 한국어 `최저가` 탭을 클릭하지 못했고, 기본 `추천` 탭 가격을 읽고도 `PRICE_VISIBLE_AFTER_FRESH_TAB`을 출력했습니다.

따라서 이 결과는 **browser price-render gate 성공**이지 **실제 최저가 acceptance 성공은 아닙니다.** runtime Provider migration은 아직 시작하지 않습니다.

## 6. 현재 acceptance — fresh tab + localized Cheapest/최저가 확인

`scripts/google_ui_probe.py` 현재 흐름:

```text
1. native Edge + dedicated profile 실행
2. 첫 탭에서 Google Flights UI 직접 입력
3. 생성된 /travel/flights/search URL 확보
4. 동일 Edge context에서 새 탭 생성
5. 동일 URL fresh navigation
6. Cheapest / 최저가 탭을 영어·한국어 모두 탐색
7. 탭 클릭 여부와 탭 광고 최저가(예: ₩338,121부터) 기록
8. More flights / 항공편 더보기 필요 시 확장
9. flight-row scoped KRW 가격만 읽기
10. 탭 광고 최저가보다 row parser 최저가가 비싸면 acceptance 거부
11. 실패 시 여러 fresh tab 반복
```

### 6.1 probe hardening

- page body 전체의 KRW 최소값 fallback 제거
- 가격 element에서 최대 12단계 ancestor를 올라가 실제 flight-row 형태를 찾도록 보강
- `aria-label`뿐 아니라 visible KRW text도 row-shaped ancestor가 확인된 경우에만 가격 후보 인정
- 한국어 `최저가`, `항공편 더보기`, 결과 section marker 지원
- fresh tab에서 가격이 늦게 채워질 수 있으므로 row 가격 기본 15초 추가 대기
- `generated_search_url`, `fresh_url`, `price_candidates` 출력
- URL / `navigator.webdriver` / language / timezone / Footer Language·Location·Currency 진단 유지
- screenshot / body text / HTML artifact 유지
- localized cheapest-tab 및 가격 일치 helper unit test 추가

성공 기준은 이제 더 엄격합니다.

```text
cheapest_tab_found=True
cheapest_tab_clicked=True
cheapest_advertised=... KRW
price_candidates=...
cheapest_row_lowest=... KRW
cheapest_price_match=True

=== SUMMARY ===
fresh_tab_attempt=N
ui_lowest=... KRW
acceptance=CHEAPEST_PRICE_VISIBLE_AFTER_FRESH_TAB
```

`render_gate=PRICE_VISIBLE_AFTER_FRESH_TAB`은 fresh tab에서 가격 렌더링 자체가 됐다는 중간 증거일 뿐, 최종 acceptance가 아닙니다.

## 7. 현재 중요한 경계

`src/flight_bot/providers.py` runtime Provider는 아직 기존 v0.2 `tfs URL + Playwright` 구현입니다.

**`CHEAPEST_PRICE_VISIBLE_AFTER_FRESH_TAB`이 실제 사용자 Windows에서 확인되기 전에는 runtime Provider를 교체하지 않습니다.**

현재 상태:

```text
Bot Core: usable
DB/latch: usable
Windows/Linux unit CI: usable
Fresh-tab price rendering: confirmed on user Windows
Localized cheapest-tab extraction: current gate
Runtime Google price Provider: migration pending
```

## 8. CI 상태/정책

최종 live Google Flights acceptance는 GitHub hosted runner가 아니라 사용자 Windows의 `02-live-cjj-tpe-visible.cmd`로 수행합니다.

기존 manual diagnostic job은 Windows-visible 전용 probe를 Ubuntu/headless에서 실행하도록 되어 있어 제거했습니다. 일반 CI는 Linux/Windows Python 3.12 compile/test와 Windows Playwright Chromium launch를 검증합니다.

## 9. fresh tab도 자동화에서 다시 막히면 다음 분기

현재는 자동 fresh tab에서 실제 가격 렌더링까지 확인됐으므로 browser extension sidecar 분기는 우선순위가 낮아졌습니다.

다만 향후 일반 브라우저에서는 가격이 나오는데 자동 fresh tab에서 다시 지속적으로 `Price unavailable`이 발생한다면 일반 사용자 브라우저 extension/content-script sidecar를 대안으로 검토합니다. stealth/CAPTCHA/BotGuard 우회를 기본 전략으로 넣지 않습니다.

## 10. acceptance 성공 후

1. runtime Provider를 검증된 fresh-tab 방식으로 교체
2. 페이지 전체 min이 아닌 실제 flight row 가격만 비교
3. 최저 출국 후보 클릭
4. 귀국 후보 선택
5. Booking / final price 단계 검증
6. 표시 가격은 `observed`, Booking 검증 가격만 `verified`
7. `REQUIRE_VERIFIED_ALERTS=true` 유지
8. fast-flights dependency 제거
9. Docker/Ubuntu 또는 browser-sidecar 운영구조 결정
10. Windows/Linux tests + live acceptance 재검증

## 11. 이후 구조 개선

- 약 10분 local cache
- 동일 검색 single-flight coalescing
- watch slot과 notification subscription 분리
- provider attempt / cache hit / error logging
- browser process/context 재사용 검토
- Provider error taxonomy 확대

## 12. 절대 되돌리지 말 것

- SerpApi를 근거 없이 Primary로 복원하지 말 것
- `fast-flights.get_flights()`를 가격 source로 복원하지 말 것
- Fli direct API를 CJJ↔TPE 실가격 source로 다시 채택하지 말 것
- Google 가격이 없을 때 다른 숫자를 추정/합성하지 말 것
- 수하물 미확인을 `없음`으로 바꾸지 말 것
