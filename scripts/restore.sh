#!/usr/bin/env bash
# backup.sh 로 만든 백업을 되살린다. 현재 DB 와 업로드 파일을 백업 시점으로 바꾸므로,
# 시작 전에 현재 상태를 자동으로 한 번 더 백업한다(되돌릴 수 있게).
# 사용법: scripts/restore.sh backups/20261027-120000 [--yes]
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${1:?복원할 백업 폴더를 지정하세요. 예: scripts/restore.sh backups/20261027-120000}"
DC=(docker compose)
for f in db.dump storage.tar.gz SHA256SUMS manifest.txt; do
  [[ -f "$SRC/$f" ]] || { echo "백업 폴더에 $f 가 없습니다: $SRC" >&2; exit 1; }
done

echo "[1/6] 백업 파일 무결성 확인"
(cd "$SRC" && sha256sum -c --quiet SHA256SUMS)
cat "$SRC/manifest.txt"

if [[ "${2:-}" != "--yes" ]]; then
  echo
  echo "현재 데이터베이스와 업로드 파일이 위 백업 시점으로 바뀝니다."
  read -r -p "계속하려면 RESTORE 를 입력하세요: " ans
  [[ "$ans" == "RESTORE" ]] || { echo "취소했습니다."; exit 1; }
fi

"${DC[@]}" up -d db
"${DC[@]}" exec -T db sh -c 'until pg_isready -U bid -d bid_analyzer -q; do sleep 1; done'

echo "[2/6] 현재 상태를 안전 백업"
SAFETY="$(scripts/backup.sh ./backups/before-restore | sed -n "s/^백업 완료: //p")"
echo "안전 백업: $SAFETY"

trap 'echo "복원 중 오류가 났습니다. 백엔드·웹이 멈춰 있을 수 있습니다. 안전 백업으로 되돌리려면: scripts/restore.sh $SAFETY" >&2' ERR

echo "[3/6] 백엔드·웹 중지(복원 중 쓰기 방지)"
"${DC[@]}" stop backend frontend >/dev/null

echo "[4/6] 데이터베이스 복원"
"${DC[@]}" exec -T db psql -U bid -d postgres -v ON_ERROR_STOP=1 -q \
  -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='bid_analyzer' and pid <> pg_backend_pid();" \
  -c "drop database if exists bid_analyzer;" -c "create database bid_analyzer owner bid;" > /dev/null
"${DC[@]}" exec -T db pg_restore -U bid -d bid_analyzer --no-owner --exit-on-error < "$SRC/db.dump"

echo "[5/6] 업로드 원본 파일 복원"
"${DC[@]}" run --rm --no-deps -T --user root --entrypoint "" backend \
  sh -c 'find /data/storage -mindepth 1 -delete && tar xzf - -C /data && chown -R bid /data/storage' < "$SRC/storage.tar.gz"

echo "[6/6] 백엔드·웹 다시 시작(필요하면 마이그레이션 자동 적용)"
"${DC[@]}" up -d backend frontend
echo "복원 완료. 문제가 있으면 안전 백업으로 되돌리세요: scripts/restore.sh $SAFETY"
