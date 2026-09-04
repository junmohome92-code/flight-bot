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

사용자 일반 브라우저에서 같은 조건으로 약 33만 원대 왕복 결과가 관찰됐습니다. 가격은 실시간이므로 특정 숫자를 acceptance 값으로 고정하지 않습니다.

## 4. 이미 거부한 Provider 경로

### SerpApi

브라우저 직접 Google Flights보다 비싸고 저렴한 혼합/별도티켓 스타일 결과가 누락된 사례가 있어 Primary로 복귀시키지 않습니다.

### tfs 직링크 + Playwright

GitHub hosted runner와 사용자 Windows 일반 회선 모두 route/date는 로드했지만 `Price unavailable`이 발생했습니다. 이 경로는 사용하지 않습니다.

### fast-flights 3.1.0 parser

현재 Google payload와 맞지 않아 `IndexError`가 발생했고, RF511/ZE781 등 일부 후보는 `[[], token]` 형태였습니다. 독립 편도 최저가 합도 사용자 일반 브라우저 왕복 최저가와 달랐습니다. 가격 Provider로 사용하지 않습니다.

### punitarani/fli direct service

검증 commit `121d34fea056dc513258958c4262cb5a4cc033c1`. `get_booking_options()` 존재는 확인했으나 CJJ↔TPE는 `Fli returned no round-trip results`였습니다. upstream no-results / BotGuard 관련 제한도 있어 Primary로 채택하지 않습니다.

## 5. 실제 Google Flights UI 실험 결과

### 5.1 첫 자동 검색 탭

Playwright-launched Edge와 native Edge + CDP attach 모두 첫 검색 결과 탭에서는 `Price unavailable`이 확인됐습니다.

### 5.2 generated URL을 fresh tab으로 다시 열면 가격 렌더링

사용자가 자동화가 만든 검색 URL을 새 창/탭에서 직접 열었을 때 가격이 정상 표시됐습니다. 이후 자동 `context.new_page()`에서도 fresh navigation 결과 실제 KRW flight-row 가격이 렌더링되는 사례가 확인됐습니다.

사용자 Windows 실측 예:

```text
price_candidates=2
887,003 KRW
1,270,502 KRW
navigator_webdriver=False
footer_location=South Korea
footer_currency=KRW
```

따라서 generated search URL의 fresh navigation 자체는 유효한 방향입니다.

### 5.3 추천 탭을 최저가로 오인한 문제 — 수정

Google Flights UI에는 `추천` / `최저가` 탭이 따로 있고 사용자 일반 브라우저에서는 `최저가 ₩338,121부터`와 약 33만 원대 row가 실제 표시됐습니다.

기존 probe는 영문 `Cheapest` exact text만 찾는 문제가 있어 추천 탭 가격을 읽고도 성공으로 판정할 수 있었습니다. 이후 다음을 수정했습니다.

- `Cheapest` / `최저가` 모두 탐색
- `View more flights` / `항공편 더보기` 모두 탐색
- 탭 클릭 여부 및 `aria-selected` 확인
- 탭의 advertised cheapest price 기록
- body 전체 min 금지
- flight-row scoped price만 허용
- advertised cheapest와 parsed row lowest 불일치 시 acceptance 거부

### 5.4 최신 사용자 Windows 결과 — Cheapest 클릭 직후 다시 Price unavailable

2026-09-04 최신 사용자 테스트:

```text
cheapest_tab_found=True
cheapest_tab_text=Cheapest ... ₩338,121
cheapest_advertised=338,121 KRW
cheapest_tab_clicked=True
cheapest_tab_aria_selected=true
expanded_results_with=View more flights
price_candidates=0
fresh_tab_1_price_unavailable=True
```

동일 결과가 fresh tab 3회에서 반복됐습니다.

즉 **base fresh search tab에서는 가격 렌더링 경험이 있었지만, Cheapest 탭으로 상태 전환한 현재 문서에서는 다시 `Price unavailable`이 발생**합니다. 이 결과는 parser 실패로 단정할 수 없습니다. 해당 문서에 실제 row price가 없기 때문입니다.

## 6. GitHub hosted Windows 실테스트

사용자 요청에 따라 GitHub Actions `windows-latest`에서 실제 native Edge + CDP 실험을 수행했습니다.

### 6.1 landing UI test

첫 실행은 Windows stdout cp1252 때문에 한글 로그에서 실패해 UTF-8 환경을 추가했습니다.

두 번째 실행에서 Google Flights 정상 landing page와 `Where from?` input이 screenshot/HTML에 존재했으나, `domcontentloaded` 직후 selector 검사 race로 origin input을 너무 일찍 확인해 실패했습니다. hosted artifact를 직접 확인해 입력창 자체는 정상 존재함을 검증했습니다.

### 6.2 generated URL 직접 open

사용자 로그의 generated search URL을 GitHub hosted Edge에서 직접 열어 첫 화면 입력 단계를 우회했습니다.

```text
cheapest_tab_found=True
cheapest_tab_clicked=True
price_unavailable=True
parser_price_candidates=0
price_node_dump_count=2
```

`₩`가 포함된 2개 DOM node는 실제 flight row가 아니라 `<script>` 데이터였습니다. 따라서 hosted runner에서는 parser가 가격을 놓친 것이 아니라 **실제 화면 가격 row가 내려오지 않았습니다.**

### 6.3 Cheapest transition URL을 다시 fresh open

Cheapest 클릭 후 생성된 `tfu=...` URL을 또 다른 새 탭에서 fresh navigation하는 실험도 GitHub hosted Windows에서 수행했습니다.

```text
cheapest_transition_price_unavailable=True
cheapest_fresh_price_unavailable=True
price_candidates=0
```

GitHub 데이터센터 환경에서는 두 번째 fresh navigation으로도 가격이 살아나지 않았습니다. 따라서 GitHub hosted runner는 실제 가격 acceptance 환경으로 사용할 수 없고, 최종 live 판정은 사용자 일반 회선 Windows에서 해야 합니다.

## 7. 현재 acceptance — Cheapest transition URL을 두 번째 fresh tab으로 재오픈

새 probe: `scripts/google_cheapest_fresh_probe.py`

Windows `02-live-cjj-tpe-visible.cmd`는 이제 이 probe를 실행합니다.

```text
INITIAL TAB
Google Flights UI 입력
→ generated_search_url 확보

BASE FRESH TAB
→ generated_search_url fresh navigation
→ Cheapest / 최저가 클릭
→ 클릭 후 생성된 tfu URL 확보

CHEAPEST FRESH TAB
→ tfu URL을 ANOTHER new page에서 fresh navigation
→ More flights 필요 시 확장
→ flight-row scoped KRW 가격 수집
→ advertised cheapest와 row lowest 일치 검증
```

성공 기준:

```text
cheapest_transition_url=...&tfu=...
=== CHEAPEST URL FRESH TAB N ===
price_candidates=...
cheapest_price_match=True

=== SUMMARY ===
fresh_tab_attempt=N
ui_lowest=... KRW
acceptance=CHEAPEST_PRICE_VISIBLE_AFTER_SECOND_FRESH_TAB
```

실패 시 `cheapest-transition-N.*`, `cheapest-fresh-N.*`, `second-fresh-final-error.*` artifact를 확인합니다.

## 8. 현재 중요한 경계

`src/flight_bot/providers.py` runtime Provider는 아직 기존 v0.2 `tfs URL + Playwright` 구현입니다.

**`CHEAPEST_PRICE_VISIBLE_AFTER_SECOND_FRESH_TAB`이 사용자 Windows에서 확인되기 전에는 runtime Provider를 교체하지 않습니다.**

현재 상태:

```text
Bot Core: usable
DB/latch: usable
Windows/Linux unit CI: usable
Base fresh-tab price rendering: user Windows에서 확인됨
Cheapest current-document transition: Price unavailable 재현
Second-fresh Cheapest URL: current acceptance gate
Runtime Google price Provider: migration pending
```

## 9. CI 상태/정책

일반 blocking CI는 다음만 유지합니다.

- Linux Python 3.12 install / compileall / pytest
- Windows Python 3.12 install / compileall / pytest
- Windows Playwright Chromium launch

실제 Google Flights live acceptance는 GitHub hosted runner의 성공 조건으로 사용하지 않습니다. 이번 hosted live test용 임시 job은 실험 종료 후 제거했습니다.

## 10. second-fresh도 사용자 Windows에서 실패하면

사용자 일반 Edge/Chrome에서는 약 33만 원대 최저가 row가 정상 표시되는데, 자동화된 second-fresh tab에서도 계속 `Price unavailable`이면 차이는 URL이 아니라 **CDP/자동화가 붙어 있는 browser context**일 가능성이 높습니다.

그 경우 Playwright stealth/BotGuard 우회를 무작정 추가하지 않고 다음 Primary 후보를 검토합니다.

```text
일반 사용자 Edge/Chrome
→ browser extension/content script가 Google Flights DOM을 읽음
→ localhost flight-bot API에 observed row 데이터 전달
```

## 11. acceptance 성공 후

1. runtime Provider를 검증된 방식으로 교체
2. 페이지 전체 min이 아닌 실제 flight row 가격만 비교
3. 최저 출국 후보 클릭
4. 귀국 후보 선택
5. Booking / final price 단계 검증
6. 표시 가격은 `observed`, Booking 검증 가격만 `verified`
7. `REQUIRE_VERIFIED_ALERTS=true` 유지
8. fast-flights dependency 제거
9. Docker/Ubuntu 또는 browser-sidecar 운영구조 결정
10. Windows/Linux tests + live acceptance 재검증

## 12. 절대 되돌리지 말 것

- SerpApi를 근거 없이 Primary로 복원하지 말 것
- `fast-flights.get_flights()`를 가격 source로 복원하지 말 것
- Fli direct API를 CJJ↔TPE 실가격 source로 다시 채택하지 말 것
- Google 가격이 없을 때 다른 숫자를 추정/합성하지 말 것
- 수하물 미확인을 `없음`으로 바꾸지 말 것
