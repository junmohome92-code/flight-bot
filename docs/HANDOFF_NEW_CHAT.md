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

**봇 Core는 살아 있고 base fresh search URL에서 가격 렌더링 사례도 확인됐지만, Cheapest/최저가 클릭으로 현재 문서가 전환되면 다시 `Price unavailable`이 발생합니다. 현재 gate는 Cheapest 클릭 후 생긴 `tfu` URL을 또 다른 fresh tab에서 다시 여는 것입니다.**

SerpApi / fast-flights parser / Fli direct API / 기존 tfs 직링크 방식은 반복하지 않습니다.

## 3. 기준 acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate style results allowed
```

사용자 일반 브라우저에서는 같은 조건으로 약 33만 원대 왕복 결과가 실제 표시됐습니다. 실시간 값이므로 특정 가격을 고정 acceptance로 사용하지 않습니다.

## 4. 핵심 실험 결과

### 첫 자동 검색 탭

Playwright-launched Edge와 native Edge + CDP attach 모두 첫 검색 결과 문서에서는 `Price unavailable`이 발생했습니다.

### generated URL fresh navigation

사용자가 자동화가 만든 search URL을 새 창에서 직접 열면 가격이 정상 표시됐습니다. 이후 자동 `context.new_page()`에서도 실제 KRW flight-row 가격이 렌더링되는 사례가 확인됐습니다.

예:

```text
price_candidates=2
887,003 KRW
1,270,502 KRW
navigator_webdriver=False
footer_location=South Korea
footer_currency=KRW
```

### 추천/최저가 탭 문제

사용자 일반 Google Flights 화면에는 `추천`과 `최저가 ₩338,121부터`가 별도 탭으로 표시됐습니다. 기존 probe가 추천 탭 가격을 최저가로 오인한 문제는 수정했습니다.

현재 `Cheapest` / `최저가` 모두 탐색하고, 탭의 advertised cheapest와 row lowest를 비교합니다.

### 최신 사용자 Windows 결과

```text
cheapest_tab_found=True
cheapest_tab_text=Cheapest ... ₩338,121
cheapest_advertised=338,121 KRW
cheapest_tab_clicked=True
cheapest_tab_aria_selected=true
price_candidates=0
fresh_tab_1_price_unavailable=True
```

3회 모두 같은 계열 결과였습니다.

즉 탭 selector는 이제 맞지만 **Cheapest 클릭으로 전환된 현재 문서에서는 실제 row price가 사라집니다.** parser만의 문제로 보지 않습니다.

## 5. GitHub hosted Windows 실제 테스트

사용자 요청으로 GitHub Actions `windows-latest`에서 native Edge 실험을 직접 수행했습니다.

- landing page는 정상 로드됨
- 초기 selector race 한 건 확인
- 사용자 generated URL 직접 open 성공
- Cheapest 탐지/클릭 성공
- hosted 환경에서는 `Price unavailable=True`
- DOM price-node dump에서 실제 flight-row KRW node는 0개
- Cheapest 클릭 후 `tfu` URL을 또 다른 fresh tab에서 열어도 hosted 환경에서는 `Price unavailable=True`

따라서 GitHub 데이터센터 runner는 live price acceptance 환경으로 사용할 수 없습니다. GitHub에서 parser가 놓친 것이 아니라 실제 화면 row가 내려오지 않는 상태였습니다.

임시 hosted live diagnostic job은 실험 종료 후 제거했고 일반 CI만 유지합니다.

## 6. 현재 코드 / 다음 Windows 테스트

새 acceptance script:

```text
scripts/google_cheapest_fresh_probe.py
```

`flight-bot - test win/02-live-cjj-tpe-visible.cmd`는 이제 이 script를 실행합니다.

흐름:

```text
INITIAL TAB
Google Flights UI 입력
→ generated_search_url

BASE FRESH TAB
generated_search_url fresh open
→ Cheapest / 최저가 클릭
→ cheapest_transition_url (= tfu URL) 확보

CHEAPEST FRESH TAB
cheapest_transition_url을 ANOTHER fresh page에서 open
→ flight-row scoped KRW 가격 수집
→ advertised cheapest와 row lowest 비교
```

성공 기준:

```text
cheapest_transition_url=...&tfu=...

=== CHEAPEST URL FRESH TAB N ===
cheapest_fresh_price_unavailable=False
price_candidates=...
#1 ... KRW | 항공사/시간/경유정보
cheapest_price_match=True

=== SUMMARY ===
fresh_tab_attempt=N
ui_lowest=... KRW
acceptance=CHEAPEST_PRICE_VISIBLE_AFTER_SECOND_FRESH_TAB
```

`.venv-win`이 이미 있으면 01은 다시 실행할 필요 없습니다.

## 7. 결과 분기

### A. `CHEAPEST_PRICE_VISIBLE_AFTER_SECOND_FRESH_TAB`

runtime Provider migration을 시작합니다.

1. 검증된 browser/fresh-tab lifecycle 반영
2. actual flight-row observed price 추출
3. 최저 출국 후보 클릭
4. returning flights 이동
5. 귀국 후보 선택
6. Booking / final total 검증
7. observed / verified 분리
8. `REQUIRE_VERIFIED_ALERTS=true` 유지
9. fast-flights 제거
10. Docker/Ubuntu 운영구조 검증
11. tests/docs 갱신

### B. second-fresh에서도 `Price unavailable`

사용자 일반 Edge/Chrome은 정상인데 CDP가 붙은 두 번째 fresh tab까지 계속 실패하는 상태입니다. 이 경우 URL/reload 실험을 더 반복하지 않고 **일반 사용자 브라우저 extension/content-script sidecar**를 다음 Primary 후보로 평가합니다.

```text
일반 Edge/Chrome
→ extension/content script가 Google Flights 실제 row DOM 읽기
→ localhost flight-bot API로 전달
```

stealth/BotGuard 우회를 기본 전략으로 하지 않습니다.

### C. second-fresh 화면에는 가격이 보이는데 `price_candidates=0`

그때는 실제 parser 문제입니다. `cheapest-fresh-N.html/txt/png`를 기준으로 row-scoped selector만 보강합니다.

## 8. runtime 주의

현재 `src/flight_bot/providers.py`는 여전히 기존 v0.2 tfs URL + Playwright Provider입니다.

**second-fresh live acceptance 성공 전에는 runtime Provider를 교체하거나 완료라고 말하지 않습니다.**

## 9. CI

일반 CI:

```text
Linux Python 3.12 → install → compileall → pytest
Windows Python 3.12 → install → compileall → pytest → Playwright Chromium launch
```

실제 Google Flights live price는 GitHub hosted CI의 blocking gate로 사용하지 않습니다.

## 10. 반복 금지

- SerpApi를 Primary로 복원하지 말 것
- fast-flights parser를 가격 source로 복원하지 말 것
- Fli direct API를 재채택하지 말 것
- 기존 direct tfs URL 접근을 다시 Primary로 쓰지 말 것
- 가격/수하물 추정 금지
- 위탁수하물 미확인 = `정보 확인 불가`

## 11. 유지 요구사항

- 슬롯 정확히 3개
- pause 슬롯 점유 / delete 해제
- target_price 기준 알림
- ARMED → 하향 돌파 1회 → ALERTED → 위로 복귀 시 re-arm
- 동일 below-target 구간 반복 알림 금지
- notifier가 Provider 호출 금지
- SQLite WAL
- 검색 순차 실행
- `REQUIRE_VERIFIED_ALERTS=true`
