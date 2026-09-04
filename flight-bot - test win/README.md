# flight-bot - test win

Windows 10/11에서 현재 `flight-bot` 소스의 Google Flights 실가격 경로를 검증하는 전용 테스트 디렉토리입니다.

이 폴더는 봇 코드를 복제하지 않고 한 단계 위 실제 프로젝트 소스를 사용합니다.

## 실행

최초 1회:

```text
01-setup-and-unit-test.cmd
```

이후 최신 ZIP으로 갱신했더라도 `.venv-win`이 그대로 있으면 live 검증은:

```text
02-live-cjj-tpe-visible.cmd
```

만 실행하면 됩니다.

## acceptance 조건

```text
CJJ (청주) → TPE (타이베이) → CJJ
2026-09-18 ~ 2026-09-20
성인 1명 / Economy / KRW
경유·혼합·별도티켓 허용
```

실시간 가격이므로 특정 금액을 고정 성공값으로 강제하지 않습니다.

## 현재 02가 검증하는 것

active script:

```text
scripts/google_booking_pointer_probe.py
```

현재 방식:

```text
Google Cheapest acceptance URL 직접 open
→ 페이지 초기 transient 가격 row snapshot
→ 사라진 price span도 snapshot 유지
→ 출국 후보 900ms 수집
→ Cheapest advertised price보다 비싼 fallback 금지
→ 최저 출국편 실제 mouse pointer click
→ Returning flights 화면 확인
→ 귀국 후보 650ms 수집
→ 최저 귀국편 mouse pointer click
→ Google Booking options CTA 주변 가격 확인
```

page 전체의 가장 작은 원화 숫자를 가져오지 않습니다.

## 왜 이전에 922,965원을 골랐나

이전 pointer probe는 후보를 선택할 때 price source가 아직 DOM에 연결돼 있는지를 다시 검사했습니다.

33만원대 최저가 span은 잠깐 나타났다 사라져 후보에서 빠졌고, 오래 남은 922,965원 row가 대신 선택됐습니다.

이번 버전은 price/row/클릭 좌표를 나타나는 즉시 snapshot으로 보존하므로 price span이 사라져도 후보 기록을 버리지 않습니다.

또 Cheapest 탭에서 더 낮은 가격이 확인됐는데 그 row를 못 잡았다면 비싼 항공편을 대신 선택하지 않고 실패합니다.

## 정상적으로 보고 싶은 출력

출국:

```text
departure_selected=... KRW
departure_selection_policy=advertised-guarded-lowest 또는 captured-lowest
departure_advertised=...
departure_candidate_prices=...
departure_pointer_click_mode=live-marked-anchor 또는 captured-coordinate
departure_pointer_click_sent=True
departure_navigation_confirmed=True
```

귀국:

```text
return_selected=... KRW
return_selection_policy=captured-lowest
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
return_selection_price=...
google_booking_option=...
observed=True
booking_option_visible=True
external_checkout_verified=False
verified=False
acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_PRESERVED_TRANSIENT_SNAPSHOTS
```

Google Booking option은 아직 외부 판매처의 최종 checkout 가격이 아니므로 성공해도 `verified=False`가 정상입니다.

## fail-closed 예

Cheapest 탭이 약 335,000원을 광고하는데 922,965원 같은 비싼 row만 snapshot된 경우:

```text
Cheapest tab advertised a lower price than every captured departure row;
refusing expensive fallback
```

가 정상입니다. 이런 경우 비싼 row를 대신 클릭하면 안 됩니다.

## 실패 artifact

```text
artifacts/google-ui-win/snapshot-departure-state.json
artifacts/google-ui-win/snapshot-return-state.json
artifacts/google-ui-win/snapshot-error-state.json
artifacts/google-ui-win/*.png
artifacts/google-ui-win/*.txt
artifacts/google-ui-win/*.html
```

귀국편 0건이면 `snapshot-return-state.json`의 `returningMarker`와 `candidates`가 가장 중요합니다.

## 브라우저

live test는 개인 Edge/Chrome profile을 사용하지 않고 전용 profile을 만듭니다.

```text
artifacts/google-profile-win/
```

현재 acceptance는 native Microsoft Edge + Playwright CDP 연결을 사용합니다.

## PowerShell 직접 실행

```powershell
cd 'C:\work\flight-bot\flight-bot - test win'
.\setup-and-unit-test.ps1
.\live-cjj-tpe.ps1
```

## 참고

- API key 불필요
- Google Flights는 공개 개발자 API가 아니므로 UI/DOM/session/IP 변화 가능
- GitHub hosted Windows에서는 실제 flight-row 가격 DOM이 내려오지 않는 것이 확인돼 live price 검증용으로 사용하지 않음
- 가격/수하물 확인 실패 시 값을 추정하지 않음
- 외부 판매처 checkout final total 확인 전에는 verified alert 금지
