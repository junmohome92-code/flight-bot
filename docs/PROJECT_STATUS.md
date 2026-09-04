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

결론: 현재 프로젝트 Primary Provider로 복귀시키지 않습니다.

### 4.2 Playwright + fast-flights 생성 tfs 직링크 — 거부

GitHub hosted Azure runner와 사용자 Windows 일반 인터넷 모두 route/date는 로드했지만 `Price unavailable`을 반환했습니다.

결론: `tfs` 직링크 + 자동화 세션 경로는 사용하지 않습니다.

### 4.3 fast-flights 3.1.0 parser — 거부

`get_flights()`는 현재 Google payload에서 `IndexError`가 발생했고, raw payload의 RF511/ZE781 등 일부 후보는 실제 숫자 대신 `[[], token]` 형태였습니다.

독립 편도 최저가 합은 724,650 KRW로 사용자 일반 브라우저의 저렴한 왕복 조합과 달랐습니다.

결론: 가격 Provider로 사용하지 않습니다.

### 4.4 punitarani/fli direct Google service API — 거부

검증 commit:

```text
121d34fea056dc513258958c4262cb5a4cc033c1
```

`get_booking_options()` 존재는 확인했으나 CJJ↔TPE 기준 검색은 `Fli returned no round-trip results`였습니다. upstream issue #223에도 일반 노선 no-results 문제가 있으며, issue #168에는 브라우저 BotGuard 신호 없이 OTA/리셀러 Booking 결과가 축소된다는 보고가 있습니다.

결론: HTTP-only Fli direct service를 Primary Provider로 채택하지 않습니다.

## 5. 실제 Google Flights UI 실험 결과

### 5.1 Playwright가 Edge를 직접 실행한 persistent profile — 실패

Google Flights 첫 화면부터 CJJ/TPE/날짜를 직접 입력했습니다. 즉 tfs 직링크는 사용하지 않았습니다.

실제 결과 URL:

```text
.../travel/flights/search?...&hl=en&gl=kr&curr=KRW
```

따라서 다음은 이미 확인됐습니다.

```text
Country hint: KR
Currency: KRW
Route/date: correct
Browser: Microsoft Edge
Dedicated persistent profile: yes
```

그럼에도:

```text
price_candidates=0
Google UI search completed but this browser session still shows Price unavailable
```

즉 국가/통화 파라미터 누락이 직접 원인은 아닙니다.

### 5.2 현재 다음 acceptance — native Edge + CDP attach

`scripts/google_ui_probe.py`를 변경했습니다.

새 방식:

```text
Windows msedge.exe를 일반 프로세스로 직접 실행
→ dedicated user-data-dir 사용
→ remote debugging port 오픈
→ Playwright는 Edge를 launch하지 않고 CDP attach만 수행
→ Google Flights UI에서 CJJ/TPE/날짜 직접 입력
```

환경 힌트:

```text
--lang=ko-KR
Accept-Language: ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7
Asia/Seoul
gl=kr
curr=KRW
```

목표는 일반 Edge와 Playwright-launched Edge의 차이를 줄이는 것입니다.

## 6. 현재 중요한 경계

`src/flight_bot/providers.py`의 runtime Provider는 아직 기존 v0.2 `tfs URL + Playwright` 구현입니다.

**native Edge CDP real-UI acceptance가 가격을 실제로 반환하기 전에는 runtime Provider를 완전히 교체하지 않습니다.**

현재 상태:

```text
Bot Core: usable
DB/latch: usable
Windows/Linux unit CI: usable
Runtime Google price Provider: migration pending
Native Edge CDP probe: current acceptance candidate
```

## 7. 다음 acceptance

Windows 최신 소스에서:

```text
flight-bot - test win
└─ 02-live-cjj-tpe-visible.cmd
```

성공 기준:

```text
=== LOCALE DIAGNOSTICS ===
url_gl_kr=True
url_curr_krw=True
...
=== SUMMARY ===
ui_lowest=... KRW
acceptance=PRICE_VISIBLE
```

실패 시:

```text
artifacts/google-ui-win/cjj-tpe-error.png
artifacts/google-ui-win/cjj-tpe-error.txt
artifacts/google-ui-win/cjj-tpe-error.html
```

## 8. acceptance 성공 후

1. runtime Provider를 real-UI 방식으로 교체
2. 가격은 페이지 전체 min이 아니라 실제 flight row 가격만 비교
3. 최저 출국 후보 선택 → 귀국 후보 → Booking 최종가격 검증
4. `REQUIRE_VERIFIED_ALERTS=true` 유지
5. fast-flights dependency 제거
6. Docker/Ubuntu profile volume 구성
7. Windows/Linux tests + live acceptance 재검증

## 9. 이후 구조 개선

- 약 10분 local cache
- 동일 검색 single-flight coalescing
- watch slot과 notification subscription 분리
- provider attempt / cache hit / error logging
- browser process/context 재사용 검토
- Provider error taxonomy 확대

## 10. 절대 되돌리지 말 것

- SerpApi를 근거 없이 Primary로 복원하지 말 것
- `fast-flights.get_flights()`를 가격 source로 복원하지 말 것
- Fli direct API를 CJJ↔TPE 실가격 source로 다시 채택하지 말 것
- Google 가격이 없을 때 다른 숫자를 추정/합성하지 말 것
- 수하물 미확인을 `없음`으로 바꾸지 말 것
