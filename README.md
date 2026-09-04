# Flight Bot v0.2 — Google Flights 가격 감시

개인 Ubuntu/WSL 홈서버에서 Docker로 실행하는 항공권 가격 감시봇입니다.

## 현재 상태 — 2026-09-04

봇/DB/알림 구조는 동작하지만 **Google Flights 실가격 Provider는 migration gate 진행 중**입니다.

기존 SerpApi는 실제 Google Flights 브라우저 가격과 큰 차이가 확인되어 Primary 후보에서 제거했습니다. 이후 세 가지 직접 접근을 검증했습니다.

```text
1. Playwright + Google tfs 직링크
   → 노선/날짜/항공편 목록은 맞음
   → GitHub hosted runner와 사용자 Windows 일반 회선 모두 Price unavailable

2. fast-flights 3.1 parser / raw payload
   → parser는 현재 payload에서 IndexError
   → raw payload에서 RF511/ZE781 등 일부 직항 후보는 가격 대신 다음 단계 token만 반환
   → 독립 편도 검색의 가격 붙은 결과는 대한항공 다중 경유편으로, 원하는 왕복 최저가와 불일치

3. punitarani/fli direct service API
   → 최신 GitHub source의 round-trip expansion + GetBookingResults까지 검증
   → CJJ↔TPE 2026-09-18~20에서 no round-trip results
   → upstream에도 일반 노선이 no results가 되는 동일 계열 이슈 존재
   → 브라우저 BotGuard가 없으면 OTA/리셀러 Booking 결과도 축소되는 upstream 보고 존재
```

따라서 **HTTP-only / tfs 직링크 방식은 현재 Primary 후보에서 제외**했습니다.

현재 acceptance 후보는 `scripts/google_ui_probe.py`입니다. 이 방식은 Google Flights 첫 화면을 실제 브라우저로 열고 출발지/도착지/날짜를 UI에 직접 입력한 뒤, 생성된 search URL을 fresh tab에서 다시 엽니다.

Windows visible 테스트는 **native Microsoft Edge + 전용 persistent profile**을 사용합니다. 개인 브라우저 프로필은 건드리지 않고 `artifacts/google-profile-win/`을 사용합니다.

2026-09-04 사용자 Windows에서 **fresh tab의 실제 KRW 가격 렌더링은 성공**했습니다. 다만 UI가 한국어 `추천` / `최저가` 탭으로 렌더링됐고 기존 영문 exact selector가 `최저가` 탭을 누르지 못해 추천 가격을 최저가로 오판했습니다. 현재 코드는 `Cheapest`와 `최저가`를 모두 인식하고 탭 광고 가격과 row parser 최저가까지 교차검증하도록 보강했습니다.

**중요:** 현재 runtime `providers.py`는 아직 기존 v0.2 tfs URL Provider입니다. `CHEAPEST_PRICE_VISIBLE_AFTER_FRESH_TAB`이 사용자 Windows에서 확인된 뒤 runtime Provider migration을 시작합니다.

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

`01`:

```text
Python 3.12 확인/설치
→ .venv-win 생성
→ 의존성 설치
→ Playwright Chromium 설치
→ pytest
```

`02`:

```text
Google Flights 첫 화면
→ CJJ 입력
→ TPE 입력
→ 2026-09-18 / 2026-09-20 입력
→ Search
→ generated_search_url 저장
→ 동일 browser context에 fresh NEW tab 생성
→ generated_search_url fresh navigation
→ Cheapest / 최저가 탭 탐색 및 클릭
→ 탭에 표시된 advertised cheapest 추출
→ More flights / 항공편 더보기 필요 시 확장
→ flight-row에 붙은 KRW 가격만 수집
→ advertised cheapest와 row parser 최저가 교차검증
```

페이지 전체에서 보이는 원화 숫자의 최소값을 fallback으로 사용하지 않습니다.

현재 중간 증거:

```text
render_gate=PRICE_VISIBLE_AFTER_FRESH_TAB
```

이 값은 fresh tab에서 실제 가격이 렌더링됐다는 뜻일 뿐 최저가 acceptance 완료를 의미하지 않습니다.

최종 성공 판정:

```text
generated_search_url=...
=== FRESH TAB ATTEMPT N ===
fresh_url=...
cheapest_tab_found=True
cheapest_tab_clicked=True
cheapest_advertised=... KRW
price_candidates=...
cheapest_row_lowest=... KRW
cheapest_price_match=True
=== SUMMARY ===
fresh_tab_attempt=N
ui_lowest=... KRW
acceptance=CHEAPEST_PRICE_VISIBLE_AFTER_FRESH_TAB
```

가격은 실시간으로 변하므로 특정 금액을 강제하지 않습니다. 사용자 화면에서는 같은 조건으로 `최저가 ₩338,121부터`가 관찰된 적이 있습니다.

디버그 파일:

```text
artifacts/google-ui-win/generator-tab.{png,txt,html}
artifacts/google-ui-win/fresh-tab-N.{png,txt,html}
artifacts/google-ui-win/fresh-tab-N-error.{png,txt,html}
artifacts/google-ui-win/final-error.{png,txt,html}
```

실패 시 URL, `navigator.webdriver`, language, timezone, Footer Language/Location/Currency와 body/HTML/screenshot을 확인합니다.

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

runtime Provider를 persistent UI 방식으로 교체할 때 browser profile 설정을 `.env.example`에 정식 반영할 예정입니다.

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

1차 acceptance는 fresh tab에서 `Cheapest/최저가` 탭의 실제 flight-row scoped observed lowest price를 읽고, 탭에 광고된 lowest와 일관됨을 확인하는 것입니다.

2차 acceptance는 그 후보를 선택해 귀국편/Booking 단계까지 내려가 **실제 판매 가능한 최종 가격**을 검증하는 것입니다.

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

실제 Google Flights acceptance는 데이터센터 IP와 headed/native Edge 조건 때문에 GitHub hosted runner의 성공 조건으로 사용하지 않습니다. 사용자 Windows에서 `02-live-cjj-tpe-visible.cmd`로 검증합니다.

## 테스트 범위

```bash
pip install -e '.[dev]'
python -m compileall -q src scripts tests
pytest -q
```

현재 unit test 범위: KRW 가격 파싱, Google UI probe row-scope/localized cheapest-tab/diagnostic helper, 고정 슬롯 1/2/3, pause 점유, delete 후 번호 재사용, SQLite WAL, 목표가 latch/re-arm, ALERTED 상태의 상세검증 억제.

## 주의사항

Google Flights는 공개 개발자 API가 아닙니다. UI/DOM 변경, CAPTCHA, IP/session 제한으로 자동화가 깨질 수 있습니다. 가격을 못 읽었을 때 가짜 값이나 `0원`을 만들지 않고 실패로 처리하는 정책을 유지합니다.

위탁수하물 정보가 확인되지 않으면 `없음`이라고 추정하지 않고 `정보 확인 불가`로 표시합니다.

새 채팅에서 이어갈 때는 `docs/HANDOFF_NEW_CHAT.md`와 `docs/PROJECT_STATUS.md`를 먼저 읽으세요.
