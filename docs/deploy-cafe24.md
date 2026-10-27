# 카페24 서버에 배포하기

## 1. 어떤 상품이어야 하나
이 시스템은 Python 서버(FastAPI)와 PostgreSQL 이 **계속 실행**되어야 하고, Docker Compose 로 설치합니다.

| 카페24 상품 | 가능 여부 |
|---|---|
| 일반 웹호스팅·쇼핑몰·워드프레스 호스팅(PHP + MySQL) | **불가.** 서버 관리자 권한이 없어 Docker·Python 상주 프로세스·PostgreSQL 을 쓸 수 없습니다 |
| 가상서버호스팅(VPS)·클라우드 서버·단독서버(관리자 root 권한, 리눅스) | **가능.** 아래 절차대로 설치 |

권장 사양: Ubuntu 22.04 또는 24.04, 메모리 **4GB**(최소 2GB — 2GB 면 아래 4-1의 스왑 추가 필수), 디스크 30GB 이상.
상품 이름·사양은 카페24 쪽에서 바뀔 수 있으니 신청 전에 "root 권한", "OS 선택(Ubuntu)", "Docker 설치 가능" 여부를 확인하세요.

## 2. 준비물
- 서버 공인 IP, root(또는 sudo) 계정 비밀번호 또는 SSH 키 — 카페24 관리 화면에서 확인
- 도메인(예: bid.example.com). 카페24 에서 산 도메인이면 카페24 DNS 관리에서 설정
- 공공데이터포털 인증키(Decoding 키)
- GitHub 저장소가 비공개라면 서버에서 받을 수 있는 방법(아래 4-3)

## 3. 도메인 연결
DNS 관리에서 **A 레코드**: `bid.example.com` → 서버 공인 IP. 반영까지 수 분~수 시간 걸릴 수 있습니다.

## 4. 서버 설치 (SSH 로 접속해서 실행)
```bash
ssh root@서버IP
```

### 4-1. 기본 설정
```bash
apt update && apt -y upgrade
timedatectl set-timezone Asia/Seoul
# 메모리 2GB 서버라면 스왑 2GB 추가(웹 화면 빌드 중 메모리 부족 방지)
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 4-2. Docker 설치
```bash
curl -fsSL https://get.docker.com | sh
docker compose version     # 버전이 나오면 정상
```

### 4-3. 코드 받기
```bash
mkdir -p /opt && cd /opt
git clone https://github.com/gogamcj/tender.git && cd tender
```
저장소가 비공개면 GitHub → Settings → Developer settings → Personal access tokens(Fine-grained, 이 저장소 읽기 전용)를 만들어, 비밀번호를 물을 때 토큰을 입력합니다. 토큰은 서버의 파일에 적어 두지 마세요.

### 4-4. 설정 파일
```bash
cp .env.example .env
python3 -c "import secrets;print(secrets.token_urlsafe(24))"   # 출력값을 DB 비밀번호로
nano .env
```
고칠 값:
```
POSTGRES_PASSWORD=위에서_만든_값
BID_DATA_GO_KR_SERVICE_KEY=공공데이터포털_Decoding_키
BID_COOKIE_SECURE=true          # HTTPS 로 운영하므로
```
`chmod 600 .env` 로 다른 계정이 못 읽게 합니다.

### 4-5. 실행
```bash
docker compose up -d --build          # 처음 5~10분
docker compose ps                     # db·backend 가 healthy 면 정상
docker compose exec backend python -m app.cli create-user admin --role admin
```
웹은 서버 안에서만 열린 상태(127.0.0.1:8080)입니다. 다음 단계에서 HTTPS 로 바깥에 엽니다.

## 5. HTTPS 연결 (Caddy, 인증서 자동 발급·갱신)
```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
cat > /etc/caddy/Caddyfile <<'CADDY'
bid.example.com {
    encode gzip
    request_body {
        max_size 25MB
    }
    reverse_proxy 127.0.0.1:8080
}
CADDY
systemctl reload caddy
```
`bid.example.com` 을 실제 도메인으로 바꾸세요. 브라우저에서 `https://bid.example.com` 접속 → 로그인.

## 6. 방화벽
- 서버: `ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable`
- 카페24 관리 화면에 방화벽(접근 제어) 설정이 있으면 80·443 을 열어 둡니다. 5432(DB)·8080 은 **열지 마세요**(설정상 서버 안에서만 접속됨).
- 가능하면 SSH(22)는 사무실 IP 에서만 허용하고, 비밀번호 대신 SSH 키 로그인을 쓰세요.

## 7. 공공데이터 API 확인
서버에서 실제 응답을 받아 필드명을 확인합니다(개발 중에는 확인하지 못한 부분).
```bash
docker compose exec backend python -m app.cli probe --out /data/storage/probe_samples
docker compose cp backend:/data/storage/probe_samples ./probe_samples
```
`probe_samples` 폴더를 압축해 전달해 주시면 응답 필드 대응을 맞추겠습니다(인증키는 파일에 들어가지 않습니다).

## 8. 백업 (매일 자동)
```bash
crontab -e
# 아래 한 줄 추가: 매일 새벽 3시 백업, 30일 지난 것 삭제
0 3 * * * cd /opt/tender && scripts/backup.sh >> backups/backup.log 2>&1 && find backups -maxdepth 1 -type d -mtime +30 -name '20*' -exec rm -rf {} +
```
서버가 망가지면 백업도 함께 사라지므로, `backups/` 를 주기적으로 다른 곳(사무실 PC, 카페24 백업 상품 등)에 복사하세요. 자세한 내용은 [백업·복원](backup-restore.md).

## 9. 업데이트
```bash
cd /opt/tender
scripts/backup.sh
git pull
docker compose up -d --build
```

## 10. 자주 막히는 곳
| 증상 | 확인 |
|---|---|
| `https://` 접속이 안 됨 | DNS A 레코드 반영 여부(`ping bid.example.com`), 80·443 방화벽, `journalctl -u caddy` |
| 로그인해도 다시 로그인 화면 | `http://` 로 접속 중인데 `BID_COOKIE_SECURE=true` → https 로 접속 |
| 빌드 중 멈춤·`Killed` | 메모리 부족 → 4-1 스왑 추가 |
| 업로드가 413 오류 | Caddyfile 의 `max_size` 확인 |
| Docker 이미지 받기 실패(429) | Docker Hub 요청 한도. 몇 분 뒤 다시 실행 |
