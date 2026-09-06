# Flight Bot — provider selection POC

현재 단계는 **항공권 가격 소스 선정**입니다.

후보는 두 개입니다.

- Naver Flights
- Skyscanner

아직 어느 쪽도 운영 Provider로 확정하지 않습니다. 먼저 Windows에서 실제 검색결과 화면을 열고, **직항 왕복 가격을 행 단위로 안정적으로 읽을 수 있는지** 비교합니다.

## 고정 테스트 조건

```text
출발: CJJ (청주)
도착: TPE (타이베이 타오위안)
출국: 2026-09-18
귀국: 2026-09-20
성인 1명
일반석
직항만
```

두 POC 모두 검색결과까지만 봅니다.

```text
검색결과 화면 열기
→ 직항 결과 탐색
→ 화면에 표시된 왕복 가격 수집
→ 가장 낮은 가격 + 후보 최대 4개 출력
→ 결과 URL/스크린샷/텍스트 저장
→ 종료
```

예약/결제 단계로 이동하지 않습니다.

## Windows — 그냥 BAT 더블클릭

Naver Flights:

```text
flight-bot - test win\02-NAVER-flight-test.bat
```

Skyscanner:

```text
flight-bot - test win\03-SKYSCANNER-flight-test.bat
```

최초 실행이라 `.venv-provider-poc`이 없으면 각 BAT가 **POC 전용 환경을 자동 생성**합니다. 기존 운영용 `.venv-win`과 섞지 않습니다. `01`을 먼저 실행할 필요는 없습니다.

수동 준비가 필요할 때만:

```text
flight-bot - test win\01-setup-and-unit-test.cmd
```

두 테스트 모두 **설치된 Microsoft Edge를 화면에 보이게 실행**하며 서로 독립적인 Python probe를 사용합니다.

## PASS 기준

```text
POC_STATUS=PASS
direct_candidate_count=1 이상
lowest_visible_direct_price=...
booking_navigation_performed=False
```

실패하면 콘솔 전체를 복사해 주시면 됩니다.

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

## 다음 단계

두 POC 결과를 비교한 뒤 한 소스를 Primary로 선정합니다.

선정 후에만:

```text
운영 Provider 통합
→ Telegram 슬롯 등록 UX 개선
→ 목표가 푸시알림 E2E
→ 10슬롯 / 최대 2개 동시검색 검증
→ Ubuntu Docker 배포
```

으로 넘어갑니다.
