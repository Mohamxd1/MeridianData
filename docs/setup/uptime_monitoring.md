# Uptime Monitoring

## Goal

Know the API is down before a client tells you.

## Monitor

Create an HTTP monitor:

```txt
GET https://api.usedataforge.com/health
```

Expected:

```txt
HTTP 200
```

Optional keyword check:

```txt
healthy
```

## Recommended alert rules

- Alert after 2 failed checks
- Notify by email and SMS
- Re-check every 1–3 minutes

## What to monitor

- API health: `/health`
- Frontend health: `https://app.usedataforge.com`
- Worker heartbeat later: a scheduled heartbeat job
