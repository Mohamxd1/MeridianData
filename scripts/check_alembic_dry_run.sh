#!/usr/bin/env bash
set -euo pipefail

if [ ! -f "alembic.ini" ]; then
  echo "No alembic.ini found. Skipping migration dry-run."
  exit 0
fi

echo "Running Alembic SQL dry-run..."
alembic upgrade head --sql > /tmp/dataforge_alembic_dry_run.sql

if grep -Eiq "DROP TABLE|DROP COLUMN|TRUNCATE TABLE" /tmp/dataforge_alembic_dry_run.sql; then
  echo "Potential destructive migration detected:"
  grep -Ein "DROP TABLE|DROP COLUMN|TRUNCATE TABLE" /tmp/dataforge_alembic_dry_run.sql
  exit 1
fi

echo "Alembic dry-run passed."
