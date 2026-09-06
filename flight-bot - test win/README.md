# Windows provider POC

현재는 항공권 소스 선정 테스트만 합니다.

후보:

```text
1. Naver Flights
2. Skyscanner
```

두 테스트는 완전히 별도입니다. 한쪽이 실패해도 다른 쪽에는 영향이 없습니다.

고정 조건:

```text
CJJ -> TPE -> CJJ
2026-09-18 ~ 2026-09-20
성인 1명 / 일반석 / 직항만
```

예약/결제 페이지로 이동하지 않습니다.

## 가장 쉬운 실행법

ZIP을 새로 받은 뒤 둘 중 원하는 BAT를 그냥 더블클릭하면 됩니다.

Naver:

```text
02-NAVER-flight-test.bat
```

Skyscanner:

```text
03-SKYSCANNER-flight-test.bat
```

`.venv-win`이 없으면 BAT가 최초 준비를 자동 실행합니다.

즉 처음부터 `01`을 따로 실행할 필요는 없습니다.

원할 때만 수동 준비:

```text
01-setup-and-unit-test.cmd
```

## 테스트가 하는 일

각 BAT는 설치된 Microsoft Edge를 화면에 띄워:

```text
검색결과 페이지 진입
-> 직항 결과 탐색
-> 화면에 표시된 가격을 결과 행 단위로 수집
-> 최저가 + 후보 최대 4개 출력
-> 결과 자료 저장
-> 종료
```

까지만 합니다.

항공권 카드나 예약 버튼을 눌러 Booking/결제 단계로 넘어가지 않습니다.

## 성공 판정

콘솔 마지막에:

```text
POC_STATUS=PASS
direct_candidate_count=1 이상
lowest_visible_direct_price=...
booking_navigation_performed=False
```

가 나오면 됩니다.

## 실패 시

콘솔 전체를 그대로 복사해 주세요.

Naver 자료:

```text
artifacts\naver-flight-poc\page.png
artifacts\naver-flight-poc\page.txt
artifacts\naver-flight-poc\result.json
```

Skyscanner 자료:

```text
artifacts\skyscanner-flight-poc\page.png
artifacts\skyscanner-flight-poc\page.txt
artifacts\skyscanner-flight-poc\result.json
```

브라우저가 차단/캡차를 띄우는지, 검색 URL이 실패하는지, 결과 행 추출만 실패하는지 구분할 수 있도록 자료를 남깁니다.

## 현재 Windows 테스트 파일

```text
01-setup-and-unit-test.cmd        선택: 수동 최초 준비
02-NAVER-flight-test.bat          Naver 독립 실검색
03-SKYSCANNER-flight-test.bat     Skyscanner 독립 실검색
setup-and-unit-test.ps1           공통 최초 준비
```

실제 probe:

```text
scripts\naver_flight_probe.py
scripts\skyscanner_flight_probe.py
```
