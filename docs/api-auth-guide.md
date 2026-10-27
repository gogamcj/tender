# 공공데이터포털 API 인증 설정 안내

## 1. 활용 신청
공공데이터포털(data.go.kr)에 로그인한 뒤 아래 서비스를 각각 **활용신청**합니다. 개발계정은 자동 승인됩니다.

| 서비스 | 포털 데이터 번호 | 개발계정 일일 트래픽(포털 기재) |
|---|---|---|
| 조달청_나라장터 입찰공고정보서비스 | 15129394 | 1,000회 |
| 조달청_나라장터 낙찰정보서비스 | 15129397 | 1,000회 |
| 조달청_나라장터 공공데이터개방표준서비스 | 15058815 | 10,000회 |

운영계정(트래픽 증가)은 포털에서 활용사례를 등록하고 신청합니다. 늘어난 한도는 아래 환경변수로 알려 주세요.

## 2. 인증키 설정
마이페이지 → 개발계정 → 일반 인증키 중 **Decoding 키**를 복사해 `.env`에 넣습니다.
Encoding 키를 넣으면 이중 인코딩되어 `30`(미등록 키) 오류가 날 수 있습니다.

```
BID_DATA_GO_KR_SERVICE_KEY=복사한_Decoding_키
# 운영계정 등으로 한도가 늘었을 때(선택)
BID_API_DAILY_LIMITS={"g2b_bid_notice": 10000, "g2b_scsbid": 10000}
```

- 인증키는 서버 환경변수에서만 읽으며, 화면·로그·오류 메시지에는 `***`로 가려집니다. 소스코드나 git 에 넣지 마세요.
- 프로그램은 API 별로 오늘(한국 날짜) 호출 수를 DB 에 기록하고, 한도의 **90%**에 이르면 수집을 멈춥니다.

## 3. 응답 구조 점검(처음 한 번)
이 프로그램의 필드 대응표는 포털 상세 페이지와 공개 오픈소스 클라이언트를 근거로 만들었고, 실제 응답으로는 아직 확인하지 못했습니다.
인증키를 넣은 뒤 아래 명령으로 실제 응답과 기대 필드를 비교해 주세요(오퍼레이션당 1회 호출).

```bash
cd backend
python -m app.cli probe --out ./probe_samples                 # 최근 며칠치 공고·결과 목록
python -m app.cli probe --notice R25BK00000000 --out ./probe_samples  # 특정 공고번호로 기초금액·예비가격·투찰업체 확인
```

결과의 `expected_missing`(기대했는데 응답에 없는 필드)과 `unmapped_fields`(응답에는 있으나 쓰지 않는 필드)를 확인합니다.
`probe_samples/*.json`을 공유해 주시면 대응표를 실응답에 맞게 고칩니다(인증키는 파일에 포함되지 않습니다).

## 4. 수집 실행
- 화면(7단계) 또는 API: `POST /api/collections` `{"operation_key": "notice_list_construction", "date_from": "2024-06-01", "date_to": "2024-06-30"}`
- 명령줄: `python -m app.cli collect --op notice_list_construction --from 2024-06-01 --to 2024-06-30`
- 공고번호 단건: `python -m app.cli collect --op prepar_construction --notice R24BK00000001`
- 오퍼레이션 목록과 근거 수준: `python -m app.cli ops` 또는 `GET /api/collections/sources`

정기 수집은 운영체제 스케줄러에 등록합니다(예: 매일 06:00 전날 공고 수집).

```
0 6 * * * cd /path/to/backend && ../.venv/bin/python -m app.cli collect --op notice_list_construction --from $(date -d yesterday +\%F) --to $(date -d yesterday +\%F)
```

## 5. 오류 코드
| 코드 | 의미 | 프로그램 동작 |
|---|---|---|
| 20, 30, 31 | 권한 없음, 미등록 키, 기한 만료 | 즉시 중단(재시도 안 함) |
| 22 | 일일 한도 초과 | 중단(작업 상태 `quota_stopped`) |
| 23 | 초당 한도 초과 | 지수 백오프 후 재시도 |
| 07 | 입력 범위 초과 등 요청 오류 | 중단, 조회 기간을 줄여 다시 시도 |
| 03 | 데이터 없음 | 빈 결과로 처리 |
| 시간 초과·네트워크·HTTP 5xx | 일시 장애 | 최대 3회 재시도 |

API 장애가 나도 이미 저장된 데이터, 업로드, 계산·분석 기능은 그대로 동작합니다. 수집은 페이지 단위로 저장되어 중간에 실패해도 받은 데이터는 남습니다.
