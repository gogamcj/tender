# 단계별 진행 보고

## 1단계 — 골격, DB 모델, 마이그레이션, 계산 엔진, 규칙 레지스트리 (2026-10-27)

### 생성한 파일
- `backend/pyproject.toml`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`
- `backend/alembic/versions/0001_initial_schema.py` — 24개 테이블 초기 스키마
- `backend/app/core/config.py` — 환경변수 설정(`BID_` 접두사)
- `backend/app/db/base.py` — 공통 기반, `ExactDecimal`(금액·비율 고정소수점), JSON/JSONB 겸용 타입
- `backend/app/db/enums.py` — 데이터 상태 8종, 개찰 상태, 조회 실패 사유, 예정가격 성격 등
- `backend/app/db/models/{accounts,rules,notices,analysis,jobs}.py`
- `backend/app/db/session.py`
- `backend/app/engines/calc/{money,formulas,errors}.py` — 계산 엔진
- `backend/app/engines/rules/{schema,registry}.py` — 규칙 정의·선택·평가
- `backend/app/services/rules.py`, `backend/app/api/{calc,rules}.py`, `backend/app/main.py`
- `backend/tests/...` — 단위 테스트(계산·규칙), 통합 테스트(스키마·API)
- `.env.example`, `docker-compose.yml`(PostgreSQL), `README.md`, `docs/design.md`, `docs/known-limitations.md`

### 구현한 기능
- 계산 엔진: 사정률, 가정 예정가격, 낙찰하한금액, 투찰률, 후보 투찰금액, 부가세 분리, 금액 경계 검증, 절사·올림·사사오입(처리 단위 지정)
  - float 입력 거부, 비율 단위(% / 소수) 명시 필수, 기준금액 종류(예정가격/기초금액/추정가격) 명시 필수
  - 기준가격이 확정값이 아니면 결과에 "가정 기반 분석" 표시
  - 절사 규칙이 없으면 원 미만 값을 그대로 두고 경고, 부가세 포함 여부 미확인 시 계산 거부
  - 모든 결과에 산식·입력값·경고를 담아 직렬화 → 재계산으로 재현 가능
- 규칙 레지스트리: 유효기간(공고일 기준, 소급 금지), 대분류·발주기관 유형·계약방법·결정방식·금액 구간·지역·업종 조건, "판단 불가" 상태 구분, 다중 일치 시 자동 선택 안 함, 미검증 규칙 결과는 확정 아님(설정으로 차단 가능), 검증됨 상태는 근거 문서 필수
- DB: 공고 유일성 `(출처, 공고번호, 차수)`, 정정 차수별 보존, 원본 레코드 분리 보존, 필드 변경 이력, 결과가 있는 공고 삭제 금지(RESTRICT), 결과 삭제 시 참여업체·예비가격 연쇄 삭제, 상태값 CHECK 제약, 낙찰률 기준 컬럼
- SQLite ↔ PostgreSQL 같은 코드·같은 마이그레이션으로 동작. SQLite 의 NUMERIC 부동소수점 오차를 발견해 스케일 정수 저장으로 해결
- API: `/api/health`, `/api/calc/*` 6종, `/api/rules`(등록·조회·검증상태 변경·선택/평가), OpenAPI 문서 `/docs`

### 실행 방법
README.md "빠른 시작" 참고.

### 실행한 테스트와 결과
- `pytest` (SQLite + PostgreSQL 16): **116 passed**
  - 계산 단위 54개, 규칙 단위 22개, 스키마 통합 24개(12개 × SQLite·PostgreSQL), API 통합 16개(8개 × 2 DB)
- `alembic upgrade head` → `alembic check`(모델과 차이 없음) → `alembic downgrade base` 를 SQLite·PostgreSQL 양쪽에서 성공
- 새 가상환경에서 `pip install -e ".[dev]"` → `alembic upgrade head` → `uvicorn` 기동 → `/api/health`, `/docs`, `/api/calc/lower-limit` 응답 확인

### 확인하지 못한 항목
- 실제 공고문·공식 예시와의 계산 교차 검증(규칙 원문 미확보)
- 실제 낙찰하한율·금액 구간·복수예비가격 규칙 데이터(모두 미등록)
- Docker Compose 로 띄운 PostgreSQL 컨테이너(개발 환경에서는 로컬 PostgreSQL 16 으로 검증)

### 다음 단계
2단계: 엑셀·CSV 업로드(시트·열 분석, 열 매핑, 형식 변환, 누락·중복·오류 검사, 미리보기, 확정 저장, 결과 보고서, 원본 보존, 변경 전후 비교)

## 2단계 — 엑셀·CSV 업로드 (2026-10-27)

### 생성·수정한 파일
- 생성: `backend/app/importers/{reader,parsing,fields,validate}.py`, `backend/app/services/{notices,imports}.py`, `backend/app/api/imports.py`
- 생성: `backend/alembic/versions/0002_import_job_links.py` — 공고·결과·변경이력에 업로드 작업 연결(되돌리기용)
- 생성: `backend/seed/sample_results.csv`, `backend/seed/README.md`, `docs/upload-guide.md`
- 생성: `backend/tests/unit/importers/*`, `backend/tests/integration/test_imports_api.py`
- 수정: `backend/app/db/base.py` — `UTCDateTime` 추가(SQLite 가 시간대를 버려 재업로드 시 모든 행이 '변경'으로 잡히던 문제 해결), `0001` 마이그레이션의 일시 타입을 같은 타입으로 교체
- 수정: `backend/app/db/models/notices.py`, `backend/app/core/config.py`(`BID_STORAGE_DIR`), `backend/app/main.py`, `backend/pyproject.toml`(python-multipart, xlrd, xlwt)

### 구현한 기능
요구사항 6장의 10단계 절차를 API 로 구현했습니다(화면은 7단계).
1. 파일 선택·검사(형식, 크기, 매크로, 압축 해제 크기, 이진 CSV) 2. 시트·열 분석 3. 열 매핑(자동 추천 + 수동) 4. 금액·비율·날짜 변환
5. 필수 항목 확인 6. 파일 내·기존 데이터 중복 검사 7. 오류·경고 표시 8. 미리보기 9. 확정 저장(변경은 행별 승인) 10. 결과 보고서 CSV
- 원본 파일 보관 + 행별 원본 셀 보존, 정규화 데이터 분리
- 기존 데이터 무조건 덮어쓰기 금지: 변경 전후를 보여 주고 승인한 행만 반영, 필드별 변경 이력 기록
- 정정 차수 저장 시 최신 차수 표시 갱신, 업로드 작업 단위 되돌리기
- 보고서 CSV 의 수식 주입 방지

### 실행 방법
`docs/upload-guide.md` 참고. 서버 실행 후 `/docs` 에서 업로드 API 를 직접 시험할 수 있습니다.

### 실행한 테스트와 결과
- `pytest` 전체(SQLite + PostgreSQL 16): **188 passed**
  - 이번 단계 추가: 업로드 단위 54개(인코딩 4종, 탭 구분, XLSX·XLS 읽기, 매크로 거부, 크기 제한, 날짜·금액·비율 변환, 매핑 추천, 검증 규칙), 업로드 API 통합 16개(8개 × 2 DB: 전체 흐름, 같은 파일 재업로드, 변경 승인·미승인, 되돌리기, 새 차수, CP949, 보고서, 상태 오류), 일시 저장 테스트 2개
- `alembic upgrade head` → `alembic check` → `alembic downgrade base` SQLite·PostgreSQL 양쪽 성공

### 확인하지 못한 항목
- 실제 나라장터에서 내려받은 엑셀 파일 형식(병합 셀, 다중 헤더 등)으로는 시험하지 못했습니다. 실제 파일을 주시면 매핑 추천 사전을 보강하겠습니다.
- 대용량(수만 행) 파일의 처리 시간

### 다음 단계
3단계: 나라장터 API 커넥터(입찰공고·낙찰정보·개방표준), 수집 작업, 호출 한도·재시도·페이지네이션, 원본 보존, 정정 이력, API 응답 구조 점검 스크립트

## 3단계 — 공식 API 커넥터와 자동 수집 (2026-10-27)

### 생성·수정한 파일
- 생성: `backend/app/connectors/{client,specs,mappers}.py` — 공통 HTTP 클라이언트, 오퍼레이션 명세(근거 수준 표시), 응답 → 정규화 변환
- 생성: `backend/app/services/{collection,quota}.py`, `backend/app/api/collections.py`, `backend/app/cli.py`(collect·probe·ops)
- 생성: `backend/alembic/versions/0003_collection_fields.py` — 예비가격 범위, 낙찰업체 식별자, 조회 상태 `not_returned`(응답 없음)
- 생성: `backend/tests/fakes.py`, `backend/tests/unit/connectors/test_client.py`, `backend/tests/integration/{test_collection,test_migrations}.py`, `docs/api-auth-guide.md`
- 수정: `app/db/{enums,session}.py`, `app/db/models/notices.py`, `app/services/notices.py`, `app/core/config.py`(`BID_API_DAILY_LIMITS`), `app/main.py`

### 구현한 기능
- 커넥터: 입찰공고(목록·검색·기초금액), 낙찰정보(최종낙찰자·개찰결과·복수예비가격 상세·개찰완료 투찰업체), 개방표준 입찰공고 — 공사·용역·물품·외자 업무별 오퍼레이션 30개 등록
- 인증키 환경변수 관리와 로그 마스킹, 요청 간격 제한, 타임아웃 30초, 지수 백오프 재시도(일시 장애·초당 한도만), 오류 코드 분류, XML 오류 응답 해석
- 페이지네이션(totalCount 기준), 같은 페이지 반복 감지, 최대 페이지 수 제한, 조회 기간을 오퍼레이션별 최대 구간으로 자동 분할
- 일일 호출 한도 보호(DB 카운터, 한도의 90% 에서 중단)
- 원본 응답 항목 보존, 같은 원본 재수집 시 건너뜀, 공식 값 변경 시 필드별 이력, 사용자 자료와 충돌 시 덮어쓰지 않고 '원본과 불일치' 표시
- 정정 차수 별도 저장 + '수정 공고 확인 필요' 표시, 개찰 전·후 구분, 결과 조회 시 응답이 비면 '응답 없음'(유찰로 보지 않음)
- 복수예비가격 상세 → 예비가격 15개·추첨 여부 저장, 확정 예정가격·사정률 계산, 확정 예정가격 대비 낙찰률 계산(기준 기록)
- 항목 하나의 오류가 수집 전체를 멈추지 않음, 페이지 단위 커밋으로 장애 시 받은 데이터 보존
- 수집 이력 API(백그라운드 실행), 명령줄 수집(정기 실행용), 실제 응답 구조 점검 도구

### 실행 방법
`docs/api-auth-guide.md` 참고.

### 실행한 테스트와 결과
- `pytest` 전체(SQLite + PostgreSQL 16): **235 passed**
  - 이번 단계 추가: 클라이언트 단위 21개(응답 형식, 오류 분류, 재시도·백오프, 키 마스킹, 페이지네이션), 수집 통합 24개(DB 무관 2개 + 11개 × 2 DB: 삽입·재수집·변경 이력, 사용자 자료 보호, 정정 차수, 낙찰·예비가격·투찰업체, 유찰 판정, 응답 없음, 한도 보호, 장애 시 데이터 보존, 부분 실패, 잘못된 항목, 백그라운드 API), 마이그레이션 왕복 2개
- `alembic` 0001→0003 업그레이드, 0002 로 다운그레이드 후 재업그레이드(데이터 유지), 모델-스키마 차이 없음: SQLite·PostgreSQL

### 확인하지 못한 항목
- **실제 API 호출 전부**: 개발 환경에서 data.go.kr 접속이 막혀 있습니다. 인증키로 `python -m app.cli probe` 실행 결과가 필요합니다.
- 계약과정통합공개서비스, 지자체 전용 API
- 실제 응답 속도에 맞춘 페이지 크기·간격 조정

### 다음 단계
4단계: 과거 낙찰 데이터 분석(기간·기관·공종·지역·금액구간·결정방식·참가업체수별 통계, 사정률 분포, 이상치, 혼합 금지), 유사 입찰 검색과 선정 근거
