# Flight Bot — Naver Flights E2E POC

현재 단계는 **Naver Flights를 운영 가격 소스로 쓸 수 있는지 실제 가격 조회 + Telegram 푸시까지 검증**하는 단계입니다.

Skyscanner는 실제 화면에서 bot challenge가 확인되어 후보에서 제외했습니다.

## 현재 Naver 방식

브라우저 DOM/CSS selector를 긁지 않습니다.

```text
flight-api.naver.com/flight/international/searchFlights
POST JSON
Accept: text/event-stream
→ SSE 응답 수집
→ itineraries + fareMappings 결합
→ 직항 왕복 가격/편명/시간 추출
```

2026-09-06 GitHub Actions 실조회에서 고정 테스트 노선의 네이버 표시 최저가와 동일한 `319,620원`을 반환하는 것을 확인했습니다.

## 고정 테스트 조건

```text
출발: CJJ (청주)
도착: TPE (타이베이 타오위안)
출국: 2026-09-18
귀국: 2026-09-20
성인 1명
일반석
직항만
```

예약/결제 페이지로 이동하지 않습니다.

## Windows 테스트

### 1. Naver 가격 추출만 확인

더블클릭:

```text
flight-bot - test win\02-NAVER-flight-test.bat
```

최초 실행이면 전용 환경 `.venv-provider-poc`을 자동 생성합니다.

성공 기준 예시:

```text
POC_STATUS=PASS
source=NAVER_SSE_API
direct_candidate_count=1 이상
lowest_direct_price=...
naver_advertised_lowest_direct=...
booking_navigation_performed=False
```

### 2. Naver → Telegram 실제 푸시 E2E

더블클릭:

```text
flight-bot - test win\03-NAVER-TELEGRAM-E2E.bat
```

처음 실행하면 아래 파일을 자동 생성하고 메모장으로 엽니다.

```text
flight-bot - test win\telegram-test.env
```

두 값만 입력합니다.

```text
TELEGRAM_BOT_TOKEN=본인_봇토큰
TELEGRAM_ALLOWED_CHAT_IDS=본인_CHAT_ID
```

저장 후 `03-NAVER-TELEGRAM-E2E.bat`를 다시 실행합니다.

E2E 성공 기준:

```text
E2E_STATUS=PASS
source=NAVER_SSE_API
telegram_message_sent=True
booking_navigation_performed=False
```

Telegram에는 조회된 가격과 가는편/오는편 편명 및 시간이 실제 전송됩니다. 테스트는 첫 번째 Chat ID 한 곳에만 보냅니다.

## 실패 진단 자료

가격 추출 테스트:

```text
artifacts\naver-flight-poc\response.sse.txt
artifacts\naver-flight-poc\response.json
artifacts\naver-flight-poc\diagnostics.json
artifacts\naver-flight-poc\result.json
```

Telegram E2E도 동일한 형식으로 `artifacts\naver-telegram-e2e\` 아래에 저장합니다.

## 다음 단계

Windows에서 `03-NAVER-TELEGRAM-E2E.bat`까지 통과하면:

```text
Naver 운영 Provider 통합
→ Telegram 등록 UX 개선
→ 목표가 1회 알림 + 일일 요약
→ 10슬롯 / 최대 2개 동시검색
→ Ubuntu Docker 실검색 검증
→ main 병합
```
