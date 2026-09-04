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

사용자 일반 브라우저에서 같은 조건으로 약 33만 원대 왕복 결과가 실제 표시됐습니다. 가격은 실시간이므로 특정 숫자를 acceptance 값으로 고정하지 않습니다.

## 4. 이미 거부한 Provider 경로

### SerpApi

브라우저 직접 Google Flights보다 비싸고 저렴한 혼합/별도티켓 스타일 결과가 누락된 사례가 있어 Primary로 복귀시키지 않습니다.

### 기존 tfs 직링크 + Playwright

GitHub hosted runner와 사용자 Windows 일반 회선 모두 route/date는 로드했지만 `Price unavailable`이 발생했습니다. Primary로 복원하지 않습니다.

### fast-flights 3.1.0 parser

현재 Google payload와 맞지 않아 `IndexError`가 발생했고 일부 후보는 실제 가격 대신 다음 단계 token 형태였습니다. 가격 Provider로 사용하지 않습니다.

### punitarani/fli direct service

검증 commit `121d34fea056dc513258958c4262cb5a4cc033c1`. CJJ↔TPE는 `Fli returned no round-trip results`였습니다. Primary로 채택하지 않습니다.

## 5. 실제 Google Flights UI 실험 결과

### 5.1 첫 자동 검색 문서

Playwright-launched Edge와 native Edge + CDP attach 모두 첫 검색 결과 문서에서는 `Price unavailable`이 확인됐습니다.

### 5.2 generated URL fresh navigation은 부분 성공

자동화가 만든 search URL을 사용자가 일반 브라우저 새 창에서 열면 가격이 정상 표시됐습니다. 자동 `context.new_page()`에서도 한 번은 실제 KRW flight-row 가격이 렌더링됐습니다.

예:

```text
price_candidates=2
887,003 KRW
1,270,502 KRW
navigator_webdriver=False
footer_location=South Korea
footer_currency=KRW
```

따라서 fresh navigation 자체가 무의미한 것은 아닙니다.

### 5.3 추천/최저가 탭 구분 문제 — 수정됨

Google Flights에는 `추천` / `최저가` 탭이 따로 있습니다. 기존 probe가 추천 탭 가격을 최저가로 오인할 수 있던 문제는 수정했습니다.

현재는:

- `Cheapest` / `최저가` 모두 탐색
- 탭 클릭 및 `aria-selected` 확인
- advertised cheapest 기록
- body 전체 min 금지
- flight-row scoped price만 허용
- advertised cheapest와 row lowest 불일치 시 acceptance 거부

### 5.4 사용자 Windows: Cheapest 클릭 후 3회 모두 Price unavailable

사용자 실측:

```text
cheapest_tab_found=True
cheapest_advertised=338,121 KRW
cheapest_tab_clicked=True
cheapest_tab_aria_selected=true
cheapest_transition_price_unavailable=True
```

Cheapest 클릭 후 생성된 `tfu` URL을 또 다른 fresh tab에서 3회 다시 열어도:

```text
cheapest_fresh_price_unavailable=True
price_candidates=0
cheapest_price_match=False
```

따라서 **second-fresh 전략은 사용자 Windows에서도 실패로 종료**합니다. URL/reload/new-tab 반복은 더 진행하지 않습니다.

### 5.5 새 핵심 관찰: 가격이 잠깐 보였다가 사라짐

사용자가 Chromium/Edge fresh 문서 로딩 과정에서 **가격이 처음에는 화면에 나타났다가 곧 사라지고 `Price unavailable` 상태로 바뀌는 현상**을 직접 확인했습니다.

이 관찰은 다음 가설을 강하게 만듭니다.

```text
초기 DOM/초기 렌더
→ 실제 가격 row가 잠깐 존재
→ Google 후속 JS 상태 갱신
→ Price unavailable로 교체
```

따라서 현재 gate는 완성된 DOM을 늦게 읽는 방식이 아니라 **사라지기 전 transient flight-row DOM을 보존하는 것**입니다.

## 6. GitHub hosted Windows 실테스트

사용자 요청으로 GitHub Actions `windows-latest`에서 native Edge live 실험을 직접 수행했습니다.

- landing page 정상 로드 확인
- generated URL 직접 open 성공
- Cheapest 탐지/클릭 성공
- hosted 환경에서는 `Price unavailable=True`
- 실제 flight-row KRW DOM node 0개
- Cheapest `tfu` URL을 또 다른 fresh tab에서 열어도 `Price unavailable=True`

따라서 GitHub 데이터센터 runner는 실제 가격 acceptance 환경으로 쓸 수 없습니다. live 최종 판정은 사용자 일반 회선 Windows에서 수행합니다.

## 7. 현재 acceptance — transient DOM capture

새 probe:

```text
scripts/google_transient_price_probe.py
```

Windows `02-live-cjj-tpe-visible.cmd`는 이 probe를 실행합니다.

핵심 방식:

```text
native Edge + 전용 profile
→ about:blank로 빠르게 시작
→ fixed acceptance의 canonical generated URL 재사용
→ Google page script보다 먼저 MutationObserver 설치
→ DOM에 잠깐이라도 나타난 ₩ price element 감시
→ price element의 ancestor에서 실제 flight-row shape 확인
→ price / airline / times / route / stops / row text를 JS 메모리에 보존
→ Google이 DOM을 Price unavailable로 바꿔도 보존된 snapshot 유지
```

중요:

- body 전체 KRW 최소값 fallback 없음
- flight-row 형태가 확인된 transient price만 인정
- `Cheapest` advertised price보다 비싼 candidate는 acceptance로 인정하지 않음
- transient observed price는 **booking verified가 아님**
- 성공해도 `REQUIRE_VERIFIED_ALERTS=true`를 해제하지 않음

성공 기준:

```text
transition_transient_1=338,xxx KRW | phase=cheapest-transition | ...
또는
cheapest_fresh_transient_1=338,xxx KRW | phase=cheapest-fresh | ...

=== SUMMARY ===
transient_lowest=...
cheapest_advertised=...
observed=TRANSIENT_FLIGHT_ROW_CAPTURED
verified=False
acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE
```

artifact:

```text
artifacts/google-ui-win/*-transient.json
artifacts/google-ui-win/*.png
artifacts/google-ui-win/*.txt
artifacts/google-ui-win/*.html
```

## 8. 테스트 속도 개선

사용자가 browser window가 너무 늦게 뜬다고 보고했습니다.

현재 Windows acceptance는 이 고정 시나리오에서 이미 UI가 생성한 canonical search URL을 재사용하므로 매번 공항/날짜를 다시 입력하지 않습니다. Edge는 `about:blank`에서 시작합니다.

이 최적화는 **acceptance diagnostic 전용**입니다. production Provider는 여전히 사용자 검색조건에 따라 동적으로 search URL을 생성해야 합니다.

## 9. 현재 중요한 경계

`src/flight_bot/providers.py` runtime Provider는 아직 기존 v0.2 tfs URL + Playwright 구현입니다.

**transient observed-price gate가 사용자 Windows에서 실제 flight-row context와 함께 통과하기 전에는 runtime Provider를 교체하지 않습니다.**

현재 상태:

```text
Bot Core: usable
DB/latch: usable
Windows/Linux unit CI: usable
Base fresh-tab price rendering: user Windows에서 한 차례 확인
Cheapest current document: Price unavailable
Second-fresh Cheapest URL: 사용자 Windows에서도 실패 종료
Transient DOM capture: ACTIVE GATE
Runtime Google price Provider: migration pending
```

## 10. transient capture 결과 분기

### A. transient flight-row 가격 캡처 성공

`observed` 가격 획득 방식으로는 성립합니다. 다음은 같은 짧은 시간 안에 후보 row를 선택할 수 있는지 검증하고, returning/Booking 단계로 내려가 실제 판매 가능 total을 확인합니다.

### B. 화면에는 가격이 보였다가 사라지는데 transient capture는 0건

DOM이 아니라 다른 렌더 계층 또는 probe 주입 시점 문제일 수 있습니다. artifact/초기 response를 분석하고, 필요하면 일반 Edge/Chrome extension/content-script 방식으로 전환합니다.

### C. 일반 Edge에서는 정상인데 CDP context에서 transient 가격 자체가 전혀 생기지 않음

URL 실험을 더 반복하지 않고 다음 Primary 후보로 전환합니다.

```text
일반 사용자 Edge/Chrome
→ extension/content script가 Google Flights 실제 row DOM 읽기
→ localhost flight-bot API로 전달
```

stealth/BotGuard 우회를 기본 전략으로 하지 않습니다.

## 11. acceptance 성공 후

1. runtime Provider를 검증된 방식으로 교체
2. actual flight-row observed price 추출
3. 최저 출국 후보 선택
4. returning flights 이동
5. 귀국 후보 선택
6. Booking / final total 검증
7. observed / verified 분리
8. `REQUIRE_VERIFIED_ALERTS=true` 유지
9. fast-flights dependency 제거
10. Docker/Ubuntu 또는 browser-sidecar 운영구조 결정
11. Windows/Linux tests + live acceptance 재검증

## 12. 절대 되돌리지 말 것

- SerpApi를 근거 없이 Primary로 복원하지 말 것
- `fast-flights.get_flights()`를 가격 source로 복원하지 말 것
- Fli direct API를 CJJ↔TPE 실가격 source로 다시 채택하지 말 것
- Google 가격이 없을 때 다른 숫자를 추정/합성하지 말 것
- 수하물 미확인을 `없음`으로 바꾸지 말 것
