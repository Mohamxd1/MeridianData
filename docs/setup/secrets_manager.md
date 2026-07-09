# Secrets Manager

## Early-stage acceptable setup

For the first few clients, encrypted environment variables in Railway/Render/Fly are acceptable.

## Upgrade path

Move to one of:

- Doppler
- AWS Secrets Manager
- 1Password Secrets Automation
- Google Secret Manager

## Secrets to protect

- DATABASE_URL
- REDIS_URL
- JWT_SECRET
- OPENAI_API_KEY
- ANTHROPIC_API_KEY
- SMTP_PASSWORD
- STRIPE_SECRET_KEY
- STRIPE_WEBHOOK_SECRET
- AWS_SECRET_ACCESS_KEY
- R2_SECRET_ACCESS_KEY
- Google service account JSON
