# 백업·복원 매뉴얼

## 무엇을 백업하나
| 대상 | 내용 | 백업 방법 |
|---|---|---|
| PostgreSQL | 공고·결과·규칙·분석 기록·원가·사용자 등 전부 | `scripts/backup.sh` (pg_dump) |
| 업로드 원본(storage) | 올린 엑셀·CSV·PDF 원본 | `scripts/backup.sh` (tar) |
| `.env` | DB 비밀번호·API 키 | **스크립트에 포함하지 않음.** 비밀번호 관리 도구 등 따로 안전하게 보관 |

## 백업
```bash
scripts/backup.sh                 # ./backups/YYYYMMDD-HHMMSS/ 에 생성
scripts/backup.sh /mnt/nas/bid    # 다른 위치
```
결과 폴더: `db.dump`(PostgreSQL custom 형식), `storage.tar.gz`, `manifest.txt`(시각·마이그레이션 버전·공고 수), `SHA256SUMS`.
스크립트는 끝에 덤프를 다시 읽어 깨지지 않았는지 확인합니다. 파일 권한은 소유자만 읽기(600)입니다.

정기 백업 예(Linux cron, 매일 새벽 2시, 30일 지난 백업 삭제):
```
0 2 * * * cd /opt/tender && scripts/backup.sh >> backups/backup.log 2>&1 && find backups -maxdepth 1 -type d -mtime +30 -name '20*' -exec rm -rf {} +
```
백업은 다른 디스크나 다른 컴퓨터에도 복사해 두세요.

## 복원
```bash
scripts/restore.sh backups/20261027-120000
```
1. 체크섬으로 백업 파일 손상 여부 확인
2. `RESTORE` 를 입력해야 진행(자동화할 때만 `--yes`)
3. **현재 상태를 `backups/before-restore/` 에 먼저 자동 백업** — 복원이 잘못되면 이 폴더로 다시 복원
4. 백엔드·웹 중지 → DB 를 지우고 백업으로 다시 만듦 → 업로드 원본 교체 → 백엔드·웹 시작(새 버전이면 마이그레이션 자동 적용)

복원 중 오류가 나면 안전 백업 경로를 알려 주고 멈춥니다. 백엔드가 멈춰 있으면 `docker compose up -d` 로 켭니다.

## 다른 서버로 옮기기
새 서버에 설치(설치 매뉴얼 1~2단계, 관리자 생성은 생략) → 기존 `.env` 의 API 키 등을 옮김 → 백업 폴더 복사 → `scripts/restore.sh <폴더>`.

## Docker 없이 운영하는 경우
- PostgreSQL: `pg_dump -Fc -d bid_analyzer > db.dump`, 복원 `pg_restore --clean --if-exists -d bid_analyzer db.dump`
- SQLite(개발용): 서버를 멈춘 뒤 `sqlite3 backend/bid_analyzer.db ".backup backup.db"`
- 업로드 원본: `BID_STORAGE_DIR`(기본 `backend/storage`) 폴더를 통째로 복사

## 검증 기록
2026-10-27, 깨끗한 폴더에서 Docker Compose 로 설치한 시스템(PostgreSQL 16)으로 확인: 백업 → 업로드 1건 추가 → 복원 후 업로드 작업 수가 백업 시점(3건)으로 돌아오고, PDF 원본 파일과 로그인·화면이 정상 동작함.
