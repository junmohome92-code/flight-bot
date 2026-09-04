# Flight Bot v0.2 — Google Flights 가격 감시

개인 Ubuntu/WSL 홈서버에서 Docker로 실행하는 항공권 가격 감시봇입니다.

## 현재 상태 — 2026-09-04

봇/DB/알림 구조는 동작하지만 **Google Flights 실가격 Provider는 migration gate 진행 중**입니다.

기존 SerpApi / fast-flights parser / Fli direct API / 기존 direct tfs 방식은 실제 Google Flights 일반 브라우저 최저가를 신뢰성 있게 재현하지 못해 Primary 후보에서 제외했습니다.

2026-09-04 사용자 Windows에서 generated search URL의 fresh navigation 중 실제 KRW flight-row 가격이 렌더링된 사례가 확인됐고, Google Flights `Cheapest/최저가` 탭에는 약 `₩338,121부터`가 표시됐습니다. 추천 탭을 최저가로 오인하던 selector 문제는 수정했습니다.

하지만 Cheapest 클릭 후 현재 문서는 다시 `Price unavailable`이 되었고, 클릭 후 생성된 `tfu` URL을 또 다른 fresh tab에서 3회 다시 열어도 `price_candidates=0`이었습니다.

**가장 중요한 최신 관찰:** 사용자 화면에서 가격이 로딩 초기에 잠깐 나타났다가 사라졌습니다. 따라서 현재 acceptance는 완성된 DOM을 늦게 읽는 대신, Google 후속 JS가 화면을 `Price unavailable`로 바꾸기 전에 transient flight-row DOM을 캡처하는 방식입니다.

새 probe:

```text
scripts/google_transient_price_probe.py
```

이 probe는 Google page script보다 먼저 `MutationObserver`를 설치하고, 잠깐 나타난 가격 element가 실제 flight-row ancestor에 속하는 경우에만 price/항공사/시간/경유/row text를 메모리에 보존합니다. 페이지 전체 원화 최소값은 사용하지 않습니다.

**중요:** transient 가격은 `observed`일 뿐 `verified/bookable` 가격이 아닙니다. `REQUIRE_VERIFIED_ALERTS=true`는 유지합니다. 현재 runtime `src/flight_bot/providers.py`도 아직 기존 v0.2 Provider이며, live acceptance 전에는 migration 완료로 보지 않습니다.

## 핵심 봇 구조

```text
APScheduler (기본 08:00 / 20:00 Asia/Seoul)
  -> Slot 1 -> Provider 검색 -> DB 저장/목표가 판정
  -> Slot 2 -> Provider 검색 -> DB 저장/목표가 판정
  -> Slot 3 -> Provider 검색 -> DB 저장/목표가 판정
```

검색은 순차 실행합니다.

- 저장 슬롯은 **정확히 3개(1, 2, 3)** 입니다.
- `pause`도 슬롯을 차지합니다. `delete`해야 번호가 비며 다음 `add`에서 재사용됩니다.
- 각 슬롯은 `target_price`를 필수로 가집니다.
- 목표가 이하에 새로 진입하면 한 번만 알립니다.
- 계속 목표가 이하라면 반복 알림하지 않습니다.
- 목표가 위로 다시 올라가면 `ARMED`로 재무장되고, 이후 다시 내려올 때 새 알림이 가능합니다.
- 알림 전송 코드는 Provider를 호출하지 않습니다.
- SQLite는 WAL 모드로 사용합니다.
- `REQUIRE_VERIFIED_ALERTS=true`가 기본입니다.

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

## Windows acceptance test

저장소 안의 `flight-bot - test win` 폴더를 사용합니다.

```text
01-setup-and-unit-test.cmd
02-live-cjj-tpe-visible.cmd
```

`.venv-win`이 이미 있으면 `01`은 다시 실행하지 않아도 됩니다.

현재 `02` 흐름:

```text
native Microsoft Edge + 전용 persistent profile
→ about:blank로 시작
→ CJJ/TPE/2026-09-18~20의 canonical generated URL 재사용
→ Google page script보다 먼저 MutationObserver 설치
→ base fresh document 로드
→ Cheapest / 최저가 클릭
→ transient DOM mutation 즉시 감시
→ 실제 flight-row ancestor가 있는 KRW price만 snapshot
→ 필요 시 Cheapest tfu URL fresh document에서도 같은 방식으로 감시
```

고정 canonical URL 재사용은 acceptance 테스트 속도를 줄이기 위한 진단 전용 최적화입니다. production Provider는 사용자 조건에 맞춰 동적으로 검색해야 합니다.

성공 예:

```text
transition_transient_1=338,xxx KRW | phase=cheapest-transition | ...
```

또는:

```text
cheapest_fresh_transient_1=338,xxx KRW | phase=cheapest-fresh | ...
```

최종:

```text
=== SUMMARY ===
transient_lowest=...
cheapest_advertised=...
observed=TRANSIENT_FLIGHT_ROW_CAPTURED
verified=False
acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE
```

가격은 실시간으로 변하므로 특정 금액을 강제하지 않습니다.

디버그 파일:

```text
artifacts/google-ui-win/*-transient.json
artifacts/google-ui-win/*.png
artifacts/google-ui-win/*.txt
artifacts/google-ui-win/*.html
```

실패 시 URL, `navigator.webdriver`, language, timezone, Footer Language/Location/Currency와 transient JSON/body/HTML/screenshot을 확인합니다.

## Docker 실행

실가격 Provider migration gate가 끝난 뒤 운영 배포를 권장합니다. 현재 기본 실행 방법은 다음과 같습니다.

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose logs -f
```

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

runtime Provider를 최종 browser 방식으로 교체할 때 profile/session 설정을 `.env.example`에 정식 반영할 예정입니다.

## 채널

- Telegram: 조회/명령/능동 알림 지원
- Discord: 조회/명령/능동 알림 지원
- Kakao Skill: 요청→응답 webhook만 지원
- Kakao 능동 알림은 별도 BizMessage/AlimTalk 연동 필요

## CJJ ↔ TPE acceptance 기준

```text
출발: CJJ
도착: TPE
출국: 2026-09-18
귀국: 2026-09-20
성인: 1
좌석: Economy
통화: KRW
경유/혼합/별도티켓: 허용
```

1차 acceptance는 실제 Google Flights가 잠깐이라도 표시한 `Cheapest/최저가` flight-row scoped observed price를 보존하는 것입니다.

2차 acceptance는 그 후보를 실제로 선택해 귀국편/Booking 단계까지 내려가 **판매 가능한 최종 가격**을 검증하는 것입니다.

`observed`와 `verified`를 혼동하지 않습니다.

## CI

일반 push/PR blocking gate:

```text
Linux Python 3.12
  → install
  → compileall src/scripts/tests
  → pytest

Windows Python 3.12
  → install
  → compileall src/scripts/tests
  → pytest
  → Playwright Chromium 실제 launch
```

실제 Google Flights acceptance는 데이터센터 IP 환경에서 가격 row가 내려오지 않는 것이 확인됐으므로 GitHub hosted runner의 blocking gate로 사용하지 않습니다. 사용자 Windows에서 `02-live-cjj-tpe-visible.cmd`로 검증합니다.

## 테스트 범위

```bash
pip install -e '.[dev]'
python -m compileall -q src scripts tests
pytest -q
```

unit test 범위에는 KRW 가격 파싱, Google UI row-scope/localized cheapest-tab, transient candidate filtering, 고정 슬롯 1/2/3, pause 점유, delete 후 번호 재사용, SQLite WAL, 목표가 latch/re-arm 등이 포함됩니다.

## 주의사항

Google Flights는 공개 개발자 API가 아닙니다. UI/DOM 변경, CAPTCHA, IP/session 제한으로 자동화가 깨질 수 있습니다. 가격을 못 읽었을 때 가짜 값이나 `0원`을 만들지 않고 실패로 처리하는 정책을 유지합니다.

위탁수하물 정보가 확인되지 않으면 `없음`이라고 추정하지 않고 `정보 확인 불가`로 표시합니다.

새 채팅에서 이어갈 때는 `docs/HANDOFF_NEW_CHAT.md`와 `docs/PROJECT_STATUS.md`를 먼저 읽으세요.
