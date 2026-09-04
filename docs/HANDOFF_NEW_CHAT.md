# Flight Bot — NEW CHAT HANDOFF

이 문서는 새 ChatGPT 채팅에서 작업을 바로 이어가기 위한 인계서입니다.

## 1. 시작할 때 먼저 읽을 파일

```text
README.md
docs/PROJECT_STATUS.md
docs/HANDOFF_NEW_CHAT.md
```

그 다음 저장소 상태를 확인합니다.

```bash
git status
git branch --show-current
git log -5 --oneline
```

기준 브랜치는 `main`입니다.

## 2. 현재 한 줄 요약

**봇 Core는 살아 있고, Google Flights 실가격 Provider만 migration gate 진행 중입니다.**

SerpApi / fast-flights parser / Fli direct API / tfs 직링크 방식은 CJJ↔TPE 실가격 기준으로 이미 문제를 확인했으므로 다시 처음부터 반복 검증하지 않습니다.

현재 다음 실험은 **실제 Google Flights 첫 화면 UI + Windows Edge/Chrome + 전용 persistent profile**입니다.

## 3. 사용자가 다음에 할 작업

최신 저장소 ZIP을 다시 받거나 `git pull` 후 Windows에서:

```text
flight-bot - test win
└─ 02-live-cjj-tpe-visible.cmd
```

`.venv-win`이 이미 정상이라면 `01`을 다시 돌릴 필요는 없습니다. 소스/의존성이 크게 바뀌었거나 `.venv-win`이 없으면 `01-setup-and-unit-test.cmd`부터 실행합니다.

기준 검색:

```text
CJJ → TPE
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate style results allowed
```

새 probe는:

```text
scripts/google_ui_probe.py
```

입니다.

## 4. 사용자에게 받아야 할 출력

성공 시:

```text
price_candidates=...
#1 ... KRW | ...
...
=== SUMMARY ===
ui_lowest=... KRW
acceptance=PRICE_VISIBLE
```

실패 시 콘솔 전체와 가능하면 다음 중 하나를 확인합니다.

```text
artifacts/google-ui-win/cjj-tpe-error.txt
artifacts/google-ui-win/cjj-tpe-error.png
```

HTML도 필요하면:

```text
artifacts/google-ui-win/cjj-tpe-error.html
```

## 5. 결과 분기

### A. `acceptance=PRICE_VISIBLE`

바로 runtime Provider migration을 진행합니다.

해야 할 순서:

1. `src/flight_bot/providers.py`를 real-UI persistent browser 방식으로 교체
2. browser profile path를 운영 설정으로 승격
   - Windows probe: `artifacts/google-profile-win`
   - Docker/Ubuntu: `/data/google-profile`
3. 가격은 페이지 전체 min이 아니라 **실제 flight row에 붙은 가격만** 비교
4. 최저 후보 클릭 → returning flights → 귀국 후보 선택 → Booking page
5. `Lowest total price` 또는 실제 booking option에서 최종 가격 검증
6. `REQUIRE_VERIFIED_ALERTS=true` 정책 유지
7. real-UI Provider 채택 후 `fast-flights` dependency와 tfs query-builder 제거
8. `scripts/live_smoke.py`를 새 Provider 기준으로 교체 또는 불필요하면 삭제
9. Docker/compose profile volume 및 설정 갱신
10. Linux/Windows unit + compileall + Windows live acceptance 재검증

### B. 브라우저 화면에는 가격이 보이는데 `price_candidates=0`

Provider 전략은 맞고 selector만 문제입니다.

`cjj-tpe-error.html/txt`를 기준으로:

- 실제 가격 element의 `aria-label`
- 가장 가까운 `li`, `[role=listitem]`, `[role=button]`
- 해당 row의 airline / CJJ / TPE / Nonstop text

를 확인해 `collect_price_candidates()`만 수정합니다.

이 경우 Fli/SerpApi로 되돌아가지 않습니다.

### C. 실제 Edge 화면도 `Price unavailable`

먼저 같은 `artifacts/google-profile-win`을 유지한 채 **2번을 한 번 더 실행**합니다. persistent profile이므로 첫 세션 이후 쿠키/Google 상태가 유지됩니다.

두 번째에도 실제 화면 자체가 `Price unavailable`이면 UI automation/session 제약을 다시 평가합니다.

기본 전략으로 stealth 플러그인, CAPTCHA 우회, BotGuard 우회를 넣지 않습니다.

## 6. 이미 확인한 실패 경로 — 반복 금지

### SerpApi

브라우저 직접 Google Flights보다 비싸고, 저렴한 혼합/별도티켓 스타일 결과가 누락된 사례가 있었습니다.

### tfs 직링크 + Playwright

GitHub hosted IP뿐 아니라 사용자 Windows 일반 회선에서도 `Price unavailable`.

### fast-flights 3.1 parser

```text
IndexError
price = k[1][0][1]
```

raw payload에서 RF511/ZE781 후보는 가격 대신 `[[], token]` 형태.

독립 편도 최저가 합은 724,650 KRW였지만 원하는 브라우저 왕복 최저가와 다른 경유 조합이었습니다.

### Fli direct service API

검증 source:

```text
punitarani/fli
commit 121d34fea056dc513258958c4262cb5a4cc033c1
```

`get_booking_options` 존재 확인 성공 후 실제 CJJ↔TPE 왕복 검색은:

```text
Fli returned no round-trip results
```

upstream issue #223에도 일반 노선 no-results 문제가 보고돼 있습니다.

upstream issue #168에는 GetBookingResults의 OTA 결과가 실제 브라우저 BotGuard 신호 없이 축소된다는 보고가 있습니다.

## 7. 현재 runtime 관련 주의

현재 `src/flight_bot/providers.py`는 아직 v0.2 tfs URL 기반 코드입니다.

그러므로 새 채팅에서 **Windows UI acceptance 성공 전에는 “운영 Provider 완료”라고 말하면 안 됩니다.**

현재 상태 표현:

```text
Core / DB / latch / channels: 구현됨
unit CI: 구현됨
real Google price acceptance: 진행 중
runtime Provider migration: acceptance 뒤에 진행
```

## 8. Core에서 유지해야 할 요구사항

- 슬롯은 정확히 3개
- pause는 슬롯 점유
- delete가 슬롯 해제
- target_price 기준 알림
- 이전 최저가 갱신 알림 방식 아님
- ARMED → 하향 돌파 1회 → ALERTED
- 목표가 위로 복귀 시 re-arm
- 같은 아래 구간에서 반복 알림 금지
- notifier가 Provider 호출 금지
- SQLite WAL
- 검색 순차 실행
- 미검증 가격/수하물 추정 금지
- 위탁수하물 미확인은 `정보 확인 불가`

## 9. Provider acceptance 뒤에 남은 후속 개선

우선순위는 Provider acceptance보다 낮습니다.

```text
10분 local cache
single-flight coalescing
subscriptions 분리
provider attempt/error/cache logging
browser 재사용 최적화
Provider error taxonomy 확장
```

## 10. 새 채팅 시작용 프롬프트

아래를 그대로 붙여넣어도 됩니다.

```text
Flight Bot 작업을 이어가자.
repo: junmohome92-code/flight-bot
branch: main

먼저 README.md, docs/PROJECT_STATUS.md, docs/HANDOFF_NEW_CHAT.md를 읽고 현재 상태를 확인해.
기존 SerpApi / fast-flights parser / Fli direct API 실패 실험을 반복하지 마.
현재 gate는 Windows real Google Flights UI persistent-browser acceptance다.

내가 `flight-bot - test win/02-live-cjj-tpe-visible.cmd` 결과를 줄 테니,
그 결과에 따라 PROJECT_STATUS/HANDOFF의 분기대로 진행해.

acceptance가 성공하면 runtime providers.py를 real-UI persistent 방식으로 교체하고,
row-scoped price extraction → return 선택 → Booking 최종가격 검증 → fast-flights 제거 → Docker/docs/tests 갱신까지 진행해.

가격이나 수하물은 절대 추정하지 말고 fail-closed 유지해.
```
