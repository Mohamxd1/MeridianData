from __future__ import annotations

import json
from pathlib import Path
from fastapi import HTTPException
from .models import ClientConfig

CONFIG_DIR = Path(__file__).parent / "configs"


def load_client_config(client_id: str) -> ClientConfig:
    # Prevent path traversal and cross-client config access.
    safe_name = client_id.strip().lower()
    if safe_name != client_id or "/" in client_id or ".." in client_id:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    path = CONFIG_DIR / f"{client_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Config not found for client_id={client_id}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        config = ClientConfig.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Invalid client config: {exc}") from exc

    if config.client_id != client_id:
        raise HTTPException(status_code=500, detail="Config client_id does not match route client_id")
    return config


def redact_config(config: ClientConfig) -> dict:
    data = config.model_dump()
    destination_config = data.get("output_destination", {}).get("config", {})
    for key in list(destination_config.keys()):
        if any(secret_word in key.lower() for secret_word in ["key", "token", "secret", "password"]):
            destination_config[key] = "REDACTED"
    return data
