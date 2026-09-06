# Flight Bot — Naver Flights SSE

네이버 항공권의 검색 응답을 이용해 **직항 왕복 가격을 감시하고 Telegram/Discord/Kakao 연동 알림을 보내는 self-hosted 봇**입니다.

현재 운영 가격 소스는 **Naver Flights SSE API 하나로 확정**했습니다. 브라우저 자동화, DOM/CSS 파싱, Playwright/Chromium은 사용하지 않습니다.

## 확정된 가격 수집 방식

```text
flight-api.naver.com/flight/international/searchFlights
        ↓ POST JSON
Accept: text/event-stream
        ↓
SSE 이벤트 수집
        ↓
itineraries + fareMappings 결합
        ↓
가는편/오는편 + 항공사 + 편명 + 시간 + 왕복 총액 구성
        ↓
동일 왕복 조합 중복 제거
        ↓
가격 오름차순 TOP 5
```

기본 검색 조건은 다음과 같습니다.

- 성인 1명
- 이코노미
- 직항
- 왕복
- KRW
- 가격순 TOP 5

2026-09-07 Windows 실조회에서 `CJJ → TPE → CJJ`, `2026-09-18 ~ 2026-09-20` 조건으로 HTTP `201`, `text/event-stream`, SSE 20개 이벤트를 정상 수신했고 최저 왕복가 **319,620원**을 확인했습니다. 같은 시점 네이버 항공권 화면 표시 가격과 일치했습니다.

## 가격 데이터 구조

한 왕복 후보는 다음 정보를 가집니다.

```text
왕복 총액
가는편 항공사 / 편명 / 출발시간 / 도착시간
오는편 항공사 / 편명 / 출발시간 / 도착시간
판매 파트너 코드
직항 여부
```

가는편과 오는편의 항공사가 달라도 하나의 왕복 조합으로 취급합니다.

예시:

```text
1. 319,620KRW
   가는편: 이스타항공 ZE781 · 23:40 → 01:10
   오는편: 에어로케이 RF322 · 13:15 → 16:40
```

## 감시/알림 동작

- 감시 슬롯: 최대 10개
- 기본 조회 주기: 2시간
- 목표가 도달 알림: 목표가 설정당 최초 1회
- 일일 요약: 기본 08:00, 해당 정기 조회 결과 재사용
- 메시지에는 가격순 최대 TOP 5 왕복 조합 표시
- 예약/결제/외부 판매처 checkout 검증은 현재 범위 밖

주요 명령:

```text
/flight add CJJ TPE 2026-09-18 2026-09-20 350000
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
/help
```

## Docker 실행

브라우저가 없기 때문에 Chromium 이미지나 shared-memory 설정이 필요하지 않습니다.

```bash
cp .env.example .env
# .env에 Telegram 등 필요한 값 입력

docker compose up -d --build
```

상태 확인:

```bash
docker compose ps
docker compose logs -f flight-bot
curl http://127.0.0.1:8080/health
```

정상 `/health` 예시 핵심값:

```json
{
  "ok": true,
  "provider": "naver-flights-sse",
  "provider_transport": "naver_sse_api",
  "browser_required": false,
  "alert_max_offers": 5
}
```

SQLite 데이터는 Compose named volume `flight_bot_data`에 보존됩니다. 컨테이너를 rebuild해도 감시 슬롯과 이력은 유지됩니다.

## 환경변수

핵심 Naver 설정:

```text
NAVER_API_URL=https://flight-api.naver.com/flight/international/searchFlights
NAVER_API_TIMEOUT_SECONDS=30
NAVER_API_ATTEMPTS=3
NAVER_MIN_REQUEST_INTERVAL_SECONDS=3
ALERT_MAX_OFFERS=5
```

요청 간 최소 간격은 연속 수동 조회가 너무 빠르게 발생하는 것을 막기 위한 안전장치입니다.

## Windows 실조회 테스트

`flight-bot - test win` 폴더에서:

```text
01-setup-and-unit-test.cmd
02-NAVER-flight-test.bat
03-NAVER-TELEGRAM-E2E.bat
```

`02`는 실제 Naver SSE 가격을 조회하고 TOP 5를 콘솔에 출력합니다. `03`은 같은 결과를 Telegram 한 곳에 실제 전송합니다.

## 개발 검증

```bash
python -m pip install -c constraints.txt -e '.[dev]'
pytest -q
python -m compileall -q src scripts

docker build -t flight-bot:test .
```

CI에서도 단위/계약 테스트와 Docker build를 수행하며, Playwright/Chromium 관련 런타임 파일이나 의존성이 다시 들어오지 않는지 검사합니다.

## 현재 아키텍처 경계

```text
Naver SSE API = 유일한 가격 소스
SQLite        = 상태/이력 저장
APScheduler   = 정기 조회
Telegram     = 알림/명령
Discord      = 선택 연동
Kakao Skill  = 선택적 reactive webhook
FastAPI      = health/admin endpoint
Docker       = Ubuntu 홈서버 배포
```

Naver 내부 API 구조가 변경될 경우 요청/응답 계약을 다시 검증해야 합니다. DOM 파싱 fallback은 두지 않습니다.
