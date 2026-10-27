# 설치 매뉴얼

## 1. 준비물
- Docker Desktop(Windows·macOS) 또는 Docker Engine + Compose 플러그인(Linux). `docker compose version` 이 나와야 합니다.
- 디스크 여유 5GB 이상(이미지·DB·업로드 원본)
- 공공데이터포털 인증키(수집 기능을 쓸 때만). [API 인증 안내](api-auth-guide.md)

## 2. 설치 (Docker Compose, 권장)
```bash
git clone https://github.com/gogamcj/tender.git && cd tender
cp .env.example .env
```
`.env` 를 열어 최소한 다음을 고칩니다.
- `POSTGRES_PASSWORD`: `python3 -c "import secrets;print(secrets.token_urlsafe(24))"` 로 만든 값(영문·숫자·`-_` 만)
- `BID_DATA_GO_KR_SERVICE_KEY`: 수집 기능을 쓸 경우 Decoding 키

```bash
docker compose up -d --build        # 처음에는 이미지 빌드로 몇 분 걸립니다
docker compose ps                   # db·backend 가 healthy, frontend 가 Up 이면 정상
docker compose exec backend python -m app.cli create-user admin --role admin   # 첫 관리자(비밀번호 입력 프롬프트)
```
브라우저에서 **http://localhost:8080** 에 접속해 로그인합니다. 다른 사용자는 '17. 시스템 설정 → 사용자 관리'에서 추가합니다(권한: 관리자·일반·조회 전용).

백엔드는 시작할 때마다 DB 마이그레이션을 자동 적용합니다.

### 가상 샘플 데이터로 둘러보기(선택)
```bash
BID_API_URL=http://localhost:8080 BID_USERNAME=admin python3 scripts/load_sample_data.py   # httpx 필요: pip install httpx
```
가상 공고 240건과 '미검증' 예시 규칙을 넣습니다. 실제 분석용 DB 에는 넣지 마세요. 되돌리려면 '14. 엑셀 업로드 관리'에서 해당 업로드를 되돌리고 '15. 규칙 관리'에서 예시 규칙을 '사용 중지'로 바꿉니다.

## 3. 다른 컴퓨터에서 접속하기
기본값은 이 컴퓨터(127.0.0.1)에서만 접속됩니다. 사내망에 열려면:
1. 앞단에 HTTPS 리버스 프록시(nginx, Caddy 등)를 두고 `http://127.0.0.1:8080` 으로 넘깁니다.
2. `.env` 에 `BID_COOKIE_SECURE=true` 를 넣고 `docker compose up -d` 로 다시 시작합니다(로그인 쿠키를 HTTPS 에서만 보냄).
3. HTTPS 없이 `BID_WEB_BIND=0.0.0.0` 으로 여는 것은 권장하지 않습니다(비밀번호가 평문으로 오감).
DB 포트(5432)는 이 컴퓨터에만 열려 있습니다. 외부에 열지 마세요.

## 4. 업데이트
```bash
scripts/backup.sh                 # 먼저 백업
git pull
docker compose up -d --build      # 새 이미지로 다시 시작, 마이그레이션 자동 적용
```

## 5. 중지·삭제
- 중지: `docker compose stop` / 다시 시작: `docker compose start`
- 컨테이너 삭제(데이터 유지): `docker compose down`
- **데이터까지 삭제**: `docker compose down -v` — DB 와 업로드 원본이 모두 지워집니다. 먼저 백업하세요.

## 6. 개발 모드(Docker 없이)
[README](../README.md)의 '빠른 시작' 참고. 백엔드 `uvicorn`(8000) + 프런트엔드 `npm run dev`(5173). 개발용 SQLite 를 쓰거나 `docker compose up -d db` 로 PostgreSQL 만 띄울 수 있습니다.

## 7. 문제 해결
| 증상 | 확인 |
|---|---|
| `POSTGRES_PASSWORD 를 설정하세요` | `.env` 가 저장소 최상위에 있는지 |
| backend 가 unhealthy | `docker compose logs backend` — DB 비밀번호에 `@ : /` 같은 문자가 있으면 바꾸고, 이미 만든 DB 는 처음 비밀번호를 유지합니다(`docker compose down -v` 전에는 바뀌지 않음) |
| 로그인 직후 다시 로그인 화면 | HTTP 로 접속하면서 `BID_COOKIE_SECURE=true` 로 둔 경우 |
| 계정 잠김 | 5회 실패 시 15분 잠김. 관리자가 '비밀번호 재설정' 가능 |
| 수집이 '한도 보호 중단' | 오늘 호출이 일일 한도의 90%에 도달. 다음 날 다시 실행하거나 운영계정 한도를 `.env` 에 반영 |
| 업로드 '파일이 너무 큼' | 20MB 이하로 나누어 올리기 |
