# Cloudflare WAF and CDN

## Goal

Put a protective edge layer in front of DataForge.

## DNS structure

```txt
app.usedataforge.com  -> frontend host
api.usedataforge.com  -> backend host
```

Enable proxy mode for both records.

## Recommended settings

- SSL/TLS mode: Full Strict
- Always Use HTTPS: On
- Automatic HTTPS Rewrites: On
- Brotli: On
- HTTP/3: On
- Cloudflare Managed WAF Rules: On
- Bot Fight Mode: On if it does not break API clients

## Basic WAF custom rules

### Block obvious non-browser admin probing

Condition:

```txt
(http.request.uri.path contains "/wp-admin") or
(http.request.uri.path contains "/phpmyadmin")
```

Action:

```txt
Block
```

### Challenge suspicious traffic to API

Condition:

```txt
(http.host eq "api.usedataforge.com" and cf.threat_score gt 25)
```

Action:

```txt
Managed Challenge
```

## Cache rule

Do not cache API responses.

Condition:

```txt
http.host eq "api.usedataforge.com"
```

Action:

```txt
Bypass cache
```

Cache static frontend assets aggressively.
