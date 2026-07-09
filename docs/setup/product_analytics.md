# Product Analytics

## Goal

Understand where clients get stuck.

## Recommended tool

PostHog.

## Events to track

```txt
user_logged_in
file_upload_started
file_upload_completed
job_completed
record_opened
record_approved
record_rejected
record_edited
export_started
export_completed
export_failed
```

## Funnel

Main product funnel:

```txt
upload -> job completed -> record opened -> approved -> exported
```

## Properties to include

- client_id
- role
- record_status
- confidence_bucket
- export_destination

Never send extracted field values, raw document text, or uploaded file names to analytics.
