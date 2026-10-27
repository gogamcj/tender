#!/usr/bin/env bash
# Docker Compose 로 실행 중인 시스템을 백업한다: PostgreSQL 전체(pg_dump) + 업로드 원본 파일(storage).
# 사용법: scripts/backup.sh [백업 폴더, 기본 ./backups]
# .env(비밀번호·API 키)는 백업에 넣지 않는다. 따로 안전한 곳에 보관하세요.
set -euo pipefail
cd "$(dirname "$0")/.."

ROOT="${1:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$ROOT/$STAMP"
DC=(docker compose)

if ! "${DC[@]}" ps --status running --services | grep -qx db; then
  echo "db 컨테이너가 실행 중이 아닙니다. 'docker compose up -d db' 후 다시 실행하세요." >&2
  exit 1
fi
mkdir -p "$OUT"
umask 077

echo "[1/3] 데이터베이스 덤프"
"${DC[@]}" exec -T db pg_dump -U bid -d bid_analyzer -Fc --no-owner > "$OUT/db.dump"

echo "[2/3] 업로드 원본 파일"
if "${DC[@]}" ps --status running --services | grep -qx backend; then
  "${DC[@]}" exec -T backend tar czf - -C /data storage > "$OUT/storage.tar.gz"
else
  "${DC[@]}" run --rm --no-deps -T --entrypoint "" backend tar czf - -C /data storage > "$OUT/storage.tar.gz"
fi

echo "[3/3] 확인 정보 기록"
REV="$("${DC[@]}" exec -T db psql -U bid -d bid_analyzer -tAc 'select version_num from alembic_version' 2>/dev/null || echo unknown)"
NOTICES="$("${DC[@]}" exec -T db psql -U bid -d bid_analyzer -tAc 'select count(*) from procurement_notices' 2>/dev/null || echo unknown)"
{
  echo "created_at=$STAMP"
  echo "alembic_revision=$REV"
  echo "procurement_notices=$NOTICES"
} > "$OUT/manifest.txt"
(cd "$OUT" && sha256sum db.dump storage.tar.gz > SHA256SUMS)

# 덤프가 실제로 읽히는지 확인(목록만 읽고 DB 는 바꾸지 않음)
"${DC[@]}" exec -T db pg_restore --list < "$OUT/db.dump" > /dev/null

echo "백업 완료: $OUT"
cat "$OUT/manifest.txt"
