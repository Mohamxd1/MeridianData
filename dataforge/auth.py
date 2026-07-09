from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _env_key_name(client_id: str) -> str:
    return f"API_KEY_{client_id.upper()}"


async def verify_api_key(request: Request, client_id: str, api_key: str | None = Depends(api_key_header)) -> None:
    """Per-client API key guard.

    Production has no keyless bypass. For local demos only, set:
      DATAFORGE_DEV_MODE=true
    """
    expected = os.getenv(_env_key_name(client_id))
    dev_mode = os.getenv("DATAFORGE_DEV_MODE", "false").lower() == "true"

    if dev_mode and client_id == "demo_client" and not expected:
        request.state.actor = "dev_mode_demo_client"
        return

    if not expected:
        raise HTTPException(status_code=403, detail="API key not configured for this client")
    if api_key != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    request.state.actor = f"api_key:{client_id}"
