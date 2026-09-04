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

**봇 Core는 살아 있고 Google Flights 실가격 Provider만 migration gate 진행 중입니다.**

SerpApi / fast-flights parser / Fli direct API / tfs 직링크 방식은 이미 실패 근거가 있으므로 반복하지 않습니다.

현재 gate는 **Google Flights UI로 검색 URL 생성 → 동일 URL을 새 탭에서 fresh open → 가격 읽기**입니다.

## 3. 기준 acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate style results allowed
```

사용자 일반 브라우저에서는 같은 조건으로 약 33만 원대 왕복 결과가 관찰된 적이 있습니다. 실시간 값이므로 숫자를 고정 acceptance로 사용하지 않습니다.

## 4. 현재까지 핵심 실험 결과

### Playwright-launched Edge

UI 첫 화면에서 직접 검색했지만 `Price unavailable`.

### Native Edge + CDP attach

Windows `msedge.exe`를 native process로 실행하고 Playwright는 CDP attach만 해도 자동검색 결과 탭은 `Price unavailable`.

`gl=kr`, `curr=KRW`, route/date는 정상이라 locale 누락은 직접 원인이 아닙니다.

### 가장 중요한 사용자 관찰

사용자가 자동화 브라우저에서 만들어진 **검색 결과 URL을 복사해서 새 창/새 탭에서 직접 열자 가격이 정상 표시**됐습니다.

따라서 현재 판단:

```text
URL/검색조건 생성 = 정상
문제 = 첫 자동검색 탭 또는 자동화 context에서의 결과 로딩 상태
```

이 관찰이 기존 retry 실험보다 우선합니다.

## 5. 현재 코드

`scripts/google_ui_probe.py`는 이제 다음 순서입니다.

```text
native Edge + dedicated profile
→ 첫 탭에서 Google Flights UI 직접 검색
→ generated_search_url 출력
→ 동일 context에 NEW TAB 생성
→ generated_search_url을 그대로 goto
→ 새 탭에서 flight-row KRW 가격 읽기
→ 필요 시 여러 fresh tab 반복
```

이전의 "같은 탭 재검색"과 다릅니다. 사용자 성공 동작을 그대로 자동화하는 테스트입니다.

## 6. 사용자가 다음에 할 작업

최신 ZIP 또는 `git pull` 후:

```text
flight-bot - test win
└─ 02-live-cjj-tpe-visible.cmd
```

`.venv-win`이 이미 있으면 01은 생략 가능합니다.

성공 시:

```text
generated_search_url=...
=== FRESH TAB ATTEMPT N ===
price_candidates=...
=== SUMMARY ===
fresh_tab_attempt=N
ui_lowest=... KRW
acceptance=PRICE_VISIBLE_AFTER_FRESH_TAB
```

실패 시 `generator-tab`, `fresh-tab-N`, `final-error` artifact를 확인합니다.

## 7. 결과 분기

### A. `PRICE_VISIBLE_AFTER_FRESH_TAB`

이 동작을 runtime Provider 설계에 반영합니다.

1. UI로 canonical search URL 생성 또는 안정적으로 재사용
2. 가격 수집은 fresh tab에서 수행
3. 페이지 전체 min이 아니라 실제 flight row 가격만 비교
4. 최저 출국 후보 → 귀국 후보 → Booking 최종가격 검증
5. `REQUIRE_VERIFIED_ALERTS=true` 유지
6. fast-flights 제거
7. Docker/Ubuntu 운영 가능성 검증
8. tests/docs 갱신

### B. 사용자가 수동 새 창에서는 가격이 보이지만 자동 `context.new_page()`에서는 계속 `Price unavailable`

이 경우 차이는 URL이 아니라 **Playwright/CDP가 붙어 있는 browser context**로 봅니다.

다음 Primary 후보는 stealth/BotGuard 우회가 아니라 일반 사용자 브라우저 안에서 동작하는 extension/content-script sidecar입니다.

```text
일반 Edge/Chrome profile
→ extension이 Google Flights URL open
→ 실제 DOM 가격 읽기
→ localhost flight-bot API로 전달
```

### C. fresh tab에서 가격은 보이는데 parser가 0건

Provider 방향은 맞고 selector 문제입니다. `fresh-tab-N.html/txt` 기준으로 row-scoped selector만 수정합니다.

## 8. 이미 확인한 실패 경로 — 반복 금지

- SerpApi: 브라우저 대비 비싼 결과 / 저렴한 혼합·별도티켓 누락 사례
- tfs 직링크 + Playwright: hosted + Windows 모두 `Price unavailable`
- fast-flights 3.1: parser `IndexError`, 일부 가격 대신 token
- Fli direct API commit `121d34f...`: CJJ↔TPE no-results; upstream no-results/BotGuard limitations

## 9. 현재 runtime 주의

현재 `src/flight_bot/providers.py`는 아직 v0.2 tfs URL 기반 코드입니다.

**fresh-tab acceptance 성공 전에는 운영 Provider 완료라고 말하면 안 됩니다.**

```text
Core / DB / latch / channels: 구현됨
unit CI: 구현됨
real Google price acceptance: 진행 중
runtime Provider migration: acceptance 뒤에 진행
```

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

## 11. 새 채팅 시작용 프롬프트

```text
Flight Bot 작업을 이어가자.
repo: junmohome92-code/flight-bot
branch: main

먼저 README.md, docs/PROJECT_STATUS.md, docs/HANDOFF_NEW_CHAT.md를 읽어.
기존 SerpApi / fast-flights parser / Fli direct API / tfs 직링크 실패 실험은 반복하지 마.

가장 중요한 최신 관찰:
자동화가 만든 Google Flights 검색 결과 URL을 사용자가 복사해서 새 창/새 탭에서 직접 열면 가격이 정상 표시됐다.

현재 gate는 scripts/google_ui_probe.py의 generated URL → fresh NEW TAB 자동 재오픈 테스트다.
내가 02-live-cjj-tpe-visible.cmd 결과를 줄 테니 그 결과에 따라 분기해.

fresh tab에서 가격이 나오면 runtime Provider로 승격하고 row-scoped price → return 선택 → Booking 검증 → fast-flights 제거 → Docker/docs/tests까지 진행해.

수동 새 창은 되는데 자동 context.new_page는 계속 Price unavailable이면 Playwright를 더 숨기려 하지 말고 일반 사용자 브라우저 extension/content-script sidecar를 다음 Primary 후보로 검토해.
가격/수하물은 절대 추정하지 말고 fail-closed 유지해.
```
