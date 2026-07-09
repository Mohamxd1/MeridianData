#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${BACKUP_DIR}/dataforge_${TIMESTAMP}.dump"

mkdir -p "$BACKUP_DIR"

echo "Creating Postgres custom-format backup: $OUT_FILE"
pg_dump "$DATABASE_URL" --format=custom --no-owner --no-acl --file="$OUT_FILE"

echo "Backup complete: $OUT_FILE"
