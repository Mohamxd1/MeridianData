from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class RateLimitInfo:
    bucket: str
    limit: int
    remaining: int
    reset_epoch: int


_memory_lock = threading.Lock()
_memory_counters: dict[str, tuple[int, int]] = {}


def _enabled() -> bool:
    return os.getenv("DATAFORGE_RATE_LIMIT_ENABLED", "true").lower() not in {"0", "false", "no", "off"}


def _period_seconds() -> int:
    return int(os.getenv("DATAFORGE_RATE_LIMIT_WINDOW_SECONDS", "3600"))


def _env_limit_name(client_id: str, bucket: str) -> str:
    safe_client = client_id.upper().replace("-", "_")
    safe_bucket = bucket.upper().replace("-", "_")
    return f"DATAFORGE_RATE_LIMIT_{safe_client}_{safe_bucket}"


def _default_limit(bucket: str) -> int:
    if bucket == "files":
        return int(os.getenv("DATAFORGE_RATE_LIMIT_FILES_PER_WINDOW", "100"))
    return int(os.getenv("DATAFORGE_RATE_LIMIT_API_PER_WINDOW", "1000"))


def _get_limit(client_id: str, bucket: str) -> int:
    return int(os.getenv(_env_limit_name(client_id, bucket), _default_limit(bucket)))


def _window_start(now: int, period: int) -> int:
    return now - (now % period)


def _memory_increment(key: str, cost: int, period: int, now: int) -> tuple[int, int]:
    window = _window_start(now, period)
    reset_epoch = window + period
    with _memory_lock:
        current_count, current_reset = _memory_counters.get(key, (0, reset_epoch))
        if current_reset <= now:
            current_count = 0
            current_reset = reset_epoch
        current_count += cost
        _memory_counters[key] = (current_count, current_reset)
        return current_count, current_reset


def _redis_increment(key: str, cost: int, period: int, now: int) -> tuple[int, int]:
    from redis import Redis

    redis_url = os.getenv("DATAFORGE_RATE_LIMIT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = Redis.from_url(redis_url, decode_responses=True)
    window = _window_start(now, period)
    reset_epoch = window + period
    redis_key = f"{key}:{window}"
    pipe = client.pipeline()
    pipe.incrby(redis_key, cost)
    pipe.expire(redis_key, period + 5)
    count, _ = pipe.execute()
    return int(count), reset_epoch


def check_rate_limit(client_id: str, bucket: str = "api", cost: int = 1) -> RateLimitInfo | None:
    """Enforce a fixed-window per-client rate limit.

    Defaults:
    - API requests: 1000/client/hour
    - Files uploaded: 100/client/hour

    Override globally with DATAFORGE_RATE_LIMIT_API_PER_WINDOW or
    DATAFORGE_RATE_LIMIT_FILES_PER_WINDOW. Override per client and bucket with
    DATAFORGE_RATE_LIMIT_<CLIENT_ID>_<BUCKET>, for example:
    DATAFORGE_RATE_LIMIT_DEMO_CLIENT_FILES=25
    """
    if not _enabled():
        return None

    if cost <= 0:
        cost = 1
    now = int(time.time())
    period = _period_seconds()
    limit = _get_limit(client_id, bucket)
    storage = os.getenv("DATAFORGE_RATE_LIMIT_STORAGE", "auto").lower()
    key = f"dataforge:rate:{client_id}:{bucket}"

    if storage == "redis" or (storage == "auto" and (os.getenv("DATAFORGE_RATE_LIMIT_REDIS_URL") or os.getenv("REDIS_URL"))):
        count, reset_epoch = _redis_increment(key, cost, period, now)
    else:
        count, reset_epoch = _memory_increment(key, cost, period, now)

    remaining = max(limit - count, 0)
    info = RateLimitInfo(bucket=bucket, limit=limit, remaining=remaining, reset_epoch=reset_epoch)
    if count > limit:
        retry_after = max(reset_epoch - now, 1)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for client '{client_id}' bucket '{bucket}'",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_epoch),
            },
        )
    return info


async def enforce_api_rate_limit(request: Request, client_id: str) -> None:
    info = check_rate_limit(client_id, bucket="api", cost=1)
    if info is not None:
        request.state.rate_limit = info


def add_rate_limit_headers(response: Any, info: RateLimitInfo | None) -> None:
    if info is None:
        return
    response.headers["X-RateLimit-Limit"] = str(info.limit)
    response.headers["X-RateLimit-Remaining"] = str(info.remaining)
    response.headers["X-RateLimit-Reset"] = str(info.reset_epoch)
