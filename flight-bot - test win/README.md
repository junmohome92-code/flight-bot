# flight-bot - test win

Windows 10/11 PowerShell에서 현재 `flight-bot` 소스를 그대로 사용해 Playwright + Chromium과 CJJ↔TPE 실가격을 검증하는 전용 테스트 디렉토리입니다.

이 디렉토리는 봇 코드를 복제하지 않습니다. 한 단계 위의 실제 프로젝트 소스를 설치해서 테스트하므로 Linux/WSL/Windows가 같은 코드를 검증합니다.

## 가장 쉬운 방법

탐색기에서 이 폴더의 `01-setup-and-unit-test.cmd`를 먼저 실행한 뒤, `02-live-cjj-tpe-visible.cmd`를 실행하세요.

첫 파일은 다음을 자동 수행합니다.

```text
Windows용 가상환경 .venv-win 생성
→ 프로젝트 + 테스트 의존성 설치
→ Playwright Chromium 설치
→ pytest 실행
```

두 번째 파일은 실제 Chromium 창을 띄워 다음 조건으로 Google Flights를 조회합니다.

```text
CJJ (청주) → TPE (타이베이)
2026-09-18 ~ 2026-09-20
성인 1명 / Economy / KRW
경유·별도티켓 허용
```

성공하면 콘솔에 JSON 결과가 출력되고 `artifacts/live-smoke-win/`에 디버그 스크린샷이 저장됩니다.

## PowerShell에서 직접 실행

프로젝트 루트가 `C:\work\flight-bot`이라고 가정하면:

```powershell
cd 'C:\work\flight-bot\flight-bot - test win'
.\setup-and-unit-test.ps1
.\live-cjj-tpe.ps1
```

브라우저를 화면에 띄우지 않으려면:

```powershell
.\live-cjj-tpe.ps1 -Headless
```

## 기대 결과

사용자 일반 브라우저에서 같은 조건으로 확인했던 Google Flights 최저가는 약 33만 원대였습니다. 가격은 실시간으로 변할 수 있으므로 정확히 같은 숫자를 강제하지 않습니다. 테스트는 Google Flights가 실제 KRW 운임을 반환하고 봇이 이를 정상적으로 파싱하는지를 확인합니다.

`Price unavailable`이 나오면 Google이 해당 IP/세션에 운임을 제공하지 않은 것입니다. GitHub hosted runner에서는 이 현상이 실제 확인됐지만, 가정용 Windows/WSL IP에서는 별도로 확인해야 합니다.

## 주의

- `.venv-win`은 Windows 전용 가상환경이라 Git에 커밋되지 않습니다.
- API Key는 필요 없습니다.
- Chromium은 테스트용으로 로컬에 설치됩니다.
- 테스트가 끝나도 기존 Linux/WSL 프로젝트 파일은 변경하지 않습니다.
