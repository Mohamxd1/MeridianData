from __future__ import annotations

import csv
import html
import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx

from dataforge.models import OutputDestination

EXPORT_DIR = Path("storage/exports")


def _ensure_export_dir() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def export_record(record: dict[str, Any], destination: OutputDestination | dict) -> dict[str, Any]:
    if isinstance(destination, dict):
        destination = OutputDestination.model_validate(destination)

    if record.get("status") != "approved":
        return {"exported": False, "reason": "record is not approved"}

    _ensure_export_dir()

    if destination.type == "csv":
        return _export_csv(record, destination)

    if destination.type == "webhook":
        return _export_webhook(record, destination)

    if destination.type == "google_sheets":
        return _export_google_sheets(record, destination)

    if destination.type == "email":
        return _export_email(record, destination)

    if destination.type == "airtable":
        return _export_airtable(record, destination)

    if destination.type == "crm":
        return _export_crm(record, destination)

    return {"exported": False, "reason": "unsupported destination"}


def _export_csv(record: dict[str, Any], destination: OutputDestination) -> dict[str, Any]:
    _ensure_export_dir()
    path = Path(destination.config.get("path", EXPORT_DIR / "approved_records.csv"))
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(record.keys())
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(record)
    return {"exported": True, "type": "csv", "path": str(path)}


def _export_webhook(record: dict[str, Any], destination: OutputDestination) -> dict[str, Any]:
    url = destination.config.get("url")
    if not url:
        raise ValueError("webhook destination requires config.url")
    headers = destination.config.get("headers", {})
    secret_env = destination.config.get("secret_env")
    if secret_env and os.getenv(secret_env):
        headers["Authorization"] = f"Bearer {os.getenv(secret_env)}"
    response = httpx.post(url, json=record, headers=headers, timeout=15)
    response.raise_for_status()
    return {"exported": True, "type": "webhook", "status_code": response.status_code}


def _export_google_sheets(record: dict[str, Any], destination: OutputDestination) -> dict[str, Any]:
    """Real Sheets export when gspread credentials are configured; local stub otherwise."""
    _ensure_export_dir()
    spreadsheet_id = destination.config.get("spreadsheet_id")
    worksheet_name = destination.config.get("worksheet", "Sheet1")
    credentials_file = destination.config.get("credentials_file") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if spreadsheet_id and credentials_file:
        import gspread

        gc = gspread.service_account(filename=credentials_file)
        worksheet = gc.open_by_key(spreadsheet_id).worksheet(worksheet_name)
        worksheet.append_row([record.get(k) for k in record.keys()])
        return {"exported": True, "type": "google_sheets", "spreadsheet_id": spreadsheet_id}

    path = EXPORT_DIR / "google_sheets_stub.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return {"exported": True, "type": "google_sheets_stub", "path": str(path), "note": "Set spreadsheet_id and credentials_file for live export"}


def _record_to_html_table(record: dict[str, Any]) -> str:
    rows = []
    for key, value in record.items():
        rendered = json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value)
        rows.append(
            "<tr>"
            f"<th style='text-align:left;padding:8px;border:1px solid #ddd;background:#f7f7f7'>{html.escape(str(key))}</th>"
            f"<td style='padding:8px;border:1px solid #ddd'>{html.escape(rendered)}</td>"
            "</tr>"
        )
    return (
        "<html><body>"
        "<h2>DataForge approved record</h2>"
        "<table style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px'>"
        + "".join(rows)
        + "</table></body></html>"
    )


def _export_email(record: dict[str, Any], destination: OutputDestination) -> dict[str, Any]:
    _ensure_export_dir()
    to_addr = destination.config.get("to")
    smtp_host = destination.config.get("smtp_host") or os.getenv("SMTP_HOST")
    smtp_user = destination.config.get("smtp_user") or os.getenv("SMTP_USER")
    smtp_password = destination.config.get("smtp_password") or os.getenv("SMTP_PASSWORD")
    from_addr = destination.config.get("from") or os.getenv("SMTP_FROM") or smtp_user

    if to_addr and smtp_host and from_addr:
        msg = EmailMessage()
        msg["Subject"] = destination.config.get("subject", "DataForge approved record")
        msg["From"] = from_addr
        msg["To"] = to_addr
        plain_text = json.dumps(record, indent=2, default=str)
        msg.set_content(plain_text)
        msg.add_alternative(_record_to_html_table(record), subtype="html")
        port = int(destination.config.get("smtp_port", os.getenv("SMTP_PORT", "587")))
        with smtplib.SMTP(smtp_host, port, timeout=15) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return {"exported": True, "type": "email", "to": to_addr}

    path = EXPORT_DIR / "email_outbox_stub.jsonl"
    payload = {"to": to_addr, "record": record, "html": _record_to_html_table(record)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    return {"exported": True, "type": "email_stub", "path": str(path), "note": "Set SMTP_HOST/SMTP_FROM for live email"}



def _apply_field_mapping(record: dict[str, Any], mapping: dict[str, str] | None) -> dict[str, Any]:
    if not mapping:
        return dict(record)
    return {destination_field: record.get(source_field) for source_field, destination_field in mapping.items()}


def _export_airtable(record: dict[str, Any], destination: OutputDestination) -> dict[str, Any]:
    """Export to Airtable when configured; write a local JSONL stub otherwise.

    Expected config for live export:
      base_id: Airtable base id
      table_name: Airtable table name
      api_key_env: environment variable containing the Airtable API key
      field_mapping: optional {record_field: airtable_field}
    """
    _ensure_export_dir()
    base_id = destination.config.get("base_id")
    table_name = destination.config.get("table_name")
    api_key = destination.config.get("api_key") or os.getenv(destination.config.get("api_key_env", "AIRTABLE_API_KEY"))
    fields = _apply_field_mapping(record, destination.config.get("field_mapping"))

    if base_id and table_name and api_key:
        url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
        response = httpx.post(
            url,
            json={"records": [{"fields": fields}]},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "exported": True,
            "type": "airtable",
            "base_id": base_id,
            "table_name": table_name,
            "record_count": len(payload.get("records", [])),
        }

    path = EXPORT_DIR / "airtable_stub.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"fields": fields}, default=str) + "\n")
    return {
        "exported": True,
        "type": "airtable_stub",
        "path": str(path),
        "note": "Set base_id, table_name, and AIRTABLE_API_KEY or api_key_env for live export",
    }


def _export_crm(record: dict[str, Any], destination: OutputDestination) -> dict[str, Any]:
    """Generic CRM export hook.

    This supports lightweight CRM integrations without adding a vendor SDK. Configure:
      url: CRM endpoint URL
      api_key_env: optional env var for bearer token
      headers: optional extra headers
      object_type: optional CRM object label such as lead, contact, ticket
      field_mapping: optional {record_field: crm_field}
    Without a URL, it writes a local JSONL stub for safe demos/tests.
    """
    _ensure_export_dir()
    url = destination.config.get("url")
    object_type = destination.config.get("object_type", "record")
    payload = {
        "object_type": object_type,
        "fields": _apply_field_mapping(record, destination.config.get("field_mapping")),
    }

    if url:
        headers = dict(destination.config.get("headers", {}))
        api_key_env = destination.config.get("api_key_env")
        if api_key_env and os.getenv(api_key_env):
            headers["Authorization"] = f"Bearer {os.getenv(api_key_env)}"
        response = httpx.post(url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        return {"exported": True, "type": "crm", "object_type": object_type, "status_code": response.status_code}

    path = EXPORT_DIR / "crm_stub.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")
    return {"exported": True, "type": "crm_stub", "path": str(path), "object_type": object_type}
