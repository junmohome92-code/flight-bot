# Windows Naver Flights test

현재는 Naver Flights만 검증합니다.

고정 조건:

```text
CJJ -> TPE -> CJJ
2026-09-18 ~ 2026-09-20
성인 1명 / 일반석 / 직항만
```

예약/결제 페이지로 이동하지 않습니다.

## 1. Naver 가격 추출 테스트

더블클릭:

```text
02-NAVER-flight-test.bat
```

`.venv-provider-poc`이 없으면 자동으로 준비합니다.

성공 시:

```text
POC_STATUS=PASS
direct_candidate_count=1 이상
lowest_visible_direct_price=...
booking_navigation_performed=False
```

실패 시 자료:

```text
artifacts\naver-flight-poc\page.png
artifacts\naver-flight-poc\page.txt
artifacts\naver-flight-poc\page.html
artifacts\naver-flight-poc\diagnostics.json
artifacts\naver-flight-poc\result.json
```

## 2. Naver -> Telegram 실제 푸시 테스트

더블클릭:

```text
03-NAVER-TELEGRAM-E2E.bat
```

처음 실행하면:

```text
telegram-test.env
```

파일을 자동 생성하고 메모장으로 엽니다.

두 줄만 입력하세요.

```text
TELEGRAM_BOT_TOKEN=본인_봇토큰
TELEGRAM_ALLOWED_CHAT_IDS=본인_CHAT_ID
```

저장하고 같은 BAT를 다시 실행합니다.

진행 순서:

```text
Telegram bot/chat 사전 확인
-> Naver Flights 실제 검색
-> 신뢰할 수 있는 직항 결과 행 추출
-> Telegram 테스트 메시지 1회 전송
-> 종료
```

성공 시:

```text
E2E_STATUS=PASS
telegram_message_sent=True
booking_navigation_performed=False
```

신뢰할 수 있는 항공편 행을 추출하지 못하면 Telegram 메시지를 보내지 않습니다.

## 수동 준비

필요할 때만:

```text
01-setup-and-unit-test.cmd
```

## 현재 파일

```text
01-setup-and-unit-test.cmd        선택: 수동 준비
02-NAVER-flight-test.bat          Naver 실검색/가격 추출
03-NAVER-TELEGRAM-E2E.bat         Naver -> Telegram 실제 푸시
telegram-test.env.example         Telegram 테스트용 템플릿
setup-and-unit-test.ps1           공통 준비
```

실제 probe:

```text
scripts\naver_flight_probe.py
scripts\naver_telegram_e2e.py
```
