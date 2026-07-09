# Log Aggregation

## Goal

Search logs by client_id, request_id, job_id, and error type.

## Recommended early-stage tools

- Better Stack Logs
- Axiom
- Datadog
- Grafana Loki

## Useful searches

### Extraction failures for one client

```txt
client_id="northline_property_management" action="extraction_failed"
```

### Slow jobs

```txt
duration_ms > 30000
```

### Rate limits

```txt
status_code=429
```

## Required log fields

- request_id
- client_id
- job_id
- record_id
- action
- status_code
- duration_ms
- error_type
