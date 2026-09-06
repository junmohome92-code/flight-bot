# Flight Bot — NEW CHAT HANDOFF

기준 브랜치: `main`

새 채팅 시작 시 먼저 읽기:

```text
README.md
docs/PROJECT_STATUS.md
docs/HANDOFF_NEW_CHAT.md
```

## 현재 한 줄 요약

**Google transient observed-price capture 자체는 이미 성공했습니다. 2026-09-06 전체 코드 리뷰 후 browser lifecycle, slot identity/concurrency, alert crash safety, API 보안, Docker/CI 구조를 전면 보강했습니다. 현재 active live gate는 navigation-safe observer로 실제 Cheapest/최저가를 클릭한 뒤 안정된 최저 출국 → Returning flights → 귀국 row → Google Booking options까지 확인하는 것입니다. 이 새 gate는 사용자 Windows에서 아직 재실행 전이므로 성공으로 간주하면 안 됩니다.**

## 기준 acceptance

```text
CJJ → TPE → CJJ
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate/self-transfer allowed
```

가격은 실시간이므로 특정 숫자 고정 금지.

사용자가 수동 Google Flights에서 실제로 확인한 예 중 하나:

```text
Cheapest from ₩311,811
EASTAR JET
11:40 PM → 1:10 AM+1
CJJ–TPE
Nonstop
```

이 숫자는 실시간 예시일 뿐 acceptance 상수는 아닙니다.

## 이미 통과한 것

Windows transient observer가 실제 flight row를 약 0.4초 시점에 보존한 적이 있습니다.

```text
~337k KRW
EASTAR JET
11:40 PM → 1:10 AM+1
CJJ–TPE
Nonstop
```

따라서 `observed flight-row price를 순간 렌더에서 읽는 것`은 가능성이 확인됐습니다.

## 최근 오답의 구조적 원인

과거 418,500 / 922,965 오선택은 Google 실가격 자체가 아니라 우리 lifecycle 문제였습니다.

주요 원인:

```text
1. Cheapest URL 상태를 실제 Cheapest click 대신 가정
2. Cheapest click 뒤 observer를 늦게 arm
3. disappearing source.isConnected를 다시 요구
4. text-node characterData 변경 직접 처리 누락
5. 출국 full navigation 뒤 새 document에서 captureEnabled=false로 reset
6. stale captured coordinate를 재검증하지 않고 click 가능
```

현재 코드는 이 경로를 제거했습니다.

## 현재 Google 구조

공통 순수 계약:

```text
src/flight_bot/google_ui_contract.py
```

active Windows orchestrator:

```text
scripts/google_booking_pointer_probe.py
```

DOM capture:

```text
scripts/google_dom_capture.js
```

구형 fresh-tab/transient probe와 해당 unit test는 current tree에서 제거했습니다. Git history에는 남아 있습니다.

### lifecycle

```text
normal search URL open
→ document init부터 observer 항상 active
→ Cheapest click 직전 departure phase 기록
→ 실제 Cheapest/최저가 click
→ aria-selected/pressed 확인
→ node add + aria + characterData price 변화 snapshot
→ advertised Cheapest + actual row-lowest settle gate
→ stale coordinate 재검증
→ Playwright real mouse click
→ click 전에 sessionStorage=returning
→ full navigation 시 새 document가 returning phase + active capture로 시작
→ Returning marker 근처 row 수집
→ +₩0 포함 return price/adjustment 허용
→ return pointer click
→ Booking options marker + CTA-scoped price
```

`page-wide KRW min`, broad container `.click()`, stale-coordinate fallback은 금지입니다.

### live 성공 출력

```text
=== EXPLICIT CHEAPEST SELECTION ===
cheapest_tab_found=True
cheapest_tab_clicked=True
cheapest_tab_selected=True

departure_selected=...
departure_selection_policy=explicit-cheapest-settled-lowest
departure_advertised=...
departure_navigation_confirmed=True

return_selected=...
return_selection_policy=return-settled-lowest
return_price_kind=adjustment 또는 displayed
return_pointer_click_sent=True

booking_options_marker=True
booking_option_candidates=>0

=== SUMMARY ===
acceptance=GOOGLE_BOOKING_OPTION_REACHED_WITH_NAVIGATION_SAFE_CAPTURE
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
```

## 현재 runtime Provider

`src/flight_bot/providers.py`는 아직 최종 accepted Provider가 아닙니다.

```text
name=google-playwright-legacy-unverified
accepted_for_alerts=False
```

중요:

- row-scoped observed만 반환
- page-wide minimum 금지
- 외부 seller checkout 미구현 → `price_verified=False`
- Service가 `accepted_for_alerts=False`를 실제 hard gate로 강제
- 따라서 `REQUIRE_VERIFIED_ALERTS=false`로 바꿔도 legacy Provider는 threshold alert 불가
- browser/context를 `src/flight_bot/browser_session.py`에서 process 단위로 재사용
- `BROWSER_PROFILE_DIR` 설정 시 persistent profile
- Windows native Edge acceptance와 Ubuntu Docker Chromium acceptance는 별개 gate

## Core 구조 보강

### slot identity

숫자 `1/2/3`은 재사용되므로 영구 identity로 사용하지 않습니다.

```text
generation = add마다 새 UUID
revision   = mutation마다 증가
```

검색 결과 저장 시 시작 당시 generation/revision과 현재 값을 비교하여 stale 결과를 폐기합니다.

검색 및 `add/delete/pause/resume/target`은 같은 operation lock을 사용합니다.

### alert crash state

```text
ARMED → SENDING → ALERTED
```

외부 notifier 호출 전에 `SENDING`을 DB에 기록합니다. process가 전송 직후 죽어도 다음 run에서 같은 below-target 구간을 다시 보내지 않는 at-most-once 정책입니다.

전송 실패가 명확히 확인되면 `FAILED` history 후 ARMED로 복구합니다.

### observed / verified persistence

`offers`는 다음을 별도 저장합니다.

```text
observed_price
booking_option_price
verified_checkout_price
verification_status
```

## 보안

Production fail-closed:

- Telegram token + allowlist 필수
- Discord token + allowlist 필수
- Kakao secret + allowed user IDs 필수
- Kakao secret 없으면 `/kakao/skill` 404
- `ADMIN_SECRET` 없으면 `/admin/check-all` 404
- Admin secret은 Kakao secret과 분리
- slot command는 해당 platform/owner가 만든 slot만 제어
- Compose port는 기본 `127.0.0.1` bind

## Docker / dependencies / CI

- non-root `app` user
- Docker healthcheck
- reusable browser profile volume path 지원
- `constraints.txt`에 검증 dependency graph 고정
- Windows setup / Linux CI / Windows CI / Docker build 모두 constraints 사용
- Docker CI: image build + container `/health` smoke + non-root 확인

GitHub hosted 환경은 **실제 Google 가격 acceptance 환경이 아님**. 실제 row DOM이 내려오지 않았던 것이 이미 확인됐습니다.

## 다음 액션

코드/CI가 모두 green인 최종 HEAD를 확인한 후 사용자에게는 최신 ZIP에서:

```text
flight-bot - test win\02-live-cjj-tpe-visible.cmd
```

만 다시 실행하도록 안내합니다.

분기:

A. Cheapest/출국/귀국/Booking 모두 성공
→ external seller checkout final-total gate 설계/구현

B. `departure_advertised`가 수동 화면보다 비쌈
→ Cheapest selected transition artifact 확인. 비싼 값을 성공 처리 금지

C. 수동 Cheapest는 싸지만 candidate가 비쌈
→ `snapshot-departure-state.json`에서 characterData/phase boundary 확인

D. Returning marker true인데 return 0
→ 새 `snapshot-return-state.json`의 phase/marker timestamp/candidates 확인. 이전 `captureEnabled reset` 버그는 재도입 금지

E. Booking marker false/option 0
→ Booking section scope만 보강. 외부 checkout과 혼동 금지

## 절대 유지할 요구사항

- exactly 3 slots
- pause occupies / delete reuses numeric slot
- target_price mandatory
- no duplicate below-target alerts
- notifier never invokes Provider
- SQLite WAL
- searches globally sequential
- `REQUIRE_VERIFIED_ALERTS=true` default
- never synthesize price/baggage
- unknown baggage = `정보 확인 불가`
- `verified=True` only after external seller checkout final total
