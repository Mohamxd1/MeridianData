#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set}"
: "${BACKUP_FILE:?BACKUP_FILE must point to a .dump file}"

echo "Restoring $BACKUP_FILE into DATABASE_URL"
pg_restore "$BACKUP_FILE" --dbname="$DATABASE_URL" --clean --if-exists --no-owner --no-acl

echo "Restore complete."
