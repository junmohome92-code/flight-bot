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

### 5.2 Native Edge + CDP attach — 실패

실제 `msedge.exe`를 native process로 띄우고 Playwright는 CDP attach만 했지만 자동 검색 결과 탭은 여전히 `Price unavailable`이었습니다.

### 5.3 핵심 관찰 — 같은 결과 URL을 사용자가 새 창에서 직접 열면 가격 표시

사용자 확인:

```text
자동화가 만든 Google Flights 검색 URL
→ 해당 URL을 복사
→ 새 브라우저 창/탭에서 직접 열기
→ 가격 정상 표시
```

따라서 현재 판단:

```text
검색 조건/URL 생성: 정상
route/date: 정상
gl=kr / curr=KRW: 정상
문제 지점: 처음 자동 검색을 수행한 탭/세션의 결과 로딩 상태
```

## 6. 현재 acceptance — generated URL → fresh new tab

`scripts/google_ui_probe.py`는 다음 순서입니다.

```text
1. native Edge + dedicated profile 실행
2. 첫 탭에서 Google Flights UI 직접 입력
3. 생성된 최종 /travel/flights/search URL 확보
4. 동일 Edge context에서 새 탭 생성
5. 정확히 같은 URL을 fresh navigation
6. Cheapest / More flights 필요 시 적용
7. flight-row scoped KRW 가격만 읽기
8. 실패 시 여러 fresh tab 반복
```

### 6.1 2026-09-04 probe hardening

현재 main 검수에서 acceptance 오판 가능성을 제거했습니다.

- page body 전체의 KRW 최소값 fallback 제거
- `li` / `role=listitem` / `role=button` 중 실제 flight-row 형태만 가격 후보로 인정
- fresh tab에서 결과 shell이 먼저 뜬 뒤 가격이 늦게 채워질 수 있으므로 row 가격을 기본 15초 추가 대기
- `generated_search_url`, `fresh_url`, `price_candidates` 출력 유지
- 실패 진단에 URL / `navigator.webdriver` / language / timezone / Footer Language·Location·Currency 포함
- screenshot / body text / HTML artifact 유지
- pure helper unit test 추가

아직 사용자 Windows에서 이 hardening 버전의 live acceptance 결과는 **미확인**입니다.

성공 기준:

```text
=== SUMMARY ===
fresh_tab_attempt=N
ui_lowest=... KRW
acceptance=PRICE_VISIBLE_AFTER_FRESH_TAB
```

## 7. 현재 중요한 경계

`src/flight_bot/providers.py` runtime Provider는 아직 기존 v0.2 `tfs URL + Playwright` 구현입니다.

**fresh-new-tab acceptance가 실제 가격을 반환하기 전에는 runtime Provider를 교체하지 않습니다.**

현재 상태:

```text
Bot Core: usable
DB/latch: usable
Windows/Linux unit CI: usable
Runtime Google price Provider: migration pending
Generated-URL fresh-tab probe: current acceptance candidate
```

## 8. CI 상태/정책

2026-09-04 기준 이전 HEAD `8621a40`의 GitHub Actions run `33838752221`은 완료 `success`였습니다.

- `unit-linux`: success
- `unit-windows`: success
- hosted `cjj-tpe-ui-diagnostic`: push에서는 skipped

기존 manual diagnostic job은 Windows-visible 전용 probe를 Ubuntu/headless에서 실행하도록 되어 있어 실제 `workflow_dispatch` 시 유효한 acceptance가 될 수 없었습니다. 이 job은 제거했고, 실제 Google Flights acceptance는 사용자 Windows의 `02-live-cjj-tpe-visible.cmd`로만 수행합니다.

## 9. fresh tab도 자동화에서 실패하면 다음 분기

사용자가 동일 URL을 수동 새 창에서 열면 가격이 보이는데 `context.new_page()`에서는 계속 `Price unavailable`이면, 차이는 URL이 아니라 **자동화가 붙어 있는 browser context**입니다.

그 경우 다음 Primary 후보는 Playwright를 더 숨기는 방식이 아니라 **일반 사용자 브라우저 안에서 동작하는 browser extension/content-script sidecar**입니다.

```text
일반 Edge/Chrome profile
→ extension이 Google Flights URL을 새 탭으로 열기
→ 실제 DOM에서 가격 읽기
→ localhost flight-bot API로 결과 전달
```

stealth/CAPTCHA/BotGuard 우회를 기본 전략으로 넣지 않습니다.

## 10. acceptance 성공 후

1. runtime Provider를 검증된 방식으로 교체
2. 페이지 전체 min이 아닌 실제 flight row 가격만 비교
3. 최저 출국 후보 → 귀국 후보 → Booking 최종가격 검증
4. observed와 verified를 구분
5. `REQUIRE_VERIFIED_ALERTS=true` 유지
6. fast-flights dependency 제거
7. Docker/Ubuntu 또는 browser-sidecar 운영구조 결정
8. Windows/Linux tests + live acceptance 재검증

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
