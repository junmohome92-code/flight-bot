# Flight Bot v0.2 — Google Flights 직접 감시

개인 Ubuntu/WSL 홈서버에서 Docker로 실행하는 항공권 가격 감시봇입니다.

## v0.2 핵심 변경

SerpApi 중심 구조를 제거했습니다. 실제 Google Flights 브라우저 화면과 가격 차이가 크게 나는 사례(CJJ→TPE, 2026-09-18~20)가 확인되어, 현재 Primary Provider는 **Playwright + headless Chromium으로 Google Flights를 직접 렌더링**합니다.

`fast-flights`는 가격 공급자가 아니라 Google의 `tfs` 검색 URL을 생성하는 용도로만 사용합니다. Google Flights 검색에서 separate-ticket / self-transfer 결과를 숨기지 않습니다.

## 동작 구조

```text
APScheduler (기본 08:00 / 20:00 Asia/Seoul)
  -> Slot 1 -> Chromium 검색 -> DB 저장/목표가 판정
  -> Slot 2 -> Chromium 검색 -> DB 저장/목표가 판정
  -> Slot 3 -> Chromium 검색 -> DB 저장/목표가 판정

동시 Chromium 검색은 하지 않고 순차 실행합니다.
```

- 저장 슬롯은 **정확히 3개(1, 2, 3)** 입니다.
- `pause`도 슬롯을 차지합니다. `delete`해야 번호가 비며 다음 `add`에서 재사용됩니다.
- 각 슬롯은 `target_price`를 필수로 가집니다.
- 목표가 이하에 새로 진입하면 한 번만 알립니다.
- 계속 목표가 이하라면 반복 알림하지 않습니다.
- 목표가 위로 다시 올라가면 `ARMED`로 재무장되고, 이후 다시 내려올 때 새 알림이 가능합니다.
- 알림 전송 코드는 Provider를 호출하지 않습니다.
- SQLite는 WAL 모드로 사용합니다.

## 가격의 두 단계

1. **Google 표시가**: 검색 결과 화면에 렌더링된 왕복 가격의 최저값.
2. **Booking 검증가**: ARMED 상태에서 표시가가 목표가 이하일 때만 출국편/귀국편을 선택해 Booking 화면의 `Lowest total price` 검증을 시도합니다.

기본값 `REQUIRE_VERIFIED_ALERTS=true`에서는 Booking 검증에 성공한 경우에만 목표가 알림을 보냅니다. 화면 가격은 검증 실패 여부와 관계없이 history에 저장됩니다.

## 명령어

```text
/flight add CJJ TPE 2026-09-18 2026-09-20 350000
/flight add CJJ TPE 2026-09-18 2026-09-20 350000 nonstop
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
```

`nonstop`을 생략하면 경유/혼합/별도티켓 조합을 허용합니다.

## Docker 실행

```bash
cp .env.example .env          # 환경설정 파일 생성
docker compose build          # Chromium 포함 이미지 빌드
docker compose up -d          # -d = detached, 백그라운드 실행
docker compose logs -f        # 실시간 로그 확인
```

Chromium의 `/dev/shm` 부족을 피하기 위해 Compose에 `shm_size: 1gb`를 지정했습니다. 브라우저는 검색마다 하나만 실행하며 슬롯은 순차 처리합니다.

## 환경설정

```env
CHECK_HOURS=8,20
BROWSER_HEADLESS=true
BROWSER_TIMEOUT_MS=45000
BROWSER_BLOCK_ASSETS=true
GOOGLE_CURRENCY=KRW
GOOGLE_GL=kr
REQUIRE_VERIFIED_ALERTS=true
```

문제 분석 시에만 `BROWSER_DEBUG_DIR=/debug`를 켜면 스크린샷을 저장합니다.

## 채널

- Telegram: 조회/명령/능동 알림 지원
- Discord: 조회/명령/능동 알림 지원
- Kakao Skill: 현재 요청→응답 webhook만 지원
- Kakao 능동 알림은 별도 BizMessage/AlimTalk 연동이 필요합니다.

## CJJ ↔ TPE 검증 시나리오

```text
출발: CJJ (청주)
도착: TPE (타오위안/타이베이)
출국: 2026-09-18
귀국: 2026-09-20
성인: 1
좌석: Economy
통화: KRW
경유/별도티켓: 허용
```

로컬/WSL에서:

```bash
pip install -e .
python -m playwright install chromium
BROWSER_DEBUG_DIR=artifacts/live-smoke python scripts/live_smoke.py
```

GitHub Actions의 `cjj-tpe-live-smoke` job도 같은 조건으로 실제 Google Flights를 호출합니다. Google이 CI IP를 CAPTCHA로 막으면 테스트는 실패하고 스크린샷 artifact를 남깁니다. 이 경우 WSL/Ubuntu 서버에서 동일 스크립트로 재검증합니다.

## 테스트

```bash
pip install -e '.[dev]'
pytest -q
```

테스트 범위: KRW 가격 파싱, 고정 슬롯 1/2/3, pause 점유, delete 후 번호 재사용, SQLite WAL, 목표가 latch/re-arm, ALERTED 상태의 상세검증 억제.

## 주의사항

Google Flights는 공개 개발자 API가 아닙니다. UI/DOM 변경, CAPTCHA, IP 제한으로 scraper가 깨질 수 있습니다. Provider 로직과 봇/DB/알림 로직을 분리해 DOM 변경 시 `providers.py`를 집중 수정할 수 있게 했습니다.

실제 구매 전에는 Google Flights/판매처에서 가격, 수하물, 환불/변경 조건을 다시 확인하세요. 위탁수하물 정보가 확인되지 않으면 봇은 `없음`이라고 추정하지 않고 `정보 확인 불가`로 표시합니다.
