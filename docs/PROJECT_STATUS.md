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

## 4. Provider 조사 결과

### 4.1 SerpApi — Primary에서 제거

기존 SerpApi deep/hidden 결과와 사용자 일반 Google Flights 화면 사이에 큰 가격 차이가 확인되었습니다.

CJJ↔TPE 사례에서 SerpApi 경로가 브라우저의 더 저렴한 혼합/별도티켓 스타일 결과를 놓쳤습니다.

결론: 현재 프로젝트 Primary Provider로 복귀시키지 않습니다.

### 4.2 Playwright + fast-flights 생성 tfs 직링크 — 거부

Google Flights route/date 자체는 정확히 로드됐습니다.

GitHub hosted Azure runner:

```text
CJJ -> TPE
2026-09-18 -> 2026-09-20
항공편 목록 로드 성공
가격: Price unavailable
```

사용자 Windows 일반 인터넷에서도 동일하게:

```text
PriceUnavailableError:
Google Flights loaded the route but returned Price unavailable for this IP/session
```

따라서 단순히 데이터센터 IP 문제만은 아니며 `tfs` 직링크 + 자동화 세션 경로 자체를 신뢰하지 않습니다.

### 4.3 fast-flights 3.1.0 parser — 거부

직접 `get_flights()` 호출 시:

```text
IndexError: list index out of range
parser.py -> price = k[1][0][1]
```

Google HTML raw payload를 공식 parser 없이 직접 분석했습니다.

왕복:

```text
rows=1
priced_rows=0
RF511 계열 후보 price block = [[], '<token>']
```

CJJ → TPE 편도:

```text
lowest priced row = 309,900 KRW
대한항공 다중 경유
RF511 / ZE781 등 일부 후보 = price 없음 + token만 존재
```

TPE → CJJ 편도:

```text
lowest priced row = 414,750 KRW
대한항공 다중 경유
```

단순 편도 최저가 합:

```text
724,650 KRW
```

이는 사용자 브라우저에서 관찰한 저렴한 왕복 조합과 다른 결과입니다.

결론: `fast-flights` parser를 가격 Provider로 사용하지 않습니다. 현재 runtime에는 tfs URL 생성용 의존성만 아직 남아 있으며 real-UI Provider가 채택되면 제거할 예정입니다.

### 4.4 punitarani/fli direct Google service API — 거부

PyPI에는 당시 `flights` 0.9.0까지만 있었으므로 다음 upstream source commit을 정확히 pin해서 검증했습니다.

```text
punitarani/fli
commit: 121d34fea056dc513258958c4262cb5a4cc033c1
```

해당 소스에 다음 API가 실제 존재함을 확인했습니다.

- GetShoppingResults
- round-trip selected_flight expansion
- GetBookingResults
- get_booking_options()

Windows 설치/API 확인은 성공했습니다.

```text
Fli booking API: OK
```

그러나 기준 시나리오 실행 결과:

```text
Fli returned no round-trip results
```

upstream에도 2026-08 기준 일반 노선 BLR→DEL이 `No flights found`로 반환되는 issue #223이 존재합니다.

또 upstream issue #168에는 브라우저 BotGuard 신호가 없으면 GetBookingResults가 OTA/리셀러 목록을 축소해서 반환한다는 실험 결과가 기록돼 있습니다.

결론: HTTP-only Fli direct service를 Primary Provider로 채택하지 않습니다.

## 5. 현재 채택 후보 — 실제 Google Flights UI + persistent browser

새 probe:

```text
scripts/google_ui_probe.py
```

Windows 실행 래퍼:

```text
flight-bot - test win/02-live-cjj-tpe-visible.cmd
```

동작:

```text
Google Flights 첫 화면 직접 열기
→ Where from? 에 CJJ 입력
→ Where to? 에 TPE 입력
→ Departure 09/18/2026
→ Return 09/20/2026
→ Search
→ Cheapest
→ 실제 렌더링된 KRW 가격 후보 수집
```

이 probe는 다음을 사용하지 않습니다.

```text
SerpApi             NO
Fli direct API       NO
fast-flights parser  NO
tfs 직링크           NO
```

Windows visible 모드 브라우저 우선순위:

```text
Microsoft Edge
→ Google Chrome
→ Playwright Chromium
```

개인 브라우저 profile은 사용하지 않습니다.

전용 persistent profile:

```text
artifacts/google-profile-win/
```

디버그:

```text
artifacts/google-ui-win/cjj-tpe-results.{png,txt,html}
artifacts/google-ui-win/cjj-tpe-error.{png,txt,html}
```

## 6. 현재 중요한 경계

`src/flight_bot/providers.py`의 runtime Provider는 아직 기존 v0.2 `tfs URL + Playwright` 구현입니다.

**새 real-UI probe가 Windows 일반 회선에서 가격 표시 acceptance를 통과하기 전에는 runtime Provider를 완전히 교체하지 않습니다.**

즉 현재 저장소 상태는:

```text
Bot Core: usable
DB/latch: usable
Windows/Linux unit tests: usable
Runtime Google price Provider: migration pending
Real-UI probe: next acceptance candidate
```

## 7. 다음 acceptance

Windows 최신 소스에서:

```text
flight-bot - test win
└─ 02-live-cjj-tpe-visible.cmd
```

성공 기준:

```text
=== SUMMARY ===
ui_lowest=... KRW
acceptance=PRICE_VISIBLE
```

실패하면 다음 세 파일 중 생성된 것을 확인합니다.

```text
artifacts/google-ui-win/cjj-tpe-error.png
artifacts/google-ui-win/cjj-tpe-error.txt
artifacts/google-ui-win/cjj-tpe-error.html
```

### 결과별 다음 조치

1. 화면에도 실제 가격이 보이고 `ui_lowest`도 정상
   - real-UI 방식 채택
   - runtime Provider 교체
   - row-scoped price extraction 강화
   - 출국/귀국/Booking verification 구현
   - fast-flights 제거

2. 화면에는 가격이 보이는데 probe가 가격을 못 읽음
   - Google UI selector/parser 문제
   - error HTML/text 기반으로 가격 row selector 수정

3. Edge persistent UI 화면 자체가 `Price unavailable`
   - 두 번째 실행에서도 같은지 확인하여 persistent session 효과 확인
   - browser/session 제약 재평가
   - stealth/CAPTCHA 우회 코드는 기본 전략으로 넣지 않음

## 8. 이후 남은 구조 개선

실가격 Provider acceptance 이후 처리할 항목:

- 약 10분 local cache
- 동일 검색 single-flight coalescing
- watch slot과 notification subscription 분리
- provider attempt / cache hit / error 분류 logging
- row-scoped price extraction
- browser process/context 재사용 검토
- 명확한 Provider error classes 확대

이 항목들은 Provider acceptance보다 뒤입니다.

## 9. CI

일반 push/PR:

```text
Linux Python 3.12
- install
- compileall src scripts tests
- pytest

Windows Python 3.12
- install
- compileall src scripts tests
- pytest
- Playwright Chromium install + launch
```

Google Flights 실검색은 hosted IP 특성 때문에 수동 `workflow_dispatch` diagnostic으로만 실행합니다.

## 10. 절대 되돌리지 말 것

- SerpApi를 근거 없이 Primary로 복원하지 말 것
- `fast-flights.get_flights()`를 검증 없이 가격 source로 복원하지 말 것
- Fli direct API를 CJJ↔TPE 실가격 source로 다시 채택하지 말 것
- Google 가격이 없을 때 다른 숫자를 추정/합성하지 말 것
- 수하물 미확인을 `없음`으로 바꾸지 말 것
