# 공공입찰 통합 분석 및 투찰금액 추천 시스템 — 설계안 (v0.1)

작성일: 2026-10-27 · 상태: 검토 요청

이 문서는 요구사항 21항에 따라 구현 전에 제시하는 아키텍처, 데이터 모델, 핵심 산식, API 연동 가능 범위, 단계별 개발 계획입니다. 여기 적힌 "확인됨/미확인" 표시는 실제로 확인한 범위를 그대로 적은 것입니다.

---

## 1. 아키텍처

단일 백엔드(모놀리식) + 단일 SPA 구조입니다. 마이크로서비스는 쓰지 않습니다.

```
┌──────────────── 브라우저 (PC / 모바일) ────────────────┐
│ React + TypeScript + Vite + Tailwind + Recharts         │
│ TanStack Query (서버 상태), React Router                │
└──────────────────────────┬──────────────────────────────┘
                           │ REST / JSON (OpenAPI 자동 문서)
┌──────────────────────────▼──────────────────────────────┐
│ FastAPI (Python 3.12+)                                  │
│  api/          라우터 (얇은 계층, 검증·권한만)          │
│  services/     유스케이스 (업로드, 수집, 분석 실행 저장) │
│  engines/                                               │
│    calc/       법정 계산 엔진 (순수 함수, Decimal)      │
│    rules/      규칙 레지스트리·유효기간·검증상태        │
│    reserve/    복수예비가격·사정률 분포 분석            │
│    stats/      과거 낙찰 통계, 유사입찰 검색            │
│    recommend/  투찰 시나리오 엔진 (calc와 분리)          │
│    cost/       원가·수익성                              │
│    qualify/    적격심사·자격 체크리스트                 │
│  connectors/   API별 독립 커넥터 (G2B 입찰공고, 낙찰,   │
│                개방표준, 사용자 정의 확장)               │
│  importers/    XLSX/CSV/XLS 파서, 열 매핑, 중복 검사    │
│  pdf/          공고문 텍스트·표 추출 (pdfplumber),      │
│                OCR은 선택(Tesseract 설치 시)             │
│  reports/      XLSX/CSV 내보내기                        │
│  db/           SQLAlchemy 2.0 모델 + Alembic            │
└──────────────────────────┬──────────────────────────────┘
                           │
              PostgreSQL 16 (운영) / SQLite (개발·테스트)
```

설계 원칙
- 계산 엔진(`engines/calc`)은 DB·HTTP에 의존하지 않는 순수 함수입니다. 입력·규칙·출력이 모두 직렬화 가능하여 `analysis_runs.input_snapshot`으로 재현할 수 있습니다.
- 추천 엔진은 계산 엔진을 호출만 하고, 계산 엔진은 추천 엔진을 모릅니다.
- 모든 금액은 `Decimal`, DB는 `NUMERIC(18,0)`(원), 비율은 `NUMERIC(9,6)`(%)로 저장합니다. float는 통계 계산 내부(NumPy)에서만 쓰고, 금액으로 되돌릴 때 규칙의 절사 방식으로 Decimal 변환합니다.
- SQLite/PostgreSQL 겸용: SQLAlchemy 표준 타입만 사용하고 JSON 컬럼은 `JSON`(PG에서는 `JSONB` variant)으로 둡니다. 마이그레이션은 Alembic 하나로 관리합니다.
- 외부 API가 죽어도 조회·업로드·수동입력·분석은 DB만으로 동작합니다.
- 비밀정보(API 키, DB 비밀번호, JWT 비밀키)는 `.env`/환경변수에서만 읽습니다.

인증: 초기 버전은 개인·소규모 업체용으로 로컬 계정(관리자/일반) + Argon2 비밀번호 해시 + HttpOnly 쿠키 세션(JWT 서명, 만료·CSRF 토큰)으로 구현합니다. 원가 자료(`company_costs`)는 소유자와 관리자만 조회합니다.

## 2. 디렉터리 구조 (계획)

```
bid-analyzer/
├─ backend/
│  ├─ app/ (api, services, engines, connectors, importers, pdf, reports, db, core)
│  ├─ alembic/  alembic.ini
│  ├─ tests/ (unit/calc, unit/importers, unit/connectors, unit/recommend, integration)
│  ├─ seed/ (샘플 데이터: 명백히 '샘플' 표시)
│  └─ pyproject.toml
├─ frontend/ (src/pages, src/components, src/api, src/lib, tests)
├─ docs/ (설치, API 인증, 업로드 안내, 백업·복원, 알려진 제한사항, 규칙 근거)
├─ scripts/ (backup.sh, restore.sh, verify_restore.sh)
├─ docker-compose.yml  .env.example  README.md
```

## 3. 데이터 모델

요구사항 7장의 컬럼을 모두 포함하고, 다음을 추가합니다.

| 테이블 | 핵심 추가 사항 |
|---|---|
| `procurement_notices` | 유일성: `(source_name, notice_number, notice_revision)`. 같은 공고번호의 차수별 행을 모두 보존하고 `is_latest_revision`, `superseded_by_id` 로 최신본을 가리킴. `procurement_category`(공사/용역/물품/외자/기타), `bid_type_id`(입찰유형 FK), `phase`(개찰전/개찰후), `estimated_price_status`(확정/사용자가정/과거기반예상/시나리오/미상) |
| `notice_raw_records` | 수집·업로드 원본(JSON/행 원문) 보존. `collected_at`, `source_name`, `payload_hash`. 정규화 테이블과 1:N |
| `notice_revisions_log` | 같은 공고의 필드별 변경 전후 값 (정정공고·재업로드 비교 확인용) |
| `bid_types` | 입찰유형 분류 체계: 대분류, 발주기관 유형(국가/지자체/공기업 등), 계약방법, 낙찰자 결정방식, 금액구간, 지역제한, 관련 면허, 적용 규정 → `bid_rules` 와 N:M |
| `bid_results` | `notice_id` FK(ON DELETE RESTRICT). `opening_status`(개찰완료/유찰/재입찰/결과미확인). `winning_rate_basis`(예정가격/기초금액/추정가격) 필수. `actual_sajeong_rate`는 내부 정의로 재계산한 값만 저장하고, 외부가 준 값은 `external_metrics` JSON에 원문 그대로 |
| `bid_candidates` | 공개된 경우에만. `(result_id, ranking, vendor_identifier)` 유일 |
| `reserve_prices` | 복수예비가격 상세가 공개된 경우 번호·금액·추첨 여부 |
| `bid_rules` | 요구 컬럼 + `formula_definition`(JSON DSL: 사용할 산식 모듈 ID와 파라미터), `rounding_rule`, `verification_status`(검증됨/미검증/폐지). 유효기간 판정은 공고일 기준 |
| `notice_rule_links` | 공고별 적용 규칙 (자동 매칭 결과 + 사용자 확정 여부) |
| `pdf_documents`, `pdf_extractions` | 추출 항목별 값, 페이지, 표 좌표, 신뢰도, 검토상태(미검토/확인/수정/거부) |
| `analysis_runs`, `bid_scenarios` | 요구 컬럼 그대로. `dataset_version` = 분석 시점 데이터 해시+건수 |
| `company_costs`, `company_profiles`, `saved_filters`, `favorites` | 요구 컬럼 + `owner_user_id` |
| `qualification_checks` | 항목별 배점, 점수상태(확인/예상/미확인), 근거 |
| `data_import_jobs`, `data_collection_jobs`, `app_events` | 업로드·수집 이력, 오류·경고 로그 |
| `users` | 계정, 역할, 해시 |

삭제 정책: 공고 삭제는 원칙적으로 금지하고 `data_status='분석 제외'`로 처리합니다. 업로드 작업 단위 롤백만 허용(해당 작업이 넣은 행만 삭제). 분석 결과는 공고 삭제 시 함께 지우지 않도록 RESTRICT.

데이터 상태: 요구 5.3의 8개 상태를 enum으로 두고, "개찰 결과 미확인"과 "유찰"을 분리합니다. 조회되지 않은 경우는 `not_found_reason`(조회기간 밖/공급범위 밖/실제 없음 확인/미조회)으로 구분합니다.

## 4. 핵심 산식 (내부 정의)

모든 금액은 원 단위 Decimal, 비율은 % 단위 Decimal입니다. 비율 입력은 % 와 소수(0.87745)를 자동 추정하지 않고 단위를 명시받습니다.

1. 사정률(%) = (예정가격 − 기초금액) ÷ 기초금액 × 100
2. 예정가격(가정) = 기초금액 × (1 + 사정률/100)
3. 낙찰하한금액 = 기준가격 × 낙찰하한율 → 공고·규칙의 절사 방식 적용. 규칙에 절사 방식이 없으면 계산은 하되 "절사 규칙 미확인" 경고를 붙이고 원 미만 값을 그대로 노출
4. 투찰률(%) = 투찰금액 ÷ 기준금액 × 100, 기준금액은 `rate_basis`(예정가격/기초금액)로 반드시 지정
5. 부가세: 공급가액 = 총액 − 세액, 세액은 공고에 명시된 값 우선. 계산 시 `vat_included` 플래그가 없으면 계산 거부
6. 원가: 총원가 = Σ(항목), 손익분기 투찰금액 = 총원가(+ 부가세 처리 방식 반영), 목표이익 달성 금액 = 총원가 + 목표이익(또는 총원가 ÷ (1 − 목표이익률))
7. 시나리오 하한 여유 = 후보금액 − 가정 하한금액. 예정가격이 미확정이면 결과 상태는 항상 "가정 기반 분석"

복수예비가격: 국가계약은 기초금액 ±2% 범위 15개·2개 추첨·상위 4개 평균, 지자체는 ±3% 범위로 널리 알려져 있으나, 이는 아직 이 프로젝트에서 원문 예규로 확인하지 않았습니다. 따라서 규칙 테이블에 "미검증"으로 등록하고, 이 규칙을 쓰는 시뮬레이션은 "미검증 규칙 기반 시나리오"로 표시합니다. 원문(기획재정부 계약예규 「예정가격 작성기준」, 행정안전부 예규 「지방자치단체 입찰 및 계약집행기준」)을 확인해 사용자가 검증 처리하면 경고가 사라집니다.

낙찰하한율·적격심사 배점: 기관·금액구간·시점별로 다르고 개정이 잦습니다. 프로그램에 하드코딩하지 않고 규칙 데이터로만 넣으며, 초기 씨앗 데이터는 모두 "미검증"으로 넣습니다. 미검증 규칙으로는 "확정 추천"을 만들지 않습니다.

## 5. API 연동 가능 범위 (2026-10-27 조사 결과)

공공데이터포털 상세 페이지에서 확인한 내용입니다. 응답 필드 목록은 포털 페이지에 비어 있고 첨부 참고문서(docx)에만 있는데, 현재 개발 환경에서는 data.go.kr 접속이 차단되어 docx와 실제 응답을 직접 받아보지 못했습니다.

| 서비스 | Base URL (확인됨) | 확인된 오퍼레이션 | 개발계정 트래픽 | 비고 |
|---|---|---|---|---|
| 나라장터 입찰공고정보서비스 (15129394) | `https://apis.data.go.kr/1230000/ad/BidPublicInfoService` | `getBidPblancListInfoCnstwk`(공사). 물품·용역·외자는 업무별 오퍼레이션 별도 | 1,000회/일 | 필수: serviceKey, pageNo, numOfRows, inqryDiv. 선택: inqryBgnDt/inqryEndDt(YYYYMMDDHHMM), bidNtceNo, type=json |
| 나라장터 낙찰정보서비스 (15129397) | `https://apis.data.go.kr/1230000/as/ScsbidInfoService` | `getScsbidListSttusThng` 등. 개찰결과·최종낙찰자·예비가격상세·투찰업체별 결과 계열 제공 | 1,000회/일 | 응답이 느림(대량 행 요청 시 타임아웃 사례 보고) → 페이지 크기 작게 |
| 나라장터 공공데이터개방표준서비스 (15058815) | `https://apis.data.go.kr/1230000/ao/PubDataOpnStdService` | `getDataSetOpnStdBidPblancInfo` (확인), 낙찰·계약 계열 오퍼레이션은 2차 출처에서만 확인 | 10,000회 | 공고일 조회기간 1개월 제한, 현재 임시로 1주로 단축 공지 |
| 계약과정통합공개서비스 | 미확인 | — | — | 2단계에서 조사 |
| 지자체 | 지자체 발주분 대부분이 나라장터에 게시되어 위 API로 수집 가능. 별도 지자체 API는 기관별로 조사 필요(LH 등 공기업은 자체 API 존재 확인) | | | |

공통: 인증은 serviceKey(디코딩 키 사용 권장), 오류코드 20/30/31(키 문제), 22(일 한도 초과), 23(초당 한도 초과). JSON/XML 지원.

이에 따른 구현 방침
- 커넥터는 오퍼레이션명·필드명 매핑을 설정 파일(YAML)로 분리해, 참고문서와 다르면 코드 수정 없이 고칠 수 있게 합니다.
- 실제 응답 필드명이 확인되기 전까지 커넥터는 "명세 미검증" 상태로 표시되고, 테스트는 녹화된 가짜 응답(fixture)으로만 돌립니다. 사용자 API 키로 첫 실호출 시 응답 구조 검증 도구(`scripts/probe_api.py`)가 필드 차이를 보고하게 합니다.
- 일 한도 보호: 커넥터별 일일 호출 카운터를 DB에 저장해 한도의 90%에서 중단, 초당 호출 간격 제한, 지수 백오프 재시도(최대 3회), 타임아웃 30초.

참고 출처: [입찰공고정보서비스](https://www.data.go.kr/en/data/15129394/openapi.do), [낙찰정보서비스](https://www.data.go.kr/en/data/15129397/openapi.do), [개방표준서비스](https://www.data.go.kr/en/data/15058815/openapi.do), [opendata-kr/narajangteo-opening-mcp](https://github.com/opendata-kr/narajangteo-opening-mcp)(응답 지연·키 인코딩 주의사항)

## 6. 단계별 개발 계획

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 1 | 저장소 골격, 백엔드 설정, DB 모델 전체 + Alembic 초기 마이그레이션, 계산 엔진(사정률·하한금액·투찰률·부가세·절사), 규칙 레지스트리(유효기간·검증상태) | pytest 계산 테스트 전부 통과, SQLite·PostgreSQL 양쪽 마이그레이션 성공 |
| 2 | 엑셀·CSV 업로드: 시트·열 분석, 열 매핑, 형식 변환, 누락·중복·오류 검사, 미리보기, 확정 저장, 결과 보고서, 원본 보존, 변경 전후 비교 | 인코딩(UTF-8/CP949/EUC-KR)·중복·잘못된 날짜 테스트 통과 |
| 3 | API 커넥터 3종 + 수집 작업(기간·기관·유형·검색어), 한도·재시도·페이지네이션·원본 보존·정정 이력·상태 관리 | 가짜 응답 기반 테스트 통과, 실키로 프로브 가능 |
| 4 | 분석 엔진: 기간·기관·공종·지역·금액구간·결정방식·참가업체수별 통계, 사정률 분포, 이상치 처리, 유사 입찰 검색(선정 근거 포함) | 통계·혼합 금지 규칙 테스트 통과 |
| 5 | 추천 엔진(보수/중간/공격/직접), 원가·수익성, 적격심사 체크리스트, 분석 실행 저장·재현 | 데이터 없음·표본 부족·시간 누출 방지 테스트 통과 |
| 6 | PDF 공고문 분석: 텍스트·표 추출, 항목별 페이지·신뢰도·검토상태, 검토값 우선 사용 | 샘플 PDF 추출 테스트 통과 |
| 7 | 프런트엔드 17개 메뉴, 반응형, 차트(분석기간·표본수·기준금액·출처 표시, 표본 부족 경고) | Vitest 컴포넌트 테스트 + Playwright 모바일/PC 스냅샷 |
| 8 | 보고서 XLSX/CSV, 인증·권한, Docker Compose, 백업·복원 스크립트, 문서 일체, 처음부터 설치 검증 | 깨끗한 환경에서 `docker compose up` → 시나리오 통과 |

낙찰 확률: 이번 계획에는 넣지 않습니다. 충분한 실제 데이터가 쌓인 뒤 시간 순서 분할 검증으로 보정(calibration)이 확인될 때만 표시하는 선택 기능으로 남깁니다.

## 7. 지금 확인이 필요한 사항

1. 코드 저장소: 연결된 저장소가 `howlguard-mac` 하나뿐이라 새 GitHub 저장소가 필요합니다(예: `bid-analyzer`). GitHub에서 직접 만든 뒤 이름을 알려 주세요.
2. 공공데이터포털 API 키: 개발 환경에서는 data.go.kr이 막혀 있어 실호출 검증은 사용자 PC에서 하게 됩니다.
