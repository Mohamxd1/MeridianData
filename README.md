# DataForge

Multi-tenant AI-powered document processing platform. Extracts structured data from uploaded files (PDFs, scans, emails, Word docs) and delivers clean records to Google Sheets, Airtable, webhooks, CSV, or email — with a human-in-the-loop review workflow.

## Current build status

| Module | Status | Score |
|--------|--------|-------|
| Backend v0.4.2 — processing pipeline | ✅ Complete | 10/10 |
| Module 1A — clients + users database | ✅ Complete | 10/10 |
| Ops gap pack — CI/CD, erasure, monitoring | ✅ Complete | 9.4/10 |
| Module 1B — api_keys, file storage, token tables | ⬜ Next | — |
| Module 3 — full JWT + API key auth | ⬜ Next | — |
| Module 2 — S3/R2 file storage | ⬜ Pending | — |
| Module 5 — Docker + deployment | ⬜ Pending | — |
| Module 4A-D — React frontend | ⬜ Pending | — |
| Module 6 — Sentry + admin dashboard | ⬜ Pending | — |
| Module 7 — Stripe billing | ⬜ Pending | — |
| Module 8 — legal documents | ⬜ Pending | — |

## Tech stack

- **Backend**: FastAPI, Python 3.12, SQLAlchemy 2.0, PostgreSQL
- **Queue**: RQ + Redis
- **AI**: OpenAI GPT-4o + Anthropic Claude (dual-provider, switchable per client)
- **Storage**: Cloudflare R2 / AWS S3 (Module 2)
- **Frontend**: React 18 + TypeScript + Vite + TanStack (Module 4)
- **Deployment**: Docker + Railway (Module 5)
- **Monitoring**: Sentry + structured JSON logging (Module 6)
- **Billing**: Stripe (Module 7)

## Project structure

```
dataforge/                  ← Python package (backend)
  main.py                   ← FastAPI app, all routes registered
  db.py                     ← SQLAlchemy async engine + session
  models.py                 ← Core tables: records, jobs, audit_log, dead_letter_jobs
  models_extended.py        ← Extended tables: clients, users (Module 1A)
  config.py                 ← Per-client JSON config loader + validator
  auth.py                   ← API key authentication
  logging_config.py         ← Structured JSON logging with request_id + client_id
  rate_limit.py             ← Per-client rate limiting (Redis + memory fallback)
  queue.py                  ← RQ job queue abstraction
  worker.py                 ← RQ worker entrypoint
  processor.py              ← Full pipeline orchestrator (intake→extract→validate→save)
  seed.py                   ← Demo client + user seed for local dev
  pipeline/
    intake.py               ← File validation, MIME sniffing, disk write
    extract.py              ← AI extraction (OpenAI + Anthropic), confidence scoring
    validate.py             ← Field validation, urgency detection, auto-approve rules
    save.py                 ← Persist records + write audit log
    export.py               ← CSV, Google Sheets, Airtable, webhook, email exports
  repositories/
    clients.py              ← DB queries for clients and users
  security/
    passwords.py            ← bcrypt hashing + password policy (Module 1A)
  jobs/
    failed_job_alert.py     ← Hourly cron: alert on dead letter jobs
    send_limit_warning_emails.py  ← Daily cron: warn clients at 80% limit
    monthly_limit_reset.py  ← Monthly cron: reset usage counters
  routers/
    erasure_router.py       ← DELETE /admin/clients/{id}/data (GDPR right-to-erasure)
  services/
    erasure.py              ← Erasure service: ordered deletion, dry-run, storage callback
  configs/
    demo_client.json        ← Demo client schema (property management)

alembic/                    ← Database migrations
  versions/
    20260522_0001_clients_users.py  ← clients + users tables (Module 1A)

tests/                      ← All test files
  conftest.py               ← Async db_session fixture with cleanup
  test_extract.py           ← AI extraction tests
  test_production_fixes.py  ← End-to-end pipeline + rate limit + token usage tests
  test_rate_limit_and_recovery.py  ← Rate limiting + startup recovery tests
  test_module1a_clients_users.py   ← Database constraint + isolation tests
  test_erasure.py           ← Erasure service dry-run + cross-client isolation tests

scripts/
  backup_postgres.sh        ← pg_dump to dated backup file
  restore_postgres.sh       ← pg_restore from backup file
  check_alembic_dry_run.sh  ← CI: fail if migration contains DROP/TRUNCATE

.github/
  workflows/ci.yml          ← GitHub Actions: test + lint + frontend build
  dependabot.yml            ← Auto-PRs for pip + npm + Actions updates

frontend/                   ← React app (Module 4 — not yet built)
  src/
    analytics/              ← PostHog integration (done)
      posthog.ts
      AnalyticsProvider.tsx
      useTrackEvent.ts

deployment/
  railway_cron_additions.toml   ← Railway cron job config
  render_cron_additions.yaml    ← Render cron job config

docs/
  setup/                    ← Runbooks for external service setup
    database_backups.md
    uptime_monitoring.md
    cloudflare_waf_cdn.md
    log_aggregation.md
    product_analytics.md
    secrets_manager.md
    status_page.md
    support_inbox.md
    contracts_esign.md
  security/
    dependency_scanning.md

CLAUDE.md                   ← Master build prompt for Claude Code (all module specs)
.env.example                ← All environment variables with descriptions
requirements.txt            ← Python dependencies
pyproject.toml              ← Pytest + ruff config
alembic.ini                 ← Alembic configuration
openapi.yaml                ← Full OpenAPI spec
```

## Local development quickstart

```bash
# 1. Clone and install
git clone https://github.com/yourusername/dataforge.git
cd dataforge
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env — set DATABASE_URL, REDIS_URL, OPENAI_API_KEY at minimum

# 3. Start Postgres + Redis
docker run -d --name dataforge-postgres \
  -e POSTGRES_USER=dataforge \
  -e POSTGRES_PASSWORD=dataforgepass \
  -e POSTGRES_DB=dataforge \
  -p 5432:5432 postgres:16

docker run -d --name dataforge-redis -p 6379:6379 redis:7

# 4. Run migrations
alembic upgrade head

# 5. Seed demo client (optional)
DATAFORGE_SEED_ON_START=true \
DATAFORGE_DEMO_OWNER_PASSWORD=YourPassword123! \
python -m dataforge.seed

# 6. Start the API
uvicorn dataforge.main:app --reload

# 7. Run tests
pytest tests/ -q
```

## Using Claude Code to complete remaining modules

This repo contains CLAUDE.md — the master build prompt. Open the project in Claude Code and say:

```
Build Module 1B from CLAUDE.md.
```

It will read the full spec and build the next module without you re-explaining the project.

## Environment variables

See `.env.example` for all variables with descriptions. Minimum required to run locally:

```
DATABASE_URL
REDIS_URL
OPENAI_API_KEY  (or ANTHROPIC_API_KEY)
```

## Key architecture decisions

- **Multi-tenant**: every DB table has `client_id` — no cross-client data leaks
- **Config-driven**: new clients need a JSON config file, no code changes
- **Audit log**: every state change written to `audit_log` with actor + timestamp
- **Dead-letter**: jobs failing 3× moved to `dead_letter_jobs` — never silently lost
- **Rate limiting**: per-client, per-bucket, Redis-backed with memory fallback
- **Dual AI**: OpenAI and Anthropic both supported, switchable per client config
- **Confidence scoring**: fields below 0.70 auto-flagged for human review
