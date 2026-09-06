# flight-bot - test win

Windows 10/11에서 현재 `flight-bot` 소스의 Google Flights 실가격 경로를 검증하는 전용 테스트 디렉토리입니다.

이 폴더는 봇 코드를 복제하지 않고 한 단계 위 실제 프로젝트 소스를 사용합니다.

## 실행

최초 1회 또는 dependency 변경 후:

```text
01-setup-and-unit-test.cmd
```

**2026-09-06 hardening에서 `constraints.txt`와 dependency/CI 구성이 바뀌었으므로, 그 이전 ZIP/가상환경에서 넘어오는 경우 이번 한 번은 반드시 `01`을 먼저 실행합니다.**

그 다음 live 검증:

```text
02-live-cjj-tpe-visible.cmd
```

이후 dependency 변경이 없고 `.venv-win`이 유지되면 `02`만 실행하면 됩니다. 현재 acceptance는 **visible native Edge 전용**입니다. 예전 headless launcher는 실제 active probe와 모순되어 제거했습니다.

## acceptance 조건

```text
CJJ (청주) → TPE (타이베이) → CJJ
2026-09-18 ~ 2026-09-20
성인 1명 / Economy / KRW
경유·혼합·별도티켓 허용
```

실시간 가격이므로 특정 금액을 성공값으로 고정하지 않습니다.

## 현재 구조

active Python:

```text
scripts/google_booking_pointer_probe.py
```

DOM capture:

```text
scripts/google_dom_capture.js
```

공통 순수 계약:

```text
src/flight_bot/google_ui_contract.py
```

브라우저 lifecycle 회귀 테스트:

```text
tests/test_google_browser_contract.py
```

흐름:

```text
일반 Google Flights 검색 URL open
→ init script가 첫 document byte부터 가격/DOM 변화 감시
→ Cheapest/최저가 클릭 요청 직전 departure phase 표시
→ Cheapest/최저가를 실제 클릭
→ aria-selected/pressed 확인
→ characterData(Text node) 포함 transient 가격 변화 snapshot
→ inline descendant text-node를 semantic spacing으로 합침
→ Cheapest 표시가 + 실제 row 최저가가 둘 다 안정될 때까지 대기
→ 비싼 임시 row fallback 금지
→ 선택 row 좌표가 아직 같은 flight card인지 재검증
→ 실제 Playwright mouse click
→ 출국 선택 전 sessionStorage에 returning phase 기록
→ full navigation이 발생해도 새 document init script가 즉시 returning capture 시작
→ Returning flights marker 주변 실제 귀국 row 수집
→ +₩0 같은 귀국 추가금도 허용
→ 귀국 row pointer click
→ Booking options marker가 실제 존재하는 상태에서만 CTA 가격 수집
```

page 전체 KRW minimum과 DOM `.click()` fallback은 사용하지 않습니다.

## 현재 fail-closed 규칙

예를 들어 사람이 보는 Cheapest가 `₩311,811`인데 봇이 `₩384,361` 또는 `₩418,500`만 잡았다면 비싼 값을 대신 선택하지 않고 실패해야 정상입니다.

또 transient row가 사라진 뒤 과거 좌표에 다른 항공편이 들어왔다면 좌표를 그대로 클릭하지 않습니다. 좌표 아래 DOM이 snapshot과 같은 시간/route flight card인지 다시 검사한 뒤에만 mouse click을 보냅니다.

## 정상 출력

```text
=== EXPLICIT CHEAPEST SELECTION ===
cheapest_tab_found=True
cheapest_tab_clicked=True
cheapest_tab_selected=True
```

출국:

```text
departure_selected=... KRW
departure_selection_policy=explicit-cheapest-settled-lowest
departure_cheapest_tab_selected=True
departure_advertised=...
departure_candidate_prices=...
departure_pointer_click_mode=...
departure_navigation_confirmed=True
```

귀국:

```text
return_selected=...
return_selection_policy=return-settled-lowest
return_price_kind=adjustment 또는 displayed
return_candidate_prices=...
return_pointer_click_sent=True
```

Booking:

```text
booking_options_marker=True
booking_option_candidates=1 이상
```

최종 성공:

```text
=== SUMMARY ===
departure_observed=...
return_displayed_price=...
return_price_kind=...
google_booking_option=...
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
acceptance=GOOGLE_BOOKING_OPTION_REACHED_WITH_NAVIGATION_SAFE_CAPTURE
```

Google Booking option은 외부 판매처 checkout final total이 아니므로 여기까지 성공해도 `verified=False`가 정상입니다.

## GitHub에서 검증된 browser lifecycle

실사이트 가격 acceptance와 별개로 GitHub CI의 실제 Chromium에서는 다음을 재현해 통과했습니다.

```text
Cheapest/row text-node 418,500 → 311,811 mutation
→ 311,811 transient departure capture
→ full document navigation
→ returning phase 자동 복원
→ Returning flights marker
→ +₩0 return row capture
```

이 검증은 Google hosted 실가격을 뜻하지 않습니다. 실제 가격은 이 Windows visible Edge run으로 확인해야 합니다.

## 실패 artifact

```text
artifacts/google-ui-win/snapshot-departure-state.json
artifacts/google-ui-win/snapshot-return-state.json
artifacts/google-ui-win/snapshot-error-state.json
artifacts/google-ui-win/*.png
artifacts/google-ui-win/*.txt
artifacts/google-ui-win/*.html
```

특히 귀국 0건이면 `snapshot-return-state.json`에서 `phase`, `returningMarker`, `returningMarkerAtMs`, `candidates`를 확인합니다.

## 브라우저

개인 Edge/Chrome profile을 사용하지 않습니다.

```text
artifacts/google-profile-win/
```

native Microsoft Edge를 별도 profile + CDP로 연결합니다.

## PowerShell 직접 실행

```powershell
cd 'C:\work\flight-bot\flight-bot - test win'
.\setup-and-unit-test.ps1
.\live-cjj-tpe.ps1
```

## 참고

- API key 불필요
- Google Flights는 공개 개발자 API가 아니므로 UI/DOM/session/IP 변화 가능
- GitHub hosted Windows는 실제 flight-row 가격 DOM이 내려오지 않아 실가격 acceptance 환경으로 사용하지 않음
- 가격/수하물 확인 실패 시 값을 추정하지 않음
- 외부 판매처 checkout final total 확인 전에는 verified alert 금지
