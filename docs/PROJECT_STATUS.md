# Flight Bot — PROJECT STATUS

최종 정리일: 2026-09-06

## 1. 현재 단계

**Google Flights Provider Migration — transient observed capability confirmed / navigation-safe Cheapest→Returning→Booking gate pending user Windows rerun**

2026-09-06 전체 코드 리뷰를 수행했고 발견된 correctness / concurrency / security / deployment 문제를 전면 보강했습니다.

현재 runtime `src/flight_bot/providers.py`는 최종 accepted Provider가 아니라:

```text
name=google-playwright-legacy-unverified
accepted_for_alerts=False
```

상태입니다.

## 2. 유지되는 Core 요구사항

- Python 3.12+
- FastAPI / APScheduler
- SQLite WAL
- Telegram / Discord / Kakao reactive skill
- 슬롯 정확히 3개(1/2/3)
- pause 슬롯 점유, delete 후 번호 재사용
- `target_price` 필수
- 동일 below-target 구간 반복 알림 금지
- notifier가 Provider 호출 금지
- 검색/slot mutation 전역 순차 실행
- `REQUIRE_VERIFIED_ALERTS=true`
- 가격/수하물 추정 금지
- 위탁수하물 미확인 = `정보 확인 불가`
- observed / Booking / verified 의미 분리
- `verified=True`는 외부 판매처 checkout final total 검증 이후에만 허용

## 3. Alert state

기존:

```text
ARMED → ALERTED
```

에서 crash duplicate 방지를 위해:

```text
ARMED
→ SENDING
→ ALERTED
→ 목표가 위로 복귀
→ ARMED
```

으로 보강했습니다.

Notifier 호출 전에 `SENDING`과 PENDING alert history를 기록합니다.

- 전송 실패가 확인되면 history=FAILED + ARMED 복구
- 전송 성공 후 DB finalization까지 성공하면 history=SENT + ALERTED
- 외부 전송 성공 직후 process crash 가능성이 있으면 SENDING이 남아 동일 below-target 재전송을 막음

즉 crash 상황에서는 중복 방지를 우선하는 at-most-once 정책입니다.

## 4. Slot identity / stale result 방지

숫자 slot ID 1/2/3은 delete 후 재사용되므로 identity로 충분하지 않습니다.

현재:

```text
generation = 새 add마다 UUID
revision   = 설정/상태 mutation마다 증가
```

를 저장합니다.

검색 시작 slot의 generation/revision과 결과 저장 시 현재 값을 비교하며 달라졌으면 stale search result를 폐기합니다.

같은 process 안에서는 다음을 하나의 operation lock으로 직렬화합니다.

```text
check
add
delete
pause
resume
target
```

따라서 검색 중 slot #1 삭제 → 새 slot #1 재사용 → 옛 검색 결과가 새 slot에 저장되는 race를 차단했습니다.

## 5. 가격 persistence

`FlightOffer`과 DB history에서 의미를 분리했습니다.

```text
observed_price          = Google flight row
booking_option_price    = Google Booking options
verified_checkout_price = external seller checkout final total
verification_status     = verification 단계
```

legacy Provider는 `observed_price`만 만들고 `verified_checkout_price=None`, `price_verified=False`입니다.

## 6. Google transient observed capability

사용자 Windows에서 Google이 실제 flight row 가격을 잠깐 렌더했다가 `Price unavailable`로 바꾸는 현상을 확인했습니다.

과거 observer가 약 0.4초 시점 실제 row를 보존하는 데 성공했습니다.

```text
~337k KRW
EASTAR JET
11:40 PM → 1:10 AM+1
CJJ–TPE
Nonstop
```

따라서 transient row observed capture 자체는 가능성이 확인됐습니다.

## 7. 최근 418k / 922k 오답 원인

사용자 수동 화면에서는 예를 들어:

```text
Cheapest from ₩311,811
```

이었지만 bot이 418,500 또는 과거 922,965를 고른 적이 있습니다.

전체 리뷰에서 원인을 다음과 같이 정리했습니다.

1. Cheapest tfu URL을 직접 열어 실제 Cheapest click을 생략
2. Cheapest click 뒤 capture를 arm해 transition price를 놓칠 수 있음
3. disappearing source/anchor의 `isConnected`를 후보 확정 때 다시 요구
4. MutationObserver의 `characterData` Text-node target을 Element가 아니라는 이유로 직접 처리하지 않음
5. 출국 선택 full navigation 후 새 document init state가 `captureEnabled=false`로 reset
6. 과거 좌표가 layout shift 후 다른 row를 가리켜도 재검증 없이 pointer click 가능
7. 단순 fixed window만으로 loading 중 비싼 임시 row를 너무 빨리 선택 가능

## 8. 현재 Google UI 구조

공통 순수 규칙:

```text
src/flight_bot/google_ui_contract.py
```

Windows orchestration:

```text
scripts/google_booking_pointer_probe.py
```

DOM init/capture:

```text
scripts/google_dom_capture.js
```

구형:

```text
scripts/google_ui_probe.py
scripts/google_transient_price_probe.py
```

와 해당 unit test는 current tree에서 제거했습니다.

### 현재 lifecycle

```text
normal search URL
→ init부터 observer active
→ Cheapest click 직전 departure phase
→ actual Cheapest/최저가 click
→ selected 확인
→ added node + aria + characterData snapshot
→ advertised Cheapest low-water 안정
→ actual eligible row minimum 안정
→ loading 중이면 최소 2 concrete row 요구
→ advertised보다 비싼 fallback 금지
→ pointer 좌표 아래 flight card 재검증
→ real mouse click
→ click 전에 sessionStorage=returning
→ full navigation 새 document도 즉시 returning capture
→ Returning marker 주변 row
→ +₩0 포함 return price 허용
→ return click
→ Booking options marker + CTA price
```

## 9. 현재 live gate

기준:

```text
CJJ → TPE → CJJ
2026-09-18 → 2026-09-20
1 adult / Economy / KRW
all stops / mixed / separate/self-transfer allowed
```

최종 새 code 성공 marker:

```text
acceptance=GOOGLE_BOOKING_OPTION_REACHED_WITH_NAVIGATION_SAFE_CAPTURE
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
```

이 **새 hardened probe는 아직 사용자 Windows에서 재실행 전**입니다. CI green은 Google 실가격 acceptance를 의미하지 않습니다.

## 10. Runtime browser

`src/flight_bot/browser_session.py` 추가.

legacy runtime은 각 slot마다 Playwright/Chromium 전체를 새로 띄우지 않고 process 단위 browser context를 재사용합니다.

`BROWSER_PROFILE_DIR` 설정 시 persistent profile을 사용합니다.

중요:

```text
Windows native Edge live acceptance != Ubuntu Docker Chromium live acceptance
```

Ubuntu production 실가격 gate는 별도로 남습니다.

## 11. Alert safety hard gate

Service는 이제 Provider의:

```text
accepted_for_alerts
```

를 실제 enforcement에 사용합니다.

따라서 legacy Provider는 사용자가 `REQUIRE_VERIFIED_ALERTS=false`로 바꿔도 threshold alert를 보낼 수 없습니다.

## 12. Security

Production fail-closed로 변경했습니다.

- Telegram token → allowed chat IDs 필수
- Discord token → allowed channel IDs 필수
- Kakao secret → allowed user IDs 필수
- Kakao secret 없으면 `/kakao/skill` 404
- `ADMIN_SECRET` 없으면 `/admin/check-all` 404
- Admin/Kakao secret 분리
- `secrets.compare_digest` 사용
- command slot ownership 검사
- Compose API는 기본 `127.0.0.1` bind

## 13. Legacy DB migration

기존 DB에 다음 column을 보강합니다.

watch_slots:

```text
generation
revision
last_verified_price
currency
...
```

offers:

```text
observed_price
booking_option_price
verified_checkout_price
verification_status
...
```

alert_history:

```text
delivery_state
dedupe_key
error
```

구형 slot 중 `target_price<=0`인 row는 새 mandatory-target 계약을 위반하므로 삭제하지 않고 **paused(enabled=0)** 로 migration합니다.

## 14. Dependencies / Docker / CI

`constraints.txt`에 검증 dependency graph를 고정했습니다.

Docker:

- Python 3.12 slim
- non-root `app` UID 10001
- Playwright Chromium
- `/data`, `/debug`
- healthcheck
- `no-new-privileges`

CI:

```text
unit-linux:
  constrained install
  compileall
  pytest

unit-windows:
  constrained install
  compileall
  pytest
  Playwright Chromium launch

docker-smoke:
  production image build
  run container
  GET /health
  non-root user 확인
```

GitHub hosted Windows는 과거 실제 Google flight-row price DOM이 내려오지 않았으므로 live 실가격 acceptance 환경으로 사용하지 않습니다.

## 15. 다음 액션

1. 최종 HEAD의 Linux / Windows / Docker CI green 확인
2. 최신 ZIP에서 Windows `02-live-cjj-tpe-visible.cmd` 실행
3. 출력에서 실제 수동 Cheapest와 departure 값을 비교
4. Returning/Booking까지 성공하면 external seller checkout gate 구현
5. 그 이후 accepted runtime Provider migration
6. Ubuntu production browser acceptance

## 16. 금지

- page-wide KRW minimum
- 가격 추정/합성
- 수하물 추정
- Google Booking option을 verified checkout으로 취급
- advertised Cheapest보다 비싼 row를 fallback 선택
- stale pointer coordinate 무검증 click
- legacy Provider alert 허용
