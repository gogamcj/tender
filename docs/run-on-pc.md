# 내 PC 에서 실행하기 (처음 하는 분용)

내 컴퓨터에서만 쓰는 방법입니다. 프로그램 3개를 Docker 가 한꺼번에 띄워 줍니다(데이터베이스, 서버, 웹 화면).
한 번 설치해 두면 다음부터는 **Docker Desktop 만 켜면** 브라우저로 바로 쓸 수 있습니다.

필요한 것: Windows 10/11(64비트) 또는 Mac, 메모리 8GB 이상 권장, 디스크 여유 10GB, 인터넷.

---

## 1단계. Docker Desktop 설치 (처음 한 번)

1. https://www.docker.com/products/docker-desktop/ 에서 내 PC 에 맞는 버전을 내려받아 설치합니다.
   - Windows 설치 옵션: **All-users installation** 선택, 아래는 **WSL 2**, **Allow Windows Containers 는 체크 해제**. 관리자 권한을 물으면 '예'. 설치 후 **재부팅**합니다.
     (Per-user 를 고르면 처음 설치하는 PC 에서는 "Virtual Machine Platform" 기능이 없다며 실패합니다. 그때는 All-users 로 다시 설치하거나, 관리자 PowerShell 에서 `wsl --install` → 재부팅 후 다시 설치)
   - Docker 실행 시 "가상화(Virtualization)가 꺼져 있다"고 나오면 PC 의 BIOS 설정에서 가상화(Intel VT-x / AMD SVM)를 켜야 합니다.
   - "WSL 업데이트가 필요하다"는 창이 나오면 안내대로 업데이트합니다.
2. Docker Desktop 을 실행합니다. 처음에 나오는 로그인·설문은 건너뛰어도 됩니다.
3. 화면 왼쪽 아래가 **초록색 "Engine running"** 이 되면 준비 완료입니다(1~2분).

> Docker Desktop 은 개인·소규모 사업자(직원 250명 미만, 연매출 1천만 달러 미만)는 무료입니다.

## 2단계. 프로그램 내려받기 (처음 한 번)

1. 브라우저에서 https://github.com/gogamcj/tender 로 갑니다.
2. 왼쪽 위 브랜치 선택에서 **`main`** 을 고릅니다(아직 PR 을 합치지 않았다면 `claude/bid-analyzer`).
3. 초록색 **`<> Code`** 버튼 → **Download ZIP**
4. 받은 ZIP 을 원하는 곳에 압축 풉니다. 예: `C:\tender`
   - 압축을 풀면 폴더 안에 또 폴더가 있을 수 있습니다. **`docker-compose.yml` 파일이 바로 보이는 폴더**가 작업 폴더입니다.

## 3단계. 설정 파일 만들기 (처음 한 번)

1. 작업 폴더에서 `.env.example` 파일을 복사해 붙여넣고, 이름을 **`.env`** 로 바꿉니다.
   - Windows 탐색기에서 안 보이면: 탐색기 상단 **보기 → 표시 → 파일 확장명, 숨긴 항목** 체크
   - 이름이 `.env.txt` 가 되지 않게 주의하세요.
2. `.env` 를 **메모장**으로 엽니다(마우스 오른쪽 → 연결 프로그램 → 메모장).
3. 다음 두 줄을 고치고 저장합니다.
   ```
   POSTGRES_PASSWORD=영문과숫자로만20자이상아무렇게나
   BID_DATA_GO_KR_SERVICE_KEY=공공데이터포털에서_받은_Decoding_키
   ```
   - 비밀번호에는 **영문·숫자만** 쓰세요(특수문자 X). 예: `k8Rt2mQx9vLp4Wz7Bn3s`
   - API 키가 아직 없으면 비워 둬도 됩니다. 엑셀 업로드·분석 기능은 키 없이 쓸 수 있고, 데이터 수집만 안 됩니다. 키 받는 법은 [API 인증 안내](api-auth-guide.md).

## 4단계. 실행하기 (처음 한 번은 5~10분)

1. 작업 폴더를 연 탐색기 주소창에 `powershell` 이라고 입력하고 Enter → 그 폴더에서 파란 창이 열립니다.
   (Mac: 터미널을 열고 `cd ` 입력 후 작업 폴더를 창에 끌어다 놓고 Enter)
2. 다음을 입력하고 Enter:
   ```
   docker compose up -d --build
   ```
   처음에는 필요한 것들을 내려받고 만드느라 시간이 걸립니다. 다시 입력 줄이 나오면 끝난 것입니다.
3. 잘 떴는지 확인:
   ```
   docker compose ps
   ```
   `db`, `backend` 옆에 **(healthy)**, `frontend` 옆에 **Up** 이 보이면 성공입니다. backend 가 `starting` 이면 30초 뒤 다시 확인하세요.

## 5단계. 관리자 계정 만들기 (처음 한 번)

```
docker compose exec backend python -m app.cli create-user admin --role admin
```
비밀번호를 두 번 물어봅니다(**10자 이상**). 입력하는 글자가 화면에 안 보이는 것이 정상입니다.

## 6단계. 사용하기

브라우저에서 **http://localhost:8080** → 사용자 이름 `admin`, 방금 정한 비밀번호로 로그인.

처음이라 데이터가 비어 있습니다. 둘러보고 싶으면:
- 메뉴 **14. 엑셀 업로드 관리** → 작업 폴더의 `backend\seed\sample_history.csv`(가상 샘플 240건) 업로드 → 업로드·분석 → 변환 옵션의 "투찰률 기준"을 **예정가격**으로 → 검사·미리보기 → 저장
- 샘플은 가짜 데이터입니다. 다 본 뒤에는 업로드 이력에서 **되돌리기**로 지우세요.

실제로 쓸 때는 가지고 있는 개찰결과 엑셀을 올리거나, API 키를 넣고 **13. 데이터 수집 관리**에서 수집합니다(관리자만).

---

## 매일 쓰는 법

| 하고 싶은 것 | 방법 |
|---|---|
| 켜기 | Docker Desktop 실행 → 잠시 뒤 http://localhost:8080 (자동으로 다시 켜집니다) |
| 안 켜지면 | 작업 폴더에서 PowerShell → `docker compose up -d` |
| 끄기 | `docker compose stop` (또는 Docker Desktop 종료) |
| 다른 사람 계정 | 17. 시스템 설정 → 사용자 관리 |
| 설정(.env) 바꾼 뒤 | `docker compose up -d` |

데이터는 Docker 안에 저장되어 PC 를 껐다 켜도 남아 있습니다.
**`docker compose down -v` 는 데이터를 전부 지우는 명령이니 쓰지 마세요.**

## 백업

중요한 자료(원가 등)를 넣었다면 가끔 백업하세요.
- Windows: [Git for Windows](https://git-scm.com/download/win) 를 설치하면 생기는 **Git Bash** 를 작업 폴더에서 열고 `scripts/backup.sh`
- Mac: 터미널에서 `scripts/backup.sh`
- `backups` 폴더에 날짜별로 생깁니다. USB·클라우드 드라이브에 복사해 두세요. 복원은 [백업·복원](backup-restore.md).

## 새 버전으로 바꾸기

1. 먼저 백업
2. 새 ZIP 을 받아 **기존 작업 폴더에 덮어쓰기**(`.env` 는 ZIP 에 없으므로 그대로 유지됨)
3. `docker compose up -d --build`

## 잘 안 될 때

| 증상 | 해결 |
|---|---|
| `docker` 를 찾을 수 없다 | Docker Desktop 이 설치·실행 중인지, PowerShell 을 새로 열었는지 |
| `POSTGRES_PASSWORD 를 설정하세요` | `.env` 이름(`.env.txt` 아님)과 위치(`docker-compose.yml` 과 같은 폴더) 확인 |
| `port is already allocated` (8080 또는 5432) | 다른 프로그램이 같은 번호를 씀. `.env` 에 `BID_WEB_PORT=8090` 또는 `BID_DB_PORT=5433` 추가 후 다시 실행(웹 주소도 :8090 으로) |
| backend 가 계속 `unhealthy`/재시작 | `docker compose logs backend` 의 마지막 줄을 보내 주세요 |
| 비밀번호를 바꿨더니 DB 오류 | 처음 실행 때의 비밀번호로 DB 가 만들어져 있습니다. `.env` 비밀번호를 원래대로 돌리세요 |
| 로그인 5번 틀려서 잠김 | 15분 기다리기 |
| 관리자 비밀번호를 잊음 | 5단계 명령을 다른 이름(예: `admin2`)으로 실행해 새 관리자 생성 후, 설정 화면에서 기존 계정 비밀번호 재설정 |
| 화면이 너무 느림 | Docker Desktop → Settings → Resources 에서 메모리를 4GB 이상으로 |

다른 PC 나 휴대폰에서 접속하는 것은 보안상 기본으로 막혀 있습니다(이 PC 에서만 접속). 필요하면 [설치 매뉴얼 3절](install.md)을 보세요.
