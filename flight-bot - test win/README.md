# flight-bot - test win

Windows 10/11에서 `flight-bot`을 실제 Google Flights + Telegram까지 검증하는 전용 폴더입니다.

## 중요한 호환성 원칙

`03-notification-test-menu.cmd`는 Windows 기본 `powershell.exe`(Windows PowerShell 5.1)에서도 동작해야 합니다.

그래서 실제 실행되는 `notification-test-menu.ps1`은 **ASCII-only**로 유지합니다. GitHub의 BOM 없는 UTF-8 `.ps1`에 한글 문자열을 직접 넣으면 Windows PowerShell 5.1이 ANSI로 잘못 읽어 문법 오류를 만들 수 있기 때문입니다.

CI에서 아래를 모두 검사합니다.

```text
Windows PowerShell 5.1 parse
PowerShell 7 parse
notification menu ASCII-only
.cmd -> canonical .ps1 파일명 일치
legacy/v2 중복 메뉴 파일 없음
```

## 1. 최초 설치 / 전체 테스트

최신 ZIP을 새 폴더에 받은 경우 먼저 실행합니다.

```text
01-setup-and-unit-test.cmd
```

하는 일:

```text
Python 3.12 확인
→ .venv-win 생성
→ dependency 설치
→ Playwright Chromium 설치
→ 전체 pytest 실행
```

## 2. Google Flights 가격 수집 acceptance

```text
02-live-cjj-tpe-visible.cmd
```

현재 acceptance:

```text
CJJ → TPE → CJJ
2026-09-18 ~ 2026-09-20
왕복 / 성인 1명 / Economy / KRW

Cheapest 실제 선택
→ 강제 full reload 1회
→ Price unavailable이면 추가 recovery reload 최대 2회
→ Cheapest 선택상태 재확인
→ 직항만 수집
→ 중복 제거
→ 최저가 + 추가 직항 후보
→ Google Flights 검색결과 URL 1개
→ 종료
```

Booking/항공사 결제/OTA 페이지는 들어가지 않습니다.

## 3. 실제 Telegram 알림 E2E 테스트

```text
03-notification-test-menu.cmd
```

`.env`에 최소 아래 3개가 필요합니다.

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=...
ADMIN_SECRET=test123456789
```

테스트 메뉴는 시작 전에 다음을 자동 검사합니다.

```text
.env 필수값
Telegram bot token 연결
Telegram chat ID 접근 가능 여부
HTTP 포트 충돌
기존 실행 중인 봇이 최신 runtime contract인지
provider = google-playwright-results-observed-accepted-flow
Cheapest forced reload = true
Price unavailable recovery reloads = 2
검색 저장공간 격리 = true
검색 주기 = 2시간
실제 슬롯 한도 = 10
admin endpoint 활성화
```

오래된 ZIP/오래된 Docker 컨테이너가 8080 포트를 잡고 있으면 **그 상태에 붙어서 잘못 테스트하지 않고 중단**합니다.

### 실행 모드

봇이 실행 중이 아니면:

```text
1. LOCAL Windows runtime
   - 브라우저가 보임
   - 테스트 전용 DB: artifacts/notification-test.db

2. DOCKER runtime
   - headless
   - DB: /data/flight_bot.db
   - debug: /debug
```

Docker Compose는 컨테이너 안에서 아래 값을 강제로 고정합니다.

```text
DATABASE_PATH=/data/flight_bot.db
BROWSER_HEADLESS=true
BROWSER_DEBUG_DIR=/debug
```

따라서 Windows 테스트용 `.env` 값을 그대로 들고 Docker로 가도 host 경로나 headed-browser 설정이 컨테이너를 깨뜨리지 않습니다.

## 4. Google + Microsoft Edge 원인분리 테스트

```text
04-test-google-msedge.cmd
```

이 테스트는 설치된 **Microsoft Edge Stable**을 Playwright `msedge` 채널로 실행합니다.

중요한 점은 브라우저만 Edge로 바꾸고 아래는 production과 동일하게 사용한다는 것입니다.

```text
accepted-tfs-v1 URL
RuntimeGoogleResultsProvider.search()
Cheapest 선택
강제 full reload 1회
Price unavailable recovery 최대 2회
직항 row-scoped 가격 추출
```

따라서 `02`는 성공하고 `03`은 실패하던 상황에서 `04`가 성공하면 bundled Chromium과 Edge의 차이를 강하게 의심할 수 있습니다.

결과/실패 자료:

```text
artifacts/google-msedge-win/
```

## 5. 네이버 항공권 대안 가능성 테스트

```text
05-test-naver-flights.cmd
```

고정 테스트 조건:

```text
청주(CJJ) → 타이베이(TPE)
2026-09-18 ~ 2026-09-20
성인 1명 / 일반석
직항만: isDirect=true
브라우저: Microsoft Edge
```

네이버 결과 페이지까지만 들어가고 **항공편/운임/예약/결제 카드를 클릭하지 않습니다.**

테스트가 확인하는 것:

```text
네이버 결과 페이지가 정상 로딩되는지
원화 가격이 노출되는지
페이지 전체 최소가가 아니라 compact row context에서 가격을 잡을 수 있는지
XHR/fetch URL을 기록해 향후 안정적인 Provider 구현 가능성을 판단할 수 있는지
```

결과/스크린샷/페이지 텍스트/네트워크 기록:

```text
artifacts/naver-flights-win/
```

## 비교 테스트 권장 순서

```text
01-setup-and-unit-test.cmd
↓
02-live-cjj-tpe-visible.cmd        기존 native Edge 기준점
↓
04-test-google-msedge.cmd          Playwright + Edge
↓
05-test-naver-flights.cmd          Naver 대안 POC
↓
03-notification-test-menu.cmd      최종 Telegram E2E는 Provider 방향 결정 후
```

`04`, `05`는 `.env`나 Telegram 설정이 없어도 실행 가능합니다.

## 가장 쉬운 목표가 알림 테스트

LOCAL 모드로 봇을 띄운 뒤 Telegram에서:

```text
/flight add CJJ TPE 2026-09-18 2026-09-20 999999
```

그 다음 메뉴:

```text
2. Test TARGET alert for one slot
Slot number: 1
```

브라우저에서 정상적으로 보여야 하는 순서:

```text
Google Flights
→ Cheapest 선택
→ full reload
→ 필요시 Price unavailable recovery reload
→ Cheapest 재확인
→ 직항 결과 수집
→ 브라우저 종료
```

그리고 Telegram에는 목표가 도달 알림이 1회 와야 합니다.

같은 목표가 설정에서는 두 번째 검색부터 목표가 알림이 반복되지 않습니다. 다시 테스트하려면 Telegram에서 목표가를 바꿔 재무장합니다.

```text
/flight target 1 999998
```

## 정기알림 즉시 테스트

실제 오전 08:00까지 기다릴 필요 없습니다.

```text
3. Test DAILY summary for one slot
Slot number: 1
```

이 테스트는 목표가 one-shot 상태를 소모하거나 재무장하지 않습니다.

## 로그

메뉴의:

```text
4. Show runtime search logs
```

또는 목표가/정기알림 테스트 직후 자동 출력되는 로그에서 아래 순서를 확인합니다.

```text
runtime_stage=cheapest-warmup
runtime_cheapest_clicked=True 또는 이미 selected
runtime_cheapest_selected_full_reload=1
runtime_price_recovery_reload=...   # 필요할 때만
runtime_price_surface=ready
runtime_stage=cheapest-post-reload
runtime_direct_offer_count=...
runtime_lowest_direct_round_trip=...
```

LOCAL 로그:

```text
artifacts/runtime-alert-test/bot.stdout.log
artifacts/runtime-alert-test/bot.stderr.log
```

Docker 로그:

```powershell
docker compose logs --tail 200 flight-bot
```

## 운영 기본값

```text
가격 검색: 2시간마다
정기 가격 알림: 하루 1회, 기본 08:00
목표가 알림: 목표가 설정당 최초 1회
슬롯: 1~10, 총 10개
경유편: 알림에서 제외
표시 직항: 기본 최대 4개, 설정 가능
사용자 링크: Google Flights 검색결과 1개만
```

각 가격 검색은 새 BrowserContext를 사용하여 cookies/cache/localStorage/IndexedDB 등 이전 검색 저장공간을 다음 관측에 넘기지 않습니다.

## 파일

```text
01-setup-and-unit-test.cmd      설치 + 전체 단위테스트
02-live-cjj-tpe-visible.cmd     Google Flights native Edge acceptance
03-notification-test-menu.cmd   실제 Telegram 알림 E2E 테스트
04-test-google-msedge.cmd       Google production Provider + Playwright msedge
05-test-naver-flights.cmd       Naver Flights direct-results viability POC
notification-test-menu.ps1      03의 canonical PowerShell 스크립트 (ASCII-only)
```

`notification-test-menu-v2.ps1` 같은 병렬/legacy 메뉴는 두지 않습니다. 테스트 진입점은 하나만 유지합니다.
