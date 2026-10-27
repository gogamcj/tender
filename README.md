# 공공입찰 통합 분석 및 투찰금액 추천 시스템

대한민국 공공입찰(나라장터·지방자치단체 등) 데이터를 모아 분석하고, 투찰금액 시나리오와 그 근거를 보여 주는 의사결정 지원 도구입니다.

- 특정 금액의 낙찰을 보장하지 않으며, 검증되지 않은 낙찰 확률을 표시하지 않습니다.
- 실제 입찰서 제출이나 투찰을 자동으로 수행하지 않습니다.
- 낙찰하한율·복수예비가격·적격심사 기준은 코드에 고정하지 않고 규칙 데이터로 관리하며, 원문 규정으로 검증되지 않은 규칙으로는 확정 결과를 만들지 않습니다.

## 현재 상태

개발 단계별 진행 상황과 구현·미구현 범위는 [docs/progress.md](docs/progress.md), 알려진 제한사항은 [docs/known-limitations.md](docs/known-limitations.md) 에 있습니다.

## 설치 (Docker Compose)

```bash
cp .env.example .env                 # POSTGRES_PASSWORD 등 수정
docker compose up -d --build
docker compose exec backend python -m app.cli create-user admin --role admin
# http://localhost:8080
```

자세한 내용: [설치 매뉴얼](docs/install.md), [API 인증 안내](docs/api-auth-guide.md), [엑셀 업로드 안내](docs/upload-guide.md), [백업·복원](docs/backup-restore.md), [카페24 등 리눅스 서버 배포](docs/deploy-cafe24.md), [알려진 제한사항](docs/known-limitations.md)

## 빠른 시작 (개발, 백엔드 SQLite)

```bash
cd backend
python3 -m venv ../.venv && . ../.venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example .env          # 필요 시 값 수정
alembic upgrade head             # DB 스키마 생성
python -m app.cli create-user admin --role admin   # 첫 관리자(비밀번호는 입력 프롬프트로)
uvicorn app.main:app --reload    # http://127.0.0.1:8000/docs 에서 API 문서 확인
pytest                           # 테스트
```

PostgreSQL 사용:

```bash
cp .env.example .env   # POSTGRES_PASSWORD 지정
docker compose up -d db
export BID_DATABASE_URL=postgresql+psycopg://bid:<비밀번호>@localhost:5432/bid_analyzer
cd backend && alembic upgrade head
# PostgreSQL 에서도 통합 테스트 실행(테스트가 스키마를 지우고 다시 만듭니다. 전용 DB 를 쓰세요)
BID_TEST_PG_URL=postgresql+psycopg://bid:<비밀번호>@localhost:5432/bid_test pytest
```

## 웹 화면 (개발)

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173 (백엔드 8000 번으로 /api 전달)
npm test           # Vitest
```

가상 샘플 데이터를 넣어 보려면 서버를 켠 뒤 `BID_USERNAME=admin python scripts/load_sample_data.py` 를 실행합니다(운영 DB 에는 넣지 마세요).

## 구조

```
backend/
  app/engines/calc    법정 계산 엔진(순수 함수, Decimal)
  app/engines/rules   규칙 정의·유효기간·검증상태·선택·평가
  app/db              SQLAlchemy 모델(SQLite·PostgreSQL 겸용)
  app/api             FastAPI 라우터
  alembic             마이그레이션
  tests               단위·통합 테스트
frontend/             React + TypeScript 웹 화면(17개 메뉴), Vitest, e2e(Playwright)
scripts/              샘플 데이터 등록 등 보조 스크립트
docs/                 설계·진행·제한사항 문서
```
