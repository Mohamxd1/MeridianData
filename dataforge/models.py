from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

FieldType = Literal["string", "number", "boolean", "date"]
RecordStatus = Literal["pending_review", "approved", "rejected"]
DestinationType = Literal["google_sheets", "webhook", "email", "csv", "airtable", "crm"]


class CustomRule(BaseModel):
    field: str
    rule: Literal["regex", "range", "enum"]
    value: Any


class ValidationRules(BaseModel):
    required_fields: list[str] = Field(default_factory=list)
    urgent_keywords: list[str] = Field(default_factory=list)
    custom_rules: list[CustomRule] = Field(default_factory=list)


class OutputDestination(BaseModel):
    type: DestinationType
    config: dict[str, Any] = Field(default_factory=dict)


class ReviewWorkflow(BaseModel):
    auto_approve_if: str
    flag_for_review_if: str


class ClientConfig(BaseModel):
    client_id: str
    company_name: str
    schema: dict[str, FieldType]
    validation_rules: ValidationRules
    extraction_prompt: str
    output_destination: OutputDestination
    review_workflow: ReviewWorkflow

    @field_validator("client_id")
    @classmethod
    def client_id_must_be_safe(cls, value: str) -> str:
        if not value.replace("_", "").isalnum() or value.lower() != value:
            raise ValueError("client_id must be lowercase snake_case")
        return value


class NormalizedFile(BaseModel):
    client_id: str
    filename: str
    content_type: str | None = None
    extension: str
    size_bytes: int
    storage_path: str
    sha256: str
    uploaded_at: datetime


class ValidationResult(BaseModel):
    status: RecordStatus
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    urgent: bool = False
    missing_required_fields: list[str] = Field(default_factory=list)


class SavedRecord(BaseModel):
    id: str
    client_id: str
    created_at: datetime
    status: RecordStatus
    raw_text: str
    extracted_fields: dict[str, Any]
    validation_result: ValidationResult
    exported: bool = False


class ProcessFileResponse(BaseModel):
    job_id: str
    status: Literal["queued"] = "queued"
    message: str
