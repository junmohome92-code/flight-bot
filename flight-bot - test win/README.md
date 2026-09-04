# flight-bot - test win

Windows 10/11 PowerShell에서 현재 `flight-bot` 소스의 Google Flights 실가격 경로를 검증하는 전용 테스트 디렉토리입니다.

이 폴더는 봇 코드를 복제하지 않습니다. 한 단계 위의 실제 프로젝트 소스를 그대로 사용합니다.

## 실행 순서

탐색기에서 다음 순서로 실행합니다.

```text
01-setup-and-unit-test.cmd
02-live-cjj-tpe-visible.cmd
```

`01`은 다음을 자동 수행합니다.

```text
Python 3.12 확인/설치
→ Windows용 .venv-win 생성
→ 프로젝트 + 테스트 의존성 설치
→ Playwright Chromium 설치
→ pytest 실행
```

`02`는 **실제 Google Flights UI**를 사용합니다.

```text
CJJ (청주) → TPE (타이베이)
2026-09-18 ~ 2026-09-20
성인 1명 / Economy / KRW
경유·혼합·별도티켓 허용
```

중요: 현재 `02`는 다음 경로를 사용하지 않습니다.

```text
fast-flights parser      사용 안 함
Fli direct service API   사용 안 함
Google tfs 직링크        사용 안 함
```

대신 Google Flights 첫 화면을 열고 `Where from?`, `Where to?`, `Departure`, `Return` UI에 직접 값을 넣은 뒤 Search 버튼을 누릅니다.

## 브라우저 방식

Windows visible 테스트에서는 다음 순서로 브라우저를 시도합니다.

```text
Microsoft Edge
→ Google Chrome
→ Playwright Chromium
```

개인 Edge/Chrome 프로필은 사용하지 않습니다. 아래에 별도 전용 프로필을 만들어 반복 테스트에서 쿠키/세션을 유지합니다.

```text
artifacts/google-profile-win/
```

디버그 결과는 아래에 저장됩니다.

```text
artifacts/google-ui-win/
  cjj-tpe-results.png/.txt/.html
  또는
  cjj-tpe-error.png/.txt/.html
```

`artifacts/`는 Git에서 무시합니다.

## PowerShell에서 직접 실행

```powershell
cd 'C:\work\flight-bot\flight-bot - test win'
.\setup-and-unit-test.ps1
.\live-cjj-tpe.ps1
```

headless 테스트:

```powershell
.\live-cjj-tpe.ps1 -Headless
```

## 성공 판정

콘솔 마지막에 다음이 나오면 1차 acceptance 성공입니다.

```text
=== SUMMARY ===
ui_lowest=... KRW
acceptance=PRICE_VISIBLE
```

가격은 실시간으로 변하므로 정확히 특정 숫자를 강제하지 않습니다. 기존 일반 브라우저에서는 같은 CJJ↔TPE 조건에서 약 33만 원대 왕복 결과가 관찰된 적이 있습니다.

visible 모드는 결과/실패 후 브라우저를 잠시 열어 두므로 화면도 직접 확인할 수 있습니다.

## 지금까지 폐기한 실가격 경로

### fast-flights parser

`fast-flights 3.1.0`은 현재 Google payload의 `[[], token]` 가격 블록을 만나 `IndexError`로 전체 파싱이 깨졌습니다. raw payload를 직접 확인했을 때 RF511/ZE781 같은 직항 후보는 가격 숫자 대신 다음 단계용 토큰만 반환됐습니다.

### Fli direct API

GitHub 최신 소스를 고정 설치해 왕복 확장 + `GetBookingResults`까지 시험했지만 CJJ↔TPE 2026-09-18~20에서 `Fli returned no round-trip results`였습니다. upstream에도 2026-08 기준 일반 노선이 `No flights found`로 반환되는 동일 계열 이슈가 있습니다. 따라서 현재 Provider 후보에서 제외합니다.

### Google tfs 직링크 + Playwright

노선/날짜/항공편 목록은 맞게 로드됐지만 GitHub hosted runner와 사용자 Windows 일반 회선 모두 `Price unavailable`이 확인됐습니다. 따라서 검색 첫 화면부터 실제 UI 입력 방식으로 변경했습니다.

## 주의

- API Key는 필요 없습니다.
- Google Flights는 공개 개발자 API가 아니므로 UI/DOM 변경 가능성이 있습니다.
- 개인 Edge/Chrome 프로필을 연결하지 마세요. 전용 profile만 사용합니다.
- 실제 구매 전에는 판매처에서 최종 가격/수하물/환불조건을 다시 확인해야 합니다.
