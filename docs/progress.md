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
  - 계산 단위 테스트 52개, 규칙 단위 테스트 22개, 스키마 통합 테스트 12개×2 DB, API 통합 테스트 8개×2 DB(일부 파라미터화 포함)
- `alembic upgrade head` → `alembic check`(모델과 차이 없음) → `alembic downgrade base` 를 SQLite·PostgreSQL 양쪽에서 성공
- 새 가상환경에서 `pip install -e ".[dev]"` → `alembic upgrade head` → `uvicorn` 기동 → `/api/health`, `/docs`, `/api/calc/lower-limit` 응답 확인

### 확인하지 못한 항목
- 실제 공고문·공식 예시와의 계산 교차 검증(규칙 원문 미확보)
- 실제 낙찰하한율·금액 구간·복수예비가격 규칙 데이터(모두 미등록)
- Docker Compose 로 띄운 PostgreSQL 컨테이너(개발 환경에서는 로컬 PostgreSQL 16 으로 검증)

### 다음 단계
2단계: 엑셀·CSV 업로드(시트·열 분석, 열 매핑, 형식 변환, 누락·중복·오류 검사, 미리보기, 확정 저장, 결과 보고서, 원본 보존, 변경 전후 비교)
