import pytest

from dataforge.pipeline import extract as extract_module
from dataforge.pipeline.extract import ExtractionError, SchemaValidationError


@pytest.mark.asyncio
async def test_successful_extraction(monkeypatch):
    async def fake_call(system_prompt, document_text, model):
        return '{"tenant_name":"Amina Ali","unit_number":"204","permission_to_enter":true}'

    monkeypatch.setattr(extract_module, "_call_openai_json", fake_call)
    result = await extract_module.extract_fields(
        "Tenant Amina Ali in unit 204 gives permission to enter.",
        {"tenant_name": "string", "unit_number": "string", "permission_to_enter": "boolean"},
        "Extract tenant maintenance request fields."
    )
    assert result["tenant_name"] == "Amina Ali"
    assert result["unit_number"] == "204"
    assert result["permission_to_enter"] is True


@pytest.mark.asyncio
async def test_field_not_found_returns_null(monkeypatch):
    async def fake_call(system_prompt, document_text, model):
        return '{"tenant_name":"Amina Ali","contact_phone":null}'

    monkeypatch.setattr(extract_module, "_call_openai_json", fake_call)
    result = await extract_module.extract_fields(
        "Tenant Amina Ali submitted a request.",
        {"tenant_name": "string", "contact_phone": "string"},
        "Extract fields."
    )
    assert result["contact_phone"] is None


@pytest.mark.asyncio
async def test_malformed_json_retry(monkeypatch):
    calls = {"count": 0}

    async def fake_call(system_prompt, document_text, model):
        calls["count"] += 1
        if calls["count"] == 1:
            return "not valid json"
        return '{"tenant_name":"Amina Ali"}'

    monkeypatch.setattr(extract_module, "_call_openai_json", fake_call)
    result = await extract_module.extract_fields(
        "Tenant Amina Ali submitted a request.",
        {"tenant_name": "string"},
        "Extract fields."
    )
    assert calls["count"] == 2
    assert result["tenant_name"] == "Amina Ali"


@pytest.mark.asyncio
async def test_malformed_json_fails_after_two_attempts(monkeypatch):
    async def fake_call(system_prompt, document_text, model):
        return "not valid json"

    monkeypatch.setattr(extract_module, "_call_openai_json", fake_call)
    with pytest.raises(ExtractionError):
        await extract_module.extract_fields(
            "Tenant Amina Ali submitted a request.",
            {"tenant_name": "string"},
            "Extract fields."
        )


@pytest.mark.asyncio
async def test_schema_mismatch():
    with pytest.raises(SchemaValidationError):
        await extract_module.extract_fields(
            "text",
            {"tenant_name": "unsupported_type"},
            "Extract fields."
        )
