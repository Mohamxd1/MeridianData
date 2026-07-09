from __future__ import annotations

import asyncio
import csv
import json
import logging
from io import StringIO
from pathlib import Path
from typing import Any

from dataforge.models import NormalizedFile

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    def __init__(self, message: str, raw_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class RateLimitError(Exception):
    pass


class SchemaValidationError(Exception):
    pass


class ConfigurationError(Exception):
    pass


def extract_text(file_obj: NormalizedFile) -> str:
    path = Path(file_obj.storage_path)
    ext = file_obj.extension.lower()

    if ext == ".pdf":
        import pdfplumber
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts).strip()

    if ext == ".docx":
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs).strip()

    if ext in {".png", ".jpg", ".jpeg"}:
        from PIL import Image
        import pytesseract
        return pytesseract.image_to_string(Image.open(path)).strip()

    if ext == ".csv":
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            return "\n".join(", ".join(row) for row in reader).strip()

    if ext == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore").strip()

    raise ExtractionError(f"Unsupported file type for text extraction: {ext}")


def _schema_as_bullets(schema: dict[str, str]) -> str:
    if not schema:
        raise SchemaValidationError("schema cannot be empty")
    allowed = {"string", "number", "boolean", "date"}
    lines = []
    for field, field_type in schema.items():
        if field_type not in allowed:
            raise SchemaValidationError(f"Unsupported field type for {field}: {field_type}")
        lines.append(f"- {field}: {field_type}")
    return "\n".join(lines)


def _validate_output_shape(record: dict[str, Any], schema: dict[str, str]) -> dict[str, Any]:
    # Supports either flat JSON: {"field": "value", "_confidence": {...}}
    # or structured JSON: {"fields": {...}, "confidence": {...}}.
    fields = record.get("fields", record) if isinstance(record.get("fields", record), dict) else record
    confidence = record.get("confidence") or record.get("_confidence") or {}
    output = {}
    for field in schema:
        output[field] = fields.get(field, None)
    if isinstance(confidence, dict):
        output["_confidence"] = {field: confidence.get(field) for field in schema if confidence.get(field) is not None}
    return output


async def extract_fields(
    text: str,
    schema: dict[str, str],
    extraction_prompt: str,
    model: str = "gpt-4o",
    provider: str = "openai",
) -> dict:
    """Extract structured values from raw text using a configurable AI provider.

    Supports OpenAI fully. Anthropic is implemented as a provider hook and requires
    ANTHROPIC_API_KEY plus the anthropic package.
    """
    schema_bullets = _schema_as_bullets(schema)
    if provider == "anthropic" and (not model or model == "gpt-4o"):
        raise ConfigurationError("ai_model must be set when using the Anthropic provider.")
    system_prompt = f"""You are a document data extraction assistant.

Your task: Extract the following fields from the document text below.
Return ONLY a valid JSON object. No explanation, no markdown, no commentary.

Fields to extract:
{schema_bullets}

Extraction instructions:
{extraction_prompt}

Rules:
- If a field is not present in the document, return null for that field.
- Do not infer or guess values. Only extract what is explicitly stated.
- Dates must be in ISO 8601 format (YYYY-MM-DD).
- Numbers must be numeric types, not strings.
- Also include an optional _confidence object with one 0.0 to 1.0 score per field.
"""

    raw_response = None
    for json_attempt in range(2):
        try:
            token_usage: dict[str, int] = {}
            if provider == "anthropic":
                provider_result = await _call_anthropic_json(system_prompt, text, model)
            elif provider == "openai":
                provider_result = await _call_openai_json(system_prompt, text, model)
            else:
                raise SchemaValidationError(f"Unsupported AI provider: {provider}")

            if isinstance(provider_result, tuple):
                raw_response, token_usage = provider_result
            else:
                raw_response = provider_result

            parsed = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
            if not isinstance(parsed, dict):
                raise ValueError("Model response was not a JSON object")
            output = _validate_output_shape(parsed, schema)
            if token_usage:
                output["_token_usage"] = token_usage
            return output
        except json.JSONDecodeError as exc:
            if json_attempt == 1:
                raise ExtractionError("Model returned malformed JSON after retry", raw_response=raw_response) from exc
        except ValueError as exc:
            if json_attempt == 1:
                raise ExtractionError(str(exc), raw_response=str(raw_response)) from exc

    raise ExtractionError("Extraction failed", raw_response=str(raw_response))


def _usage_value(usage: Any, attr: str, default: int = 0) -> int:
    if usage is None:
        return default
    if isinstance(usage, dict):
        return int(usage.get(attr, default) or default)
    return int(getattr(usage, attr, default) or default)


def _normalize_openai_usage(usage: Any) -> dict[str, int]:
    return {
        "input_tokens": _usage_value(usage, "prompt_tokens"),
        "output_tokens": _usage_value(usage, "completion_tokens"),
        "total_tokens": _usage_value(usage, "total_tokens"),
    }


def _normalize_anthropic_usage(usage: Any) -> dict[str, int]:
    input_tokens = _usage_value(usage, "input_tokens")
    output_tokens = _usage_value(usage, "output_tokens")
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


async def _call_openai_json(system_prompt: str, document_text: str, model: str) -> str:
    from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError

    client = AsyncOpenAI()
    last_error = None
    for attempt in range(3):
        try:
            response = await client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": document_text},
                ],
                temperature=0,
            )
            usage = getattr(response, "usage", None)
            token_usage = _normalize_openai_usage(usage)
            if usage:
                logger.info("extraction_token_usage", extra={"usage": token_usage, "provider": "openai", "model": model})
            return response.choices[0].message.content or "{}", token_usage
        except OpenAIRateLimitError as exc:
            last_error = exc
            await asyncio.sleep(2 ** attempt)

    raise RateLimitError("OpenAI rate limit exceeded after 3 attempts") from last_error


async def _call_anthropic_json(system_prompt: str, document_text: str, model: str) -> str:
    from anthropic import AsyncAnthropic, RateLimitError as AnthropicRateLimitError

    client = AsyncAnthropic()
    last_error = None
    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=2000,
                temperature=0,
                system=system_prompt,
                messages=[{"role": "user", "content": document_text}],
            )
            usage = getattr(response, "usage", None)
            token_usage = _normalize_anthropic_usage(usage)
            if usage:
                logger.info("extraction_token_usage", extra={"usage": token_usage, "provider": "anthropic", "model": model})
            return response.content[0].text, token_usage
        except AnthropicRateLimitError as exc:
            last_error = exc
            await asyncio.sleep(2 ** attempt)

    raise RateLimitError("Anthropic rate limit exceeded after 3 attempts") from last_error
