# Windows Naver Flights test

현재는 Naver Flights SSE API 경로만 검증합니다.

고정 조건:

```text
CJJ -> TPE -> CJJ
2026-09-18 ~ 2026-09-20
성인 1명 / 일반석 / 직항만
```

브라우저 DOM을 파싱하지 않고 네이버 항공권 SSE 응답에서 가격/편명/시간을 읽습니다. 예약/결제 페이지로 이동하지 않습니다.

## 1. Naver 가격 추출 테스트

더블클릭:

```text
02-NAVER-flight-test.bat
```

`.venv-provider-poc`이 없으면 자동으로 준비합니다.

성공 시:

```text
POC_STATUS=PASS
source=NAVER_SSE_API
direct_candidate_count=1 이상
lowest_direct_price=...
naver_advertised_lowest_direct=...
booking_navigation_performed=False
```

실패 시 자료:

```text
artifacts\naver-flight-poc\response.sse.txt
artifacts\naver-flight-poc\response.json
artifacts\naver-flight-poc\diagnostics.json
artifacts\naver-flight-poc\result.json
```

## 2. Naver -> Telegram 실제 푸시 테스트

더블클릭:

```text
03-NAVER-TELEGRAM-E2E.bat
```

처음 실행하면 `telegram-test.env`를 자동 생성하고 메모장으로 엽니다.

```text
TELEGRAM_BOT_TOKEN=본인_봇토큰
TELEGRAM_ALLOWED_CHAT_IDS=본인_CHAT_ID
```

저장하고 같은 BAT를 다시 실행합니다.

진행 순서:

```text
Telegram bot/chat 사전 확인
-> Naver Flights SSE API 실제 조회
-> 직항 왕복 가격/편명/시간 추출
-> Telegram 테스트 메시지 1회 전송
-> 종료
```

성공 시:

```text
E2E_STATUS=PASS
source=NAVER_SSE_API
telegram_message_sent=True
booking_navigation_performed=False
```

유효한 항공권 행을 만들지 못하면 Telegram 메시지를 보내지 않습니다.

## 수동 준비

필요할 때만:

```text
01-setup-and-unit-test.cmd
```

## 현재 파일

```text
01-setup-and-unit-test.cmd        선택: 수동 준비
02-NAVER-flight-test.bat          Naver 실조회/가격 추출
03-NAVER-TELEGRAM-E2E.bat         Naver -> Telegram 실제 푸시
telegram-test.env.example         Telegram 테스트용 템플릿
setup-and-unit-test.ps1           공통 준비
```

실제 probe:

```text
scripts\naver_flight_probe.py
scripts\naver_telegram_e2e.py
```
