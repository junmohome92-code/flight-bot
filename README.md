# Flight Bot

Ubuntu 서버에 Docker Compose로 배포하는 항공권 최저가 감시봇입니다.

기준 원칙:
- AI는 가격을 만들거나 추측하지 않습니다.
- 실제 가격은 Flight Provider API에서만 가져옵니다.
- `price_verified=false` 가격은 최저가 알림에 사용하지 않습니다.
- Telegram / Discord / Kakao가 동일한 SQLite DB와 검색 정책을 공유합니다.

## 현재 구현 범위

- Docker / Docker Compose
- Python 3.12
- SQLite 영구 볼륨
- APScheduler (기본 08:00 / 20:00, Asia/Seoul)
- 최대 3개 감시 슬롯
- SerpApi Google Flights Provider 골격
  - 1차 검색
  - `departure_token`
  - 귀국편 선택 / `booking_token`
  - Booking Options 판매 가격 비교
  - 검증 가격만 최저가 후보로 사용
- Telegram Bot
- Discord Bot
- Kakao 챗봇 Skill webhook
- `/health` 상태 확인

> **주의:** SerpApi 실제 응답 구조나 계정 플랜에 따라 Booking Options 필드가 달라질 수 있으므로, API 키 입력 후 실제 응답으로 adapter 검증이 필요합니다.

## 명령어

```text
/flight add CJJ TPE 2026-10-21 2026-10-25 nonstop
/flight list
/flight check 1
/flight pause 1
/flight resume 1
/flight delete 1
/help
```

현재 자연어 AI 파서는 설정 자리만 마련되어 있고 아직 연결하지 않았습니다. 먼저 명시적 명령으로 Provider/알림 흐름을 안정화한 뒤 Gemini/Groq/OpenRouter 중 하나를 붙이는 것을 권장합니다.

## Ubuntu 서버 배포

```bash
# 1) 저장소 복제
# git clone = GitHub 저장소를 서버로 복사
git clone https://github.com/junmohome92-code/flight-bot.git

# 2) 프로젝트 폴더 이동
# cd = change directory
cd flight-bot

# 3) 환경변수 파일 생성
# cp = copy
cp .env.example .env

# 4) API 키 입력
nano .env

# 5) 이미지 빌드 + 백그라운드 실행
# up = 서비스 실행, -d = detached/background, --build = 이미지 재빌드
docker compose up -d --build

# 6) 상태 확인
# ps = 실행 중인 compose 서비스 목록
docker compose ps

# 7) 로그 확인
# logs = 로그, -f = 실시간 follow
docker compose logs -f flight-bot
```

브라우저 또는 curl에서:

```bash
curl http://127.0.0.1:8080/health
```

## `.env`에서 나중에 입력할 값

### 필수: 항공권

```env
SERPAPI_API_KEY=
```

### Telegram

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS=
```

`TELEGRAM_ALLOWED_CHAT_IDS`는 쉼표로 여러 개 지정할 수 있습니다. 비워두면 토큰에 접근 가능한 모든 채팅의 명령을 받으므로 개인 운영에서는 채우는 것을 권장합니다.

### Discord

```env
DISCORD_BOT_TOKEN=
DISCORD_ALLOWED_CHANNEL_IDS=
```

Discord Developer Portal에서 **Message Content Intent**를 활성화해야 현재 텍스트 명령 방식이 동작합니다.

### Kakao

```env
KAKAO_SKILL_SECRET=
KAKAO_ALLOWED_USER_IDS=
```

Kakao 챗봇 관리자센터의 Skill URL은 외부에서 HTTPS로 접근 가능한 다음 주소로 연결합니다.

```text
https://YOUR_DOMAIN/kakao/skill
```

현재 구현된 Kakao 연동은 **사용자가 카카오톡에서 질문/명령을 보내고 Skill 서버가 답하는 방식**입니다.

예약 스케줄에 따라 서버가 먼저 카카오톡으로 가격 하락 알림을 보내는 기능은 일반 Skill webhook만으로 처리하지 않습니다. 이 기능은 카카오 비즈메시지/알림톡 발송 계약 또는 해당 발송 공급자 API가 확정되면 `Notifier` adapter에 추가합니다. Telegram/Discord 예약 알림은 현재 구조에서 직접 발송 가능합니다.

## 데이터 저장

SQLite 파일은 컨테이너 내부 `/data/flight_bot.db`에 있고 Docker named volume `flight_bot_data`에 보존됩니다.

컨테이너를 다시 만들어도 볼륨을 삭제하지 않는 한 데이터는 유지됩니다.

## 스케줄

기본값:

```env
TIMEZONE=Asia/Seoul
CHECK_HOURS=8,20
```

즉 매일 한국시간 08:00 / 20:00에 활성 슬롯을 검사합니다.

가격이 이전 검증 가격보다 낮아지면 해당 슬롯을 만든 Telegram/Discord 채널에 알립니다. 최초 검증 가격도 기준 가격을 만들기 위해 한 번 알림으로 기록합니다.

## 구조

```text
flight-bot/
├── compose.yaml
├── Dockerfile
├── .env.example
├── pyproject.toml
└── src/flight_bot/
    ├── __main__.py       # FastAPI + scheduler + bot lifecycle
    ├── channels.py       # Telegram / Discord adapters
    ├── config.py         # .env settings
    ├── db.py             # SQLite
    ├── models.py         # domain models
    ├── providers.py      # SerpApi adapter
    └── service.py        # shared command/search/alert core
```

## 다음 구현 순서

1. 실제 `SERPAPI_API_KEY`로 CJJ → TPE 테스트
2. Booking Options 실제 JSON과 adapter 필드 대조
3. Telegram Bot 연결 테스트
4. Discord Bot 연결 테스트
5. Kakao Skill HTTPS endpoint 연결
6. 자연어 parser 추가 (AI는 JSON 파싱만)
7. 수하물 정보 검증 강화
8. Provider fallback 추가
9. Kakao 능동 알림이 필요하면 알림톡/비즈메시지 provider adapter 추가

## 보안

- `.env`는 `.gitignore` 대상입니다.
- 실제 API 키/봇 토큰은 GitHub에 커밋하지 마세요.
- Kakao Skill endpoint는 가능하면 reverse proxy에서 HTTPS를 사용하세요.
- 허용 chat/channel/user ID를 설정해 개인용 봇으로 제한하세요.
