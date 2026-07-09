# Dependency Scanning

This repo includes:

```txt
.github/dependabot.yml
.github/workflows/ci.yml
```

## What it does

- Opens dependency update PRs weekly
- Covers Python packages
- Covers frontend npm packages
- Covers GitHub Actions versions
- Runs `pip-audit` in CI as a warning step

## Before production

Turn on GitHub repository settings:

- Dependabot alerts
- Dependabot security updates
- Secret scanning
- Push protection
