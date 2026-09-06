# Flight Bot v0.2 — Google Flights 가격 감시

개인 Ubuntu 홈서버에서 Docker로 실행하는 항공권 가격 감시봇입니다.

## 현재 상태

Bot Core / SQLite / Telegram / Discord / Kakao reactive skill 골격은 구현되어 있습니다.

Google Flights 실가격 Provider는 **migration/acceptance 진행 중**입니다. 사용자 Windows 환경에서 transient 실제 flight-row 가격을 사라지기 전에 잡는 것까지는 확인됐지만, 최종 runtime Provider로 승격하려면 다음 live gate가 다시 통과해야 합니다.

```text
일반 검색 URL
→ 실제 Cheapest/최저가 클릭
→ 안정된 최저 출국 row
→ 실제 pointer click
→ Returning flights
→ 귀국 row
→ Google Booking options
→ 이후 별도 gate에서 외부 판매처 checkout final total
```

외부 판매처 checkout final total 확인 전에는 항상 `verified=False`입니다.

runtime `src/flight_bot/providers.py`는 아직 **legacy unverified Provider**이며 `accepted_for_alerts=False`로 하드 차단되어 있습니다. `REQUIRE_VERIFIED_ALERTS=false`로 바꿔도 이 legacy Provider는 목표가 알림을 보낼 수 없습니다.

## 핵심 요구사항

```text
Python 3.12+
FastAPI / APScheduler
SQLite WAL
Telegram / Discord
Kakao reactive skill
slots = exactly 1/2/3
pause keeps slot occupied
delete frees/reuses slot number
target_price required
REQUIRE_VERIFIED_ALERTS=true
searches and slot mutations globally serialized
never synthesize price/baggage data
unknown baggage = 정보 확인 불가
```

Alert latch:

```text
ARMED
→ verified/eligible price <= target
→ SENDING (external notification side effect in progress)
→ ALERTED
→ price > target
→ ARMED
```

`SENDING`은 process crash 직후 동일 below-target 구간에서 중복 알림을 보내는 것을 막기 위한 at-most-once 상태입니다.

## 슬롯 identity / 동시성

슬롯 번호는 항상 1/2/3이지만 번호 자체를 영구 identity로 신뢰하지 않습니다.

각 슬롯은:

```text
generation = 새 add마다 새로운 UUID
revision   = 설정/상태 변경마다 증가
```

를 가집니다.

검색 중 슬롯을 delete하고 같은 번호를 재사용하는 race를 막기 위해 검색 결과 저장 시 generation/revision을 다시 검증합니다. 같은 process 안에서는 검색과 `add/delete/pause/resume/target`을 하나의 operation lock으로 직렬화합니다.

## observed / Booking / verified 가격

서로 다른 의미를 섞지 않습니다.

```text
observed_price          = Google flight row에 실제 표시된 가격
booking_option_price    = Google Booking options 단계 가격
verified_checkout_price = 외부 판매처 checkout final total
```

DB `offers`에도 세 값을 별도 column으로 보존합니다.

## Google Flights acceptance 구조

공통 순수 계약:

```text
src/flight_bot/google_ui_contract.py
```

Windows active probe:

```text
scripts/google_booking_pointer_probe.py
scripts/google_dom_capture.js
```

### capture lifecycle

DOM observer는 Cheapest 클릭 후에 켜는 방식이 아닙니다. **document 시작부터 항상 동작**합니다.

- DOM node 추가
- aria-label 변경
- `characterData` Text-node 가격 변경
- Cheapest tab selected 상태
- Returning flights marker

를 추적합니다.

Cheapest 클릭 직전 departure phase를 표시하므로 클릭 transition 중 잠깐 나타난 가격도 snapshot으로 남습니다.

출국편 선택이 full navigation을 일으키면 `sessionStorage`의 `returning` phase를 새 document init script가 복구합니다. 따라서 새 문서에서도 observer가 꺼지지 않습니다.

### 최저가 settle gate

`첫 가격 1개가 보였다`만으로 선택하지 않습니다.

출국 선택은:

```text
Cheapest control 실제 selected
+ capture minimum duration
+ Cheapest advertised 가격 안정
+ 실제 flight-row minimum 안정
+ loading 중이면 2개 이상 concrete row
+ advertised price보다 비싼 fallback 금지
```

을 만족해야 합니다.

사람이 보는 Cheapest가 `₩311,811`인데 bot이 `₩384,361` 또는 `₩418,500`만 잡았다면 비싼 값을 대신 선택하지 않고 실패해야 정상입니다.

### pointer safety

DOM `.click()` fallback은 사용하지 않습니다.

transient row에서 보존한 pointer 좌표를 쓰기 전에 `document.elementFromPoint()` 기준으로 현재 그 좌표 아래 DOM이 snapshot의 출발/도착시간 및 route와 같은 flight card인지 다시 확인합니다. layout shift로 다른 row가 들어온 좌표는 클릭하지 않습니다.

### Returning price

Google의 귀국편 선택 화면은 `+₩0`, `+₩25,000` 같은 추가금 형식을 사용할 수 있으므로 returning phase만 0원 floor를 허용합니다. 출국/Booking 총액의 50,000원 plausibility floor와 의미를 분리합니다.

### Booking options

Booking option candidate가 있어도 페이지/화면에 실제 `Booking options` / `예약 옵션` marker가 없으면 성공으로 인정하지 않습니다.

Google Booking option은 외부 판매처 checkout final total이 아니므로 여기까지 성공해도:

```text
external_checkout_verified=False
verified=False
```

입니다.

## 반복하지 않을 실패 경로

- SerpApi Primary
- fast-flights parser를 가격 source로 사용
- punitarani/fli direct API
- Cheapest tfu URL 반복 fresh-open
- page-wide KRW minimum
- broad results container DOM `.click()`
- disappearing source node가 아직 `isConnected`인지 후보 확정 때 다시 요구
- headless Windows live acceptance

`fast-flights`는 현재 legacy runtime의 **URL builder에만** 남아 있고 가격 parser로는 사용하지 않습니다. accepted Provider migration 후 제거 대상입니다.

## Runtime browser

legacy runtime은 매 슬롯마다 Chromium 전체를 재시작하지 않습니다.

```text
src/flight_bot/browser_session.py
```

이 process 단위 browser/context를 재사용합니다. `BROWSER_PROFILE_DIR`을 지정하면 persistent profile을 사용합니다.

단, Windows native Edge acceptance 성공이 Ubuntu Docker Chromium 가격 acceptance를 의미하지는 않습니다. Ubuntu production browser gate는 별도로 남아 있습니다.

## Windows acceptance

최초 1회 또는 dependency 변경 후:

```text
flight-bot - test win\01-setup-and-unit-test.cmd
```

이후:

```text
flight-bot - test win\02-live-cjj-tpe-visible.cmd
```

현재 기준 route:

```text
CJJ → TPE → CJJ
2026-09-18 ~ 2026-09-20
1 adult / Economy / KRW
stops unrestricted
mixed airlines / separate/self-transfer allowed
```

실시간 가격이므로 특정 숫자를 고정 acceptance 값으로 사용하지 않습니다.

자세한 live 출력 설명은 `flight-bot - test win/README.md`를 참고합니다.

## 보안 기본값

Production은 fail-closed입니다.

- Telegram token을 설정하면 `TELEGRAM_ALLOWED_CHAT_IDS` 필수
- Discord token을 설정하면 `DISCORD_ALLOWED_CHANNEL_IDS` 필수
- Kakao secret을 설정하면 `KAKAO_ALLOWED_USER_IDS` 필수
- Kakao secret이 없으면 `/kakao/skill`은 404
- `ADMIN_SECRET`이 없으면 `/admin/check-all`은 404
- Admin secret은 Kakao secret과 분리
- channel command는 해당 platform/owner가 만든 slot만 조작 가능
- Compose HTTP port는 기본적으로 `127.0.0.1`에만 bind

Kakao webhook을 공개해야 한다면 reverse proxy/TLS/auth 구조를 앞에 둡니다.

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Container는 non-root `app` user로 실행하고 healthcheck를 포함합니다.

```text
GET /health
```

Compose의 기본 port binding:

```text
127.0.0.1:8080
```

입니다.

## Dependencies

`pyproject.toml`은 호환 범위를 정의하고, 실제 검증된 dependency graph는:

```text
constraints.txt
```

에 고정합니다.

Windows setup / Linux CI / Windows CI / Docker build 모두 constraints를 사용합니다.

## CI

GitHub Actions는 다음을 검증합니다.

```text
Linux: install + compileall + pytest
Windows: install + compileall + pytest + Playwright Chromium launch
Docker: production image build + non-root check + /health smoke
```

GitHub hosted environment은 Google 실가격 acceptance 환경으로 사용하지 않습니다. 과거 hosted Windows/Azure 환경에서는 실제 flight-row 가격 DOM이 내려오지 않는 것을 확인했습니다.

## 주요 파일

```text
src/flight_bot/__main__.py          FastAPI / scheduler / runtime lifecycle
src/flight_bot/service.py           slot command / serialized check / alert state machine
src/flight_bot/db.py                SQLite WAL / migrations / slot generation
src/flight_bot/models.py            domain models / observed-vs-verified
src/flight_bot/channels.py          Telegram / Discord / Kakao notification boundary
src/flight_bot/providers.py         legacy unverified Google runtime provider
src/flight_bot/browser_session.py   reusable Playwright session
src/flight_bot/google_ui_contract.py pure Google UI candidate rules
scripts/google_booking_pointer_probe.py Windows acceptance orchestrator
scripts/google_dom_capture.js        early DOM/transient capture
```
