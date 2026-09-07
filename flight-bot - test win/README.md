# Windows Naver Flights SSE test

Windows에서는 브라우저 없이 Naver Flights SSE 응답을 직접 검증합니다.

고정 실조회 조건:

```text
CJJ -> TPE -> CJJ
2026-09-18 ~ 2026-09-20
성인 1명 / 이코노미 / 직항 / 왕복
```

## 1. 가격/항공편 실조회

더블클릭:

```text
02-NAVER-flight-test.bat
```

`.venv-provider-poc`이 없으면 테스트용 Python 환경을 자동 준비합니다.

성공 시 핵심 출력:

```text
POC_STATUS=PASS
source=NAVER_SSE_API
direct_candidate_count=...
lowest_direct_price=...
candidate_1=...
  outbound=항공사 편명 | 시간 -> 시간
  return=항공사 편명 | 시간 -> 시간
...
```

가능한 왕복 조합을 가격순으로 정렬하며 기본 출력은 TOP 5입니다.

진단 자료:

```text
artifacts\naver-flight-poc\response.sse.txt
artifacts\naver-flight-poc\response.json
artifacts\naver-flight-poc\diagnostics.json
artifacts\naver-flight-poc\result.json
```

## 2. Naver SSE -> Telegram 실제 푸시

더블클릭:

```text
03-NAVER-TELEGRAM-E2E.bat
```

처음 실행하면 `telegram-test.env`를 만들고 메모장으로 엽니다.

```text
TELEGRAM_BOT_TOKEN=본인_봇토큰
TELEGRAM_ALLOWED_CHAT_IDS=본인_CHAT_ID
```

저장하고 같은 BAT를 다시 실행합니다.

진행 순서:

```text
Telegram bot/chat 확인
-> Naver Flights SSE 실조회
-> 왕복 조합 가격순 TOP 5 구성
-> 가는편/오는편 항공사·편명·시간 포함
-> Telegram 테스트 메시지 1회 전송
```

성공 시:

```text
E2E_STATUS=PASS
source=NAVER_SSE_API
telegram_message_sent=True
```

실조회가 실패하면 Telegram 메시지는 보내지 않습니다.

## 수동 준비

필요할 때만:

```text
01-setup-and-unit-test.cmd
```

현재 Windows 테스트 파일:

```text
01-setup-and-unit-test.cmd
02-NAVER-flight-test.bat
03-NAVER-TELEGRAM-E2E.bat
telegram-test.env.example
setup-and-unit-test.ps1
```
