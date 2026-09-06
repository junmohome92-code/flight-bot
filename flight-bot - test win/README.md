# flight-bot - test win

Windows 10/11에서 `flight-bot`을 쉽게 검증하는 전용 폴더입니다.

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

이미 같은 폴더에서 `.venv-win`을 유지하고 있고 dependency 변경이 없다면 매번 실행할 필요는 없습니다.

## 2. 실제 Google Flights 가격 수집 테스트

```text
02-live-cjj-tpe-visible.cmd
```

현재 acceptance 범위:

```text
CJJ → TPE → CJJ
2026-09-18 ~ 2026-09-20
왕복 / 성인 1명 / Economy / KRW
Cheapest 선택
→ 필요한 refresh/recovery
→ 직항만 수집
→ 중복 직항 제거
→ 최저가 + 추가 직항 후보 표시
→ Google Flights 검색결과 URL 1개
→ 종료
```

Booking options, 항공사 결제 페이지, OTA/여행사 페이지에는 들어가지 않습니다.

정상 출력의 핵심:

```text
=== DIRECT GOOGLE RESULTS ===
direct_offer_1=...
direct_offer_2=...

=== SUMMARY ===
connections_in_alert=0
booking_navigation_performed=False
external_checkout_navigation_performed=False
google_flights_result_url=...
acceptance=GOOGLE_RESULTS_DIRECT_ONLY_SINGLE_LINK
```

## 3. 실제 Telegram 알림 테스트 — 추천

```text
03-notification-test-menu.cmd
```

처음 실행할 때 `.env`가 없으면 `.env.example`을 복사해 `.env`를 만들어 줍니다. 아래 3개를 입력한 뒤 다시 실행합니다.

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=...
ADMIN_SECRET=아무_긴_랜덤문자열
```

메뉴는 실행 중인 봇을 자동 탐지합니다. 없으면 선택할 수 있습니다.

```text
1. Windows 로컬 봇 시작
2. Docker Compose 봇 시작
```

그 다음 메뉴:

```text
1. Health / 슬롯 상태
2. 슬롯 1개 목표가 알림 테스트
3. 슬롯 1개 정기알림 테스트
4. 전체 슬롯 일반 가격검색
5. 전체 슬롯 강제 정기알림
6. Telegram 테스트 명령 표시
```

### 가장 쉬운 목표가 알림 테스트

Telegram에서 먼저:

```text
/flight add CJJ TPE 2026-09-18 2026-09-20 999999
```

목표가를 현재 항공권보다 충분히 높게 잡아 첫 테스트에서 조건을 만족시키기 위한 예입니다.

그 뒤 `03` 메뉴에서:

```text
2 → 슬롯 1
```

정상이면 Telegram에:

```text
🔥 목표가 도달
✈️ CJJ → TPE 왕복
...
Google Flights 직항 왕복가
1. ...
2. ...
Google Flights 검색결과: https://www.google.com/travel/flights/search?...
```

이 옵니다.

같은 메뉴 `2 → 슬롯 1`을 다시 실행해도 같은 목표가 설정에서는 `🔥 목표가 도달` 알림이 다시 오지 않아야 정상입니다.

목표가를 다시 설정하면 1회 재활성화됩니다.

```text
/flight target 1 999998
```

### 정기알림 즉시 테스트

실제 오전 08:00까지 기다릴 필요가 없습니다.

```text
03 메뉴
→ 3
→ 슬롯 번호
```

정상이면:

```text
📊 정기 가격 알림
```

이 즉시 옵니다. 이 테스트는 목표가 one-shot 상태를 소모하거나 재무장하지 않습니다.

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

각 가격 검색은 새 BrowserContext를 사용하여 cookies/cache/localStorage/IndexedDB 등 이전 검색 저장공간을 다음 2시간 관측에 넘기지 않습니다.

## Docker 테스트

`.env`를 채운 뒤:

```text
03-notification-test-menu.cmd
→ Docker Compose 시작 선택
```

또는 직접:

```powershell
docker compose up -d --build
```

기본 HTTP 포트는 host loopback에만 노출됩니다.

```text
http://127.0.0.1:8080
```

중지:

```powershell
docker compose down
```

## 파일

```text
01-setup-and-unit-test.cmd      설치 + 전체 단위테스트
02-live-cjj-tpe-visible.cmd     Google Flights 실가격 acceptance
03-notification-test-menu.cmd   로컬/Docker Telegram 알림 E2E 테스트 메뉴
```
