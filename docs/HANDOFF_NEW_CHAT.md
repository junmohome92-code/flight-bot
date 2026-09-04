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

**봇 Core는 살아 있고, Google Flights 실가격 Provider만 migration gate 진행 중입니다.**

SerpApi / fast-flights parser / Fli direct API / tfs 직링크 방식은 CJJ↔TPE 실가격 기준으로 이미 문제를 확인했으므로 반복 검증하지 않습니다.

현재 gate는 **Windows native Edge + dedicated persistent profile + Playwright CDP attach + 최대 5회 fresh UI retry**입니다.

## 3. 기준 acceptance

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate style results allowed
```

사용자 일반 브라우저에서는 같은 조건으로 약 33만 원대 왕복 결과가 관찰된 적이 있습니다. 실시간 값이므로 정확한 숫자를 acceptance 조건으로 고정하지 않습니다.

## 4. 현재까지 실험 결과

### Playwright-launched Edge

Google Flights 첫 화면 UI부터 직접 입력했지만:

```text
price_candidates=0
Price unavailable
```

### Native Edge + CDP attach 1회

Windows `msedge.exe`를 직접 실행하고 Playwright는 CDP attach만 했습니다.

실제 사용자 출력:

```text
url_gl_kr=True
url_curr_krw=True
page_mentions_krw=True
page_mentions_korea=True
price_candidates=0
Native Edge UI still shows Price unavailable despite KR/KRW settings
```

따라서 `gl=kr`, `curr=KRW` 누락은 아닙니다.

기존 `page_mentions_korea` 검사는 route 텍스트와 실제 Footer Location을 구분하지 못하므로 현재 코드에서 폐기/보강했습니다.

### 현재 코드

`scripts/google_ui_probe.py`는 이제:

```text
native msedge.exe
→ dedicated persistent profile
→ Playwright CDP attach
→ UI search
→ Footer Language / Location / Currency 출력
→ navigator.webdriver / navigator.language / timezone 출력
→ Price unavailable이면 최대 5회 fresh UI search retry
```

를 수행합니다.

UI 언어는 selector 안정성을 위해 English를 유지합니다. 지역/표시 통화는 독립적으로 `gl=kr`, `curr=KRW`이며 실제 Footer 값으로 검증합니다.

## 5. 사용자가 다음에 할 작업

최신 ZIP 또는 `git pull` 후:

```text
flight-bot - test win
└─ 02-live-cjj-tpe-visible.cmd
```

`.venv-win`이 이미 있으면 01은 생략 가능합니다.

성공 시 필요한 출력:

```text
Price became visible on attempt N/5.
=== SUMMARY ===
ui_lowest=... KRW
acceptance=PRICE_VISIBLE
```

실패 시 필요한 출력:

```text
footer_language=...
footer_location=...
footer_currency=...
navigator_webdriver=...
navigator_language=...
timezone=...
attempt 1..5: Google UI returned Price unavailable
```

## 6. 결과 분기

### A. `acceptance=PRICE_VISIBLE`

runtime Provider migration 진행:

1. `src/flight_bot/providers.py` real-UI persistent 방식으로 교체
2. flight-row scoped 가격 추출
3. 최저 출국 후보 → 귀국 후보 → Booking 최종가격 검증
4. `REQUIRE_VERIFIED_ALERTS=true` 유지
5. `fast-flights` 제거
6. Docker/Ubuntu profile volume 구성
7. tests/docs 갱신

### B. 5회 전부 `Price unavailable` + Footer South Korea/KRW

locale 문제가 아니라 browser/session 조건을 분리합니다.

다음 세 수동 baseline을 비교합니다.

```text
A. 사용자 일반 Edge + 평소 profile + 수동 검색
B. dedicated google-profile-win + remote debugging 없이 수동 검색
C. dedicated google-profile-win + remote debugging 상태에서 수동 검색
```

이 결과로 fresh profile / remote debugging / Playwright interaction 중 어떤 조건이 가격을 없애는지 확인합니다.

### C. Footer Location/Currency 자체가 잘못됨

Google Travel locale setting을 명시적으로 수정하는 UI 단계를 추가합니다. URL의 `gl`/`curr`만 신뢰하지 않습니다.

## 7. 이미 확인한 실패 경로 — 반복 금지

- SerpApi: 브라우저보다 비싼 결과, 저렴한 혼합/별도티켓 결과 누락 사례
- tfs 직링크 + Playwright: hosted + Windows 모두 `Price unavailable`
- fast-flights 3.1: parser `IndexError`, 일부 가격 대신 token
- Fli direct API commit `121d34f...`: CJJ↔TPE no-results; upstream no-results/BotGuard limitations

SerpApi는 Primary로 되돌리지 않습니다. 단, 2026-03 공개 이슈에서 Google Flights의 `Price unavailable`이 간헐적이며 반복 검색으로 완화된 기록은 현재 retry 설계의 참고 근거로만 사용합니다.

## 8. 현재 runtime 주의

현재 `src/flight_bot/providers.py`는 아직 v0.2 tfs URL 기반 코드입니다.

**Windows UI acceptance 성공 전에는 운영 Provider 완료라고 말하면 안 됩니다.**

```text
Core / DB / latch / channels: 구현됨
unit CI: 구현됨
real Google price acceptance: 진행 중
runtime Provider migration: acceptance 뒤에 진행
```

## 9. 유지 요구사항

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

## 10. 새 채팅 시작용 프롬프트

```text
Flight Bot 작업을 이어가자.
repo: junmohome92-code/flight-bot
branch: main

먼저 README.md, docs/PROJECT_STATUS.md, docs/HANDOFF_NEW_CHAT.md를 읽어.
기존 SerpApi / fast-flights parser / Fli direct API / tfs 직링크 실패 실험은 반복하지 마.

현재 gate는 Windows native Edge + CDP attach + dedicated persistent profile + 최대 5회 fresh UI retry다.
내가 `flight-bot - test win/02-live-cjj-tpe-visible.cmd` 결과를 줄 테니 footer_location/footer_currency/navigator_webdriver와 5회 retry 결과를 기준으로 분기해.

acceptance가 성공하면 providers.py를 real-UI persistent 방식으로 교체하고 row-scoped price extraction → return 선택 → Booking 검증 → fast-flights 제거 → Docker/docs/tests까지 진행해.

5회 모두 Price unavailable이면 자동화 우회부터 하지 말고 일반 Edge / dedicated profile(no CDP) / dedicated profile(CDP) 수동 baseline으로 원인을 분리해.
가격이나 수하물은 절대 추정하지 말고 fail-closed 유지해.
```
