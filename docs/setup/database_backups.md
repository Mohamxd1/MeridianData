# Database Backups

## Goal

Prevent permanent client data loss.

## Minimum requirement before first paying client

- Automated daily backup
- Restore test into staging
- Written recovery steps
- Database credentials stored in a secure environment variable system

## Hosted Postgres checklist

1. Open your Postgres hosting provider.
2. Enable automated backups.
3. Enable point-in-time recovery if supported.
4. Set backup retention to at least 7 days for early stage, 30 days for paid clients.
5. Create a staging database.
6. Restore a backup into staging once.
7. Record the restore timestamp and result.

## Self-managed backup command

```bash
DATABASE_URL="postgresql://..." BACKUP_DIR="./backups" bash scripts/backup_postgres.sh
```

## Restore command

```bash
DATABASE_URL="postgresql://..." BACKUP_FILE="./backups/dataforge_xxx.dump" bash scripts/restore_postgres.sh
```

## Recovery target

For paid clients, aim for:

- RPO: 24 hours or better
- RTO: 4 hours or better
