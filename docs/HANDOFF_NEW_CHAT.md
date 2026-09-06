# Flight Bot — NEW CHAT HANDOFF

기준 브랜치: `main`

새 채팅 시작 시 반드시 실제 GitHub를 읽고 현재 상태를 추측하지 말 것.

먼저 확인:

```text
1. main 최신 HEAD
2. README.md
3. docs/PROJECT_STATUS.md
4. docs/HANDOFF_NEW_CHAT.md
5. 최신 GitHub Actions CI
```

## 현재 핵심 상태

**2026-09-06 전체 hardening 패치와 CI 검증은 완료됐고, 이제 사용자 Windows의 실제 Google Flights live 결과만 기다리는 상태입니다. 결과 확인 전에는 runtime Provider migration을 완료 처리하거나 새 방식으로 갈아엎지 마십시오.**

hardened code baseline:

```text
6cba0260f48e2f7537b26336c9bf10a3eb90b052
fix: preserve spacing across inline Google flight nodes
```

이 baseline의 최종 CI:

```text
run number: 146
run id: 34023484207
conclusion: success

unit-linux       success
unit-windows     success
docker-smoke     success
browser-contract success
```

문서 업데이트 때문에 새 채팅에서 보는 `main` HEAD는 위 code baseline보다 뒤일 수 있습니다. **코드 기능 기준점은 `6cba026...`, 최신 상태 문서는 현재 `main`의 PROJECT_STATUS/HANDOFF가 Source of Truth**입니다.

## 다음 사용자 액션

이번 hardening에서 `constraints.txt`와 dependency/CI 구성이 변경됐으므로 최신 ZIP을 받은 뒤 **이번 한 번은** Windows에서:

```text
01-setup-and-unit-test.cmd
02-live-cjj-tpe-visible.cmd
```

순서로 실행합니다.

그 이후 dependency 변경이 없고 `.venv-win`이 유지되면 `02`만 실행합니다.

사용자가 새 채팅에 `02` 출력 또는 artifact를 붙여넣으면 그 결과를 기준으로 다음 분기로 바로 진행합니다.

## 기준 acceptance

```text
CJJ → TPE → CJJ
2026-09-18 → 2026-09-20
1 adult
Economy
KRW
all stops / mixed airlines / separate/self-transfer allowed
```

가격은 실시간이므로 특정 숫자를 acceptance 상수로 고정하지 않습니다.

사용자가 수동 Google Flights에서 실제로 본 예:

```text
Cheapest from ₩311,811
EASTAR JET
11:40 PM → 1:10 AM+1
CJJ–TPE
Nonstop
```

이 값은 비교용 당시 예시일 뿐입니다.

## 이미 통과한 사실

Windows transient observer가 실제 Google flight row를 약 0.4초 시점에 포착한 적이 있습니다.

```text
~337k KRW
EASTAR JET
11:40 PM → 1:10 AM+1
CJJ–TPE
Nonstop
```

따라서 `Google이 잠깐 렌더한 실제 flight-row observed price를 읽는 것` 자체는 가능성이 확인됐습니다.

반면 GitHub hosted Windows/Azure 환경은 실제 Google flight-row 가격 DOM이 내려오지 않았으므로 **Google 실가격 acceptance 환경으로 사용하지 않습니다.**

## 이번 hardening에서 실제로 패치한 내용

### 1. Google browser lifecycle

과거 418,500 / 922,965 오선택 원인:

```text
- Cheapest 상태를 URL만 보고 가정
- Cheapest click 뒤 observer를 늦게 arm
- disappearing price span의 isConnected를 후보 확정 때 다시 요구
- Text-node characterData mutation 직접 처리 누락
- 출국 full navigation 후 새 document에서 observer phase reset
- stale captured coordinate를 재검증 없이 click 가능
- loading 중 비싼 임시 row를 너무 일찍 확정 가능
- inline descendant text가 붙으면 시간 parser가 깨질 수 있음
```

현재 구조:

```text
normal search URL
→ init script부터 observer active
→ departure phase 기록
→ 실제 Cheapest/최저가 click
→ aria-selected/pressed 확인
→ added node + aria + characterData capture
→ descendant text-node semantic spacing
→ advertised Cheapest low-water 안정화
→ 실제 eligible row minimum 안정화
→ advertised보다 비싼 fallback 금지
→ pointer 좌표 아래 row identity 재검증
→ real mouse click
→ click 전에 sessionStorage=returning
→ full document navigation
→ 새 document init부터 returning observer 자동 복원
→ Returning marker 주변 row 수집
→ +₩0 return adjustment 허용
→ 귀국 real mouse click
→ Booking options marker + CTA scoped price
```

관련 파일:

```text
src/flight_bot/google_ui_contract.py
scripts/google_booking_pointer_probe.py
scripts/google_dom_capture.js
tests/test_google_browser_contract.py
```

구형 probe는 current tree에서 정리됨.

### 2. 실제 Chromium browser-contract

새 CI job은 helper 함수만 테스트하지 않습니다.

실제 Chromium에서:

```text
Cheapest tab / row text-node
418,500 → 311,811 mutation
→ 311,811 departure candidate capture
→ sessionStorage returning phase
→ full navigation
→ 새 document observer 재생성
→ Returning flights marker
→ +₩0 return row capture
```

를 검증합니다.

첫 run에서 inline `<span>`의 텍스트가 공백 없이 합쳐져 시간 parser가 row를 놓치는 문제가 실제로 잡혔고, `6cba026...`에서 semantic text spacing으로 수정한 뒤 최종 CI green이 됐습니다.

### 3. Slot identity / concurrency

숫자 slot `1/2/3`은 delete 후 재사용되므로 별도 identity를 추가했습니다.

```text
generation = add마다 UUID
revision   = mutation마다 증가
```

검색 시작 당시 generation/revision과 저장 시점 값을 비교해 stale result를 버립니다.

다음은 동일 operation lock으로 직렬화됩니다.

```text
check
add
delete
pause
resume
target
```

### 4. Alert crash safety

```text
ARMED → SENDING → ALERTED
```

Notifier 외부 호출 전에 `SENDING` + PENDING history를 DB에 남깁니다.

- 전송 실패 확인 → FAILED + ARMED 복구
- 전송 성공 + finalize → SENT + ALERTED
- 전송 성공 직후 process crash → SENDING 유지, 같은 below-target 중복 발송 방지

at-most-once 우선 정책입니다.

### 5. 가격 의미 분리

```text
observed_price          = Google flight row
booking_option_price    = Google Booking options
verified_checkout_price = 외부 판매처 checkout final total
verification_status     = 검증 단계
```

절대로 Booking option을 verified final price로 승격하지 않습니다.

### 6. Runtime Provider hard gate

현재 `src/flight_bot/providers.py`는 최종 accepted Provider가 아닙니다.

```text
name=google-playwright-legacy-unverified
accepted_for_alerts=False
```

Service가 `accepted_for_alerts`를 실제 enforcement에 사용하므로 `REQUIRE_VERIFIED_ALERTS=false`로 바꿔도 legacy Provider threshold alert는 금지됩니다.

`src/flight_bot/browser_session.py`에서 browser/context를 process 단위로 재사용하고 `BROWSER_PROFILE_DIR` persistent profile을 지원합니다.

### 7. Security / deployment

Production fail-closed:

```text
Telegram token  → allowed chat IDs 필수
Discord token   → allowed channel IDs 필수
Kakao secret    → allowed user IDs 필수
ADMIN_SECRET    → admin endpoint 전용
```

- Kakao secret 없으면 `/kakao/skill` 404
- Admin secret 없으면 `/admin/check-all` 404
- Admin/Kakao secret 분리
- `secrets.compare_digest`
- slot command ownership 검사
- Compose 기본 bind `127.0.0.1`

Docker:

```text
Python 3.12 slim
non-root app UID 10001
Playwright Chromium
healthcheck
no-new-privileges
/data + /debug
```

`constraints.txt`로 Windows/Linux/Docker dependency graph를 맞췄습니다.

## live 성공 시 보고 싶은 핵심 출력

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

## 사용자 결과별 다음 분기

### A. Cheapest / 출국 / 귀국 / Booking 모두 성공

다음 작업:

```text
external seller checkout final-total gate 설계/구현
→ 실제 final total 검증
→ verified_checkout_price 저장
→ 그 이후 accepted runtime Provider migration
→ Ubuntu production browser acceptance
```

**Google Booking option까지만 성공했다고 `verified=True`로 바꾸면 안 됩니다.**

### B. `departure_advertised`가 수동 화면보다 비쌈

Cheapest selected transition artifact를 확인합니다. 비싼 값을 성공 처리하지 않습니다.

### C. 수동 Cheapest는 싸지만 candidate가 비쌈/없음

`snapshot-departure-state.json`과 HTML/PNG를 기준으로 characterData/row-shape/phase boundary만 수정합니다.

page-wide KRW minimum은 금지입니다.

### D. `body_has_returning=True` 또는 returning marker true인데 candidate 0

`snapshot-return-state.json`의:

```text
phase
returningMarker
returningMarkerAtMs
candidates
rowText
sourceText
```

를 확인합니다.

과거의 `새 document에서 observer가 꺼지는` 버그는 재도입하지 않습니다.

### E. return click 성공, Booking marker/option 0

Booking section scope만 보강합니다. 외부 checkout과 혼동하지 않습니다.

## 결과 전까지 하지 말 것

- runtime Provider accepted migration 완료 선언
- Google Booking option을 verified checkout으로 취급
- page-wide KRW minimum
- 가격/수하물 추정
- advertised Cheapest보다 비싼 fallback
- stale pointer 좌표 무검증 click
- 같은 fresh-tab/URL-refresh/stealth 실험 반복
- 이미 완료된 hardening을 새 채팅에서 다시 재구현

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
