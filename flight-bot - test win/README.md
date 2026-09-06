# Windows provider POC

이 폴더는 항공권 소스를 고르기 위한 **독립 실검색 테스트** 전용입니다.

테스트 대상:

```text
1. Naver Flights
2. Skyscanner
```

둘은 서로 다른 Python probe를 사용합니다. 한쪽이 깨져도 다른 쪽 테스트에는 영향을 주지 않습니다.

## 1. 최초 준비

```text
01-setup-and-unit-test.cmd
```

하는 일:

```text
Python 3.12 확인
→ .venv-win 생성
→ 프로젝트 dependency 설치
→ Microsoft Edge 설치 여부 확인
→ pytest 실행
```

## 2. Naver Flights

더블클릭:

```text
02-NAVER-flight-test.bat
```

고정 검색:

```text
CJJ → TPE → CJJ
2026-09-18 ~ 2026-09-20
성인 1명 / 일반석 / 직항만
```

동작:

```text
Microsoft Edge visible 실행
→ Naver Flights 직항 검색 URL 진입
→ 직항 결과 행 + 가격 탐색
→ 최저가와 후보 최대 4개 출력
→ 결과 자료 저장
→ 종료
```

예약/결제 결과를 클릭하지 않습니다.

결과 자료:

```text
artifacts\naver-flight-poc\page.png
artifacts\naver-flight-poc\page.txt
artifacts\naver-flight-poc\result.json
```

## 3. Skyscanner

더블클릭:

```text
03-SKYSCANNER-flight-test.bat
```

검색 조건은 Naver 테스트와 동일합니다.

동작:

```text
Microsoft Edge visible 실행
→ Skyscanner 직항 검색 URL 진입
→ 직항 결과 행 + 가격 탐색
→ 최저가와 후보 최대 4개 출력
→ 결과 자료 저장
→ 종료
```

예약/결제 결과를 클릭하지 않습니다.

결과 자료:

```text
artifacts\skyscanner-flight-poc\page.png
artifacts\skyscanner-flight-poc\page.txt
artifacts\skyscanner-flight-poc\result.json
```

## 성공 판정

콘솔 마지막에 아래가 나와야 합니다.

```text
POC_STATUS=PASS
```

그리고 최소한:

```text
direct_candidate_count=1 이상
lowest_visible_direct_price=...
booking_navigation_performed=False
```

가 있어야 합니다.

## 실패하면

`POC_STATUS=FAIL`이 뜨면 콘솔 전체를 복사해 주시면 됩니다.

추가로 각 `artifacts` 폴더의 `result.json`이 있으면 DOM/가격 추출 실패인지, 사이트 차단인지 구분하기 쉽습니다.

## 파일 구성

```text
01-setup-and-unit-test.cmd
setup-and-unit-test.ps1
02-NAVER-flight-test.bat
03-SKYSCANNER-flight-test.bat
```

실제 probe:

```text
scripts\naver_flight_probe.py
scripts\skyscanner_flight_probe.py
```
