# Flight Bot — NEW CHAT HANDOFF

이 문서는 새 ChatGPT 채팅에서 작업을 바로 이어가기 위한 인계서입니다.

## 1. 시작할 때 먼저 읽을 파일

```text
README.md
docs/PROJECT_STATUS.md
docs/HANDOFF_NEW_CHAT.md
```

기준 브랜치는 `main`입니다.

## 2. 현재 한 줄 요약

**봇 Core는 살아 있고 Google Flights base fresh 문서에서 실제 KRW 가격이 렌더링된 사례도 있습니다. 하지만 Cheapest/최저가 상태 전환 후에는 `Price unavailable`이 되고, second-fresh URL도 사용자 Windows에서 3회 모두 실패했습니다. 최신 핵심 관찰은 “가격이 잠깐 보였다가 사라진다”이며, 현재 gate는 사라지기 전 transient flight-row DOM을 캡처하는 것입니다.**

SerpApi / fast-flights parser / Fli direct API / 기존 direct tfs 반복은 금지합니다.

## 3. 기준 acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate style results allowed
```

사용자 일반 Google Flights에서는 약 33만 원대 왕복 결과가 실제 표시됐습니다. 실시간 값이므로 특정 숫자를 고정 acceptance로 사용하지 않습니다.

## 4. 핵심 실험 결과

### generated URL fresh navigation

자동화가 만든 search URL을 사용자가 일반 브라우저 새 창에서 열면 가격이 정상 표시됐고, 자동 `context.new_page()`에서도 한 번은 실제 flight-row KRW 가격이 수집됐습니다.

```text
price_candidates=2
887,003 KRW
1,270,502 KRW
navigator_webdriver=False
footer_location=South Korea
footer_currency=KRW
```

### 추천/최저가 오인 문제

`Cheapest` / `최저가`를 모두 인식하도록 수정했고 advertised cheapest와 row lowest를 교차검증합니다.

사용자 Windows에서는:

```text
cheapest_tab_found=True
cheapest_advertised=338,121 KRW
cheapest_tab_clicked=True
cheapest_tab_aria_selected=true
```

까지 정상입니다.

### second-fresh 전략 — 종료

Cheapest 클릭 후 생긴 `tfu` URL을 또 다른 fresh tab에서 3회 열었지만 모두:

```text
cheapest_fresh_price_unavailable=True
price_candidates=0
cheapest_price_match=False
```

였습니다. 따라서 URL/reload/new-tab을 더 반복하지 않습니다.

### 가장 중요한 최신 관찰

사용자가 Chromium/Edge 로딩 중 **가격이 처음에는 잠깐 보였다가 사라지는 것**을 직접 확인했습니다.

즉 현재 강한 가설:

```text
초기 DOM/렌더에 실제 가격 row 존재
→ Google 후속 JS 상태 갱신
→ Price unavailable로 교체
```

## 5. GitHub hosted Windows 실제 테스트

실제 `windows-latest` native Edge에서 다음을 검증했습니다.

- Google Flights landing 정상 로드
- generated URL 직접 open 성공
- Cheapest 탐지/클릭 성공
- hosted 환경에서는 실제 flight-row 가격 DOM이 내려오지 않음
- Cheapest `tfu` URL second-fresh도 `Price unavailable`

따라서 GitHub 데이터센터 runner는 live price acceptance 환경으로 사용할 수 없습니다. 일반 compile/test CI만 유지합니다.

## 6. 현재 acceptance script

```text
scripts/google_transient_price_probe.py
```

Windows:

```text
flight-bot - test win/02-live-cjj-tpe-visible.cmd
```

이제 `02`는 기존 two-stage probe가 아니라 transient probe를 실행합니다.

흐름:

```text
native Edge + dedicated profile
→ about:blank로 시작
→ fixed acceptance canonical generated URL 재사용
→ Google page script보다 먼저 MutationObserver 설치
→ DOM mutation에서 ₩ price element 즉시 감시
→ ancestor가 실제 flight row인지 확인
→ price/airline/times/route/stops/row text snapshot 저장
→ 이후 Google이 Price unavailable로 바꿔도 snapshot 유지
```

고정 acceptance URL을 재사용하는 것은 테스트 속도 개선용입니다. production search는 사용자 조건에 맞춰 동적으로 URL을 생성해야 합니다.

## 7. 다음 사용자 테스트 성공 기준

```text
transition_transient_count=...
transition_transient_1=338,xxx KRW | phase=cheapest-transition | ...
```

또는:

```text
cheapest_fresh_transient_count=...
cheapest_fresh_transient_1=338,xxx KRW | phase=cheapest-fresh | ...
```

최종:

```text
=== SUMMARY ===
transient_lowest=...
cheapest_advertised=...
observed=TRANSIENT_FLIGHT_ROW_CAPTURED
verified=False
acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE
```

이 성공은 **observed price만 증명**합니다. Booking 검증 가격은 아닙니다.

## 8. 결과 분기

### A. transient capture 성공

다음은 사라지기 전 해당 row를 선택할 수 있는지 검증합니다. 이후 returning flights → 귀국 후보 → Booking/final total로 내려가 verified price를 확인합니다.

### B. 화면에는 가격이 보였다가 사라지는데 transient 0건

초기 DOM artifact/주입 시점을 분석합니다. DOM capture가 구조적으로 불안정하면 일반 사용자 Edge/Chrome extension/content-script sidecar로 전환합니다.

### C. 일반 브라우저만 정상이고 CDP context에서는 transient price 자체가 전혀 없음

Playwright 새 탭 실험을 더 반복하지 않고 extension/content-script sidecar를 Primary 후보로 전환합니다.

```text
일반 Edge/Chrome
→ extension/content script가 실제 Google Flights row 읽기
→ localhost flight-bot으로 observed data 전달
```

stealth/BotGuard 우회를 기본 전략으로 하지 않습니다.

## 9. runtime 주의

현재 `src/flight_bot/providers.py`는 여전히 기존 v0.2 tfs URL + Playwright Provider입니다.

**transient observed gate 통과 전에는 runtime migration을 완료했다고 말하지 않습니다.**

`REQUIRE_VERIFIED_ALERTS=true`는 계속 유지합니다.

## 10. CI

```text
Linux Python 3.12 → install → compileall → pytest
Windows Python 3.12 → install → compileall → pytest → Playwright Chromium launch
```

Google live price는 hosted CI blocking gate가 아닙니다.

## 11. 반복 금지

- SerpApi Primary 복원 금지
- fast-flights parser 가격 source 복원 금지
- Fli direct API 재채택 금지
- URL reload/new-tab 반복 실험 금지
- 가격/수하물 추정 금지
- 위탁수하물 미확인 = `정보 확인 불가`

## 12. 유지 요구사항

- 슬롯 정확히 3개
- pause 슬롯 점유 / delete 해제
- target_price 기준 알림
- ARMED → 하향 돌파 1회 → ALERTED → 위로 복귀 시 re-arm
- 동일 below-target 구간 반복 알림 금지
- notifier가 Provider 호출 금지
- SQLite WAL
- 검색 순차 실행
- `REQUIRE_VERIFIED_ALERTS=true`
