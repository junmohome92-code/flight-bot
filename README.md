# Flight Bot — Naver Flights E2E POC

현재 단계는 **Naver Flights를 운영 가격 소스로 쓸 수 있는지 Windows에서 실검색 + Telegram 푸시까지 검증**하는 단계입니다.

Skyscanner는 실제 화면에서 bot challenge가 확인되어 후보에서 제외했습니다.

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

검색결과까지만 사용합니다.

```text
Naver Flights 검색결과 진입
→ 화면에 보이는 가격 텍스트 탐색
→ 가격 주변의 실제 항공편 결과 문맥 확인
→ 직항 후보 최대 4개 정리
→ 필요 시 Telegram 테스트 메시지 전송
→ 종료
```

예약/결제 페이지로 이동하지 않습니다.

## Windows 테스트

### 1. Naver 가격 추출만 확인

더블클릭:

```text
flight-bot - test win\02-NAVER-flight-test.bat
```

최초 실행이면 전용 환경 `.venv-provider-poc`을 자동 생성합니다.

성공 기준:

```text
POC_STATUS=PASS
direct_candidate_count=1 이상
lowest_visible_direct_price=...
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
telegram_message_sent=True
booking_navigation_performed=False
```

Telegram에는 `🧪 네이버 항공권 E2E 테스트`로 시작하는 메시지가 실제 전송됩니다. 이 테스트는 첫 번째 Chat ID 한 곳에만 보냅니다.

## 실패 진단 자료

가격 추출 테스트:

```text
artifacts\naver-flight-poc\page.png
artifacts\naver-flight-poc\page.txt
artifacts\naver-flight-poc\page.html
artifacts\naver-flight-poc\diagnostics.json
artifacts\naver-flight-poc\result.json
```

Telegram E2E:

```text
artifacts\naver-telegram-e2e\page.png
artifacts\naver-telegram-e2e\page.txt
artifacts\naver-telegram-e2e\page.html
artifacts\naver-telegram-e2e\diagnostics.json
artifacts\naver-telegram-e2e\result.json
```

현재 extractor는 특정 해시 CSS class 하나에 의존하지 않고, 화면에 보이는 가격 텍스트를 시작점으로 실제 항공편 결과 문맥을 찾습니다. iframe과 open shadow root도 함께 검사합니다. 신뢰할 수 있는 결과 행을 못 찾으면 Telegram을 보내지 않습니다.

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

순서로 진행합니다.
