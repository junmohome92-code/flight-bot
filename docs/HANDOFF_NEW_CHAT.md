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

**봇 Core는 살아 있고 Google Flights fresh-tab 가격 렌더링은 성공했으며, 현재 gate는 한국어 `최저가` 탭을 실제로 선택해 약 33만 원대 최저 row를 읽는 단계입니다.**

SerpApi / fast-flights parser / Fli direct API / tfs 직링크 방식은 이미 실패 근거가 있으므로 반복하지 않습니다.

## 3. 기준 acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate style results allowed
```

사용자 일반 브라우저에서는 같은 조건으로 약 33만 원대 왕복 결과가 관찰됐습니다. 실시간 값이므로 특정 숫자를 고정 acceptance로 사용하지 않습니다.

## 4. 핵심 실험 결과

### 첫 자동 검색 탭

Playwright-launched Edge와 native Edge + CDP attach 모두 첫 자동 검색 탭에서는 `Price unavailable`이 발생했습니다.

### 수동 fresh window

자동화가 만든 search URL을 사용자가 새 창/새 탭에서 직접 열면 가격이 정상 표시됐습니다.

### 자동 fresh tab — 가격 렌더링 성공

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

따라서 **동일 URL을 `context.new_page()`에서 fresh navigation하면 자동화된 Edge에서도 실제 KRW flight-row 가격이 렌더링될 수 있음이 확인됐습니다.**

하지만 사용자가 첨부한 화면에는 `추천`과 `최저가 ₩338,121부터` 탭이 따로 있었고, 기존 probe는 `Cheapest` 영문 exact text만 찾아 한국어 `최저가` 탭을 클릭하지 못했습니다. 그 결과 추천 탭 가격을 읽고도 `PRICE_VISIBLE_AFTER_FRESH_TAB`을 출력했습니다.

이전 출력은 **render gate 성공**으로만 인정하며, 실제 최저가 acceptance 성공으로 보지 않습니다.

## 5. 현재 코드

`scripts/google_ui_probe.py`는 이제 다음 순서입니다.

```text
native Edge + dedicated profile
→ 첫 탭에서 Google Flights UI 직접 검색
→ generated_search_url 출력
→ 동일 context NEW TAB
→ generated_search_url fresh goto
→ Cheapest / 최저가 영어·한국어 selector 탐색
→ 탭 클릭 여부 기록
→ 탭에 표시된 광고 최저가(예: ₩338,121부터) 추출
→ More flights / 항공편 더보기 필요 시 적용
→ row-scoped KRW 가격 수집
→ advertised cheapest보다 row parser 최저가가 비싸면 acceptance 거부
```

추가 hardening:

- body 전체 KRW minimum fallback 없음
- price element에서 ancestor를 최대 12단계 올라가 flight-row shape를 찾음
- visible KRW text도 flight-row ancestor가 확인된 경우에만 수집
- 한국어 `최저가`, `항공편 더보기`, 결과 section marker 지원
- 기본 15초 row-price wait
- Footer Language/Location/Currency + navigator.webdriver/language/timezone + URL 진단
- `generator-tab`, `fresh-tab-N`, error screenshot/txt/html artifact 유지

runtime `src/flight_bot/providers.py`는 아직 기존 tfs URL Provider입니다. **아직 runtime migration 하지 않았습니다.**

## 6. 사용자가 다음에 할 작업

최신 `main`을 받은 뒤:

```text
flight-bot - test win
└─ 02-live-cjj-tpe-visible.cmd
```

`.venv-win`이 이미 있으면 01은 생략 가능합니다.

이번 성공 기준은 다음입니다.

```text
generated_search_url=...

=== FRESH TAB ATTEMPT N ===
fresh_url=...
cheapest_tab_found=True
cheapest_tab_text=최저가 ...
cheapest_advertised=... KRW
cheapest_tab_clicked=True
price_candidates=...
#1 ... KRW | 항공사/시간/경유정보
render_gate=PRICE_VISIBLE_AFTER_FRESH_TAB
cheapest_tab_ready=True
cheapest_price_match=True
cheapest_row_lowest=... KRW

=== SUMMARY ===
fresh_tab_attempt=N
ui_lowest=... KRW
acceptance=CHEAPEST_PRICE_VISIBLE_AFTER_FRESH_TAB
```

`cheapest_advertised`가 약 33만 원인데 `cheapest_row_lowest`가 40만/80만 원대로 나오면 selector 또는 row parser가 아직 잘못된 것이므로 acceptance는 실패해야 합니다.

## 7. 결과 분기

### A. `CHEAPEST_PRICE_VISIBLE_AFTER_FRESH_TAB`

이때 runtime Provider migration을 시작합니다.

1. fresh-tab browser lifecycle 반영
2. 실제 flight-row scoped observed price
3. 최저 출국 후보 클릭
4. returning flights 이동
5. 귀국 후보 선택
6. Booking / final total 검증
7. observed / verified 분리
8. `REQUIRE_VERIFIED_ALERTS=true` 유지
9. fast-flights 제거
10. Docker/Ubuntu 운영구조 검증
11. tests/docs 갱신

### B. `cheapest_tab_found=False`

`fresh-tab-N.html/txt` 기준으로 한국어/DOM selector를 보강합니다.

### C. `cheapest_tab_clicked=True`인데 `cheapest_price_match=False`

탭 클릭 자체는 됐지만 row parser가 탭의 광고 최저가 row를 놓친 것입니다. price element의 ancestor 구조를 artifact HTML로 분석해 row-scoped parser만 보강합니다.

### D. 다시 `Price unavailable`

동일 URL fresh navigation이 일시적으로 실패한 것입니다. 여러 fresh tab 결과와 세션 진단을 비교합니다. 일반 브라우저만 계속 성공하고 자동 context가 지속 실패할 때만 extension/content-script sidecar를 다시 검토합니다.

## 8. CI

실제 live Google Flights acceptance는 사용자 Windows에서 수행합니다. GitHub 일반 CI는 Linux/Windows Python 3.12 compile/test와 Windows Playwright Chromium launch를 검증합니다.

## 9. 이미 확인한 실패 경로 — 반복 금지

- SerpApi: 브라우저 대비 비싼 결과 / 저렴한 혼합·별도티켓 누락 사례
- tfs 직링크 + Playwright: 첫 자동 탭에서 hosted + Windows `Price unavailable`
- fast-flights 3.1: parser `IndexError`, 일부 가격 대신 token
- Fli direct API commit `121d34f...`: CJJ↔TPE no-results; upstream no-results/BotGuard limitations

## 10. 유지 요구사항

- 슬롯 정확히 3개
- pause 슬롯 점유 / delete 해제
- target_price 기준 알림
- ARMED → 하향 돌파 1회 → ALERTED → 위로 복귀 시 re-arm
- 반복 알림 금지
- notifier가 Provider 호출 금지
- SQLite WAL
- 검색 순차 실행
- 가격/수하물 추정 금지
- 위탁수하물 미확인 = `정보 확인 불가`
