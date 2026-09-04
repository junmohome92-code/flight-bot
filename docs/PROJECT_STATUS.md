# Flight Bot — PROJECT STATUS

최종 정리일: 2026-09-04

## 1. 현재 단계

**Provider Migration Gate — ACTIVE**

봇 Core/DB/목표가 latch/채널 구조는 유지합니다. 현재 막힌 부분은 Google Flights의 실제 브라우저 최저가를 신뢰성 있게 얻는 Provider입니다.

운영 Ubuntu 서버로 최종 배포하기 전에 CJJ↔TPE acceptance test를 통과해야 합니다.

## 2. 유지되는 Core

- Python 3.12+
- FastAPI
- APScheduler
- SQLite WAL
- Telegram / Discord
- Kakao reactive skill
- 슬롯 정확히 3개: 1/2/3
- pause는 슬롯 점유
- delete 후 번호 재사용
- target_price 필수
- alert latch: ARMED → 목표가 하향 돌파 시 1회 → ALERTED → 목표가 위로 복귀 시 re-arm
- `REQUIRE_VERIFIED_ALERTS=true` 기본
- Provider와 notifier 분리
- 검색은 슬롯별 순차 실행
- 가격/수하물 정보 미확인 시 추정값 생성 금지

## 3. 기준 acceptance 시나리오

```text
Origin: CJJ
Destination: TPE
Departure: 2026-09-18
Return: 2026-09-20
Adult: 1
Cabin: Economy
Currency: KRW
Stops: unrestricted
Mixed airlines: allowed
Separate/self-transfer style results: allowed
```

사용자 일반 브라우저에서 같은 조건으로 약 33만 원대 왕복 결과가 관찰된 적이 있습니다. 가격은 실시간 값이므로 정확한 숫자를 acceptance 조건으로 고정하지 않습니다.

## 4. 이미 거부한 Provider 경로

### SerpApi

브라우저 직접 Google Flights보다 비싸고, 저렴한 혼합/별도티켓 스타일 결과가 누락된 사례가 있었습니다. Primary로 복귀시키지 않습니다.

### tfs 직링크 + Playwright

GitHub hosted runner와 사용자 Windows 일반 회선 모두 route/date는 로드했지만 `Price unavailable`이 발생했습니다. 이 경로는 사용하지 않습니다.

### fast-flights 3.1.0 parser

`get_flights()`에서 현재 Google payload와 맞지 않아 `IndexError`가 발생했고, raw payload의 RF511/ZE781 등 일부 후보는 실제 숫자 대신 `[[], token]` 형태였습니다. 독립 편도 최저가 합은 724,650 KRW로 사용자 일반 브라우저의 저렴한 왕복 조합과 달랐습니다. 가격 Provider로 사용하지 않습니다.

### punitarani/fli direct Google service API

검증 commit:

```text
121d34fea056dc513258958c4262cb5a4cc033c1
```

`get_booking_options()` 존재는 확인했으나 CJJ↔TPE 기준 검색은 `Fli returned no round-trip results`였습니다. upstream issue #223에도 일반 노선 no-results 문제가 있고, issue #168에는 브라우저 BotGuard 신호 없이 OTA/리셀러 Booking 결과가 축소된다는 보고가 있습니다. Primary로 채택하지 않습니다.

## 5. 실제 Google Flights UI 실험 결과

### 5.1 Playwright-launched Edge persistent profile — 실패

Google Flights 첫 화면부터 CJJ/TPE/날짜를 직접 입력했으며 tfs 직링크는 사용하지 않았습니다.

실제 결과 URL:

```text
.../travel/flights/search?...&hl=en&gl=kr&curr=KRW
```

확인 결과:

```text
Route/date: correct
Country hint: gl=kr
Currency: curr=KRW
Browser: Microsoft Edge
Dedicated persistent profile: yes
price_candidates=0
Price unavailable
```

### 5.2 Native Edge + CDP attach — 1회 실행도 실패

Windows의 실제 `msedge.exe`를 직접 실행하고 Playwright는 CDP attach만 수행했습니다.

```text
Edge launch: native msedge.exe
Playwright role: CDP attach only
Accept-Language: ko-KR...
gl=kr
curr=KRW
```

사용자 실행 결과:

```text
url_gl_kr=True
url_curr_krw=True
page_mentions_krw=True
page_mentions_korea=True
price_candidates=0
Native Edge UI still shows Price unavailable despite KR/KRW settings
```

따라서 단순 `gl`/`curr` 누락이 직접 원인은 아닙니다.

주의: 기존 `page_mentions_korea=True`는 route 자체의 South Korea 텍스트와 구분하지 못하므로 실제 Footer Location 검증으로 교체했습니다.

### 5.3 현재 acceptance — native Edge + actual footer locale + 최대 5회 fresh UI retry

SerpApi도 2026-03 Google Flights에서 정상 검색이 간헐적으로 `Price unavailable`을 반환하는 문제를 공개적으로 기록했고, 당시 약 5번 중 1번 누락되어 반복 검색으로 우회한 뒤 자동 retry를 추가했습니다.

현재 `scripts/google_ui_probe.py`는 다음을 수행합니다.

```text
native msedge.exe
→ dedicated persistent profile
→ Playwright CDP attach only
→ Google Flights 첫 UI에서 검색
→ 실제 Footer Language / Location / Currency 출력
→ navigator.webdriver / language / timezone 출력
→ Price unavailable이면 fresh UI 검색을 최대 5회 반복
```

UI는 selector 안정성을 위해 English로 유지합니다. 지역과 표시 통화는 독립적으로:

```text
gl=kr
curr=KRW
Accept-Language=ko-KR...
```

로 설정하며 실제 Footer 값으로 확인합니다.

## 6. 현재 중요한 경계

`src/flight_bot/providers.py`의 runtime Provider는 아직 기존 v0.2 `tfs URL + Playwright` 구현입니다.

**5회 retry acceptance가 실제 가격을 반환하기 전에는 runtime Provider를 교체하지 않습니다.**

현재 상태:

```text
Bot Core: usable
DB/latch: usable
Windows/Linux unit CI: usable
Runtime Google price Provider: migration pending
Native Edge retry probe: current acceptance candidate
```

## 7. 다음 acceptance

Windows 최신 소스에서:

```text
flight-bot - test win
└─ 02-live-cjj-tpe-visible.cmd
```

이번에는 최대 5회까지 자동 재검색합니다.

성공 기준:

```text
Price became visible on attempt N/5.
=== SUMMARY ===
ui_lowest=... KRW
acceptance=PRICE_VISIBLE
```

실패 시 중요한 출력:

```text
footer_location=...
footer_currency=...
navigator_webdriver=...
navigator_language=...
timezone=...
attempt 1..5: Price unavailable
```

디버그 파일:

```text
artifacts/google-ui-win/attempt-N-results.{png,txt,html}
artifacts/google-ui-win/cjj-tpe-error.{png,txt,html}
```

## 8. 5회 모두 실패하면 다음 분기

5회 모두 `Price unavailable`이고 Footer가 South Korea/KRW라면 locale 문제보다 **browser session / remote-debugging / automated interaction 차이** 가능성을 우선합니다.

그때는 자동화를 더 우회하려 하지 말고 다음 수동 baseline을 분리해서 비교합니다.

```text
A. 일반 사용자 Edge + 현재 실제 사용자 profile + 수동 검색
B. dedicated google-profile-win + remote debugging 없이 수동 검색
C. dedicated google-profile-win + remote debugging + 수동 검색
```

이 세 조건으로 fresh profile, remote debugging, Playwright interaction 중 어느 조건에서 가격이 사라지는지 분리합니다.

stealth/CAPTCHA/BotGuard 우회 코드는 기본 전략으로 넣지 않습니다.

## 9. acceptance 성공 후

1. runtime Provider를 real-UI 방식으로 교체
2. 가격은 페이지 전체 min이 아니라 실제 flight row 가격만 비교
3. 최저 출국 후보 선택 → 귀국 후보 → Booking 최종가격 검증
4. `REQUIRE_VERIFIED_ALERTS=true` 유지
5. fast-flights dependency 제거
6. Docker/Ubuntu profile volume 구성
7. Windows/Linux tests + live acceptance 재검증

## 10. 이후 구조 개선

- 약 10분 local cache
- 동일 검색 single-flight coalescing
- watch slot과 notification subscription 분리
- provider attempt / cache hit / error logging
- browser process/context 재사용 검토
- Provider error taxonomy 확대

## 11. 절대 되돌리지 말 것

- SerpApi를 근거 없이 Primary로 복원하지 말 것
- `fast-flights.get_flights()`를 가격 source로 복원하지 말 것
- Fli direct API를 CJJ↔TPE 실가격 source로 다시 채택하지 말 것
- Google 가격이 없을 때 다른 숫자를 추정/합성하지 말 것
- 수하물 미확인을 `없음`으로 바꾸지 말 것
