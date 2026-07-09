from __future__ import annotations

import logging
from typing import Any

from dataforge.config import load_client_config
from dataforge.models import NormalizedFile
from dataforge.pipeline.extract import extract_fields, extract_text
from dataforge.pipeline.save import add_audit_log, move_job_to_dead_letter, save_record, update_job
from dataforge.pipeline.validate import validate_record

logger = logging.getLogger(__name__)
MAX_JOB_ATTEMPTS = 3
LOW_CONFIDENCE_THRESHOLD = 0.70


def _confidence_metrics(fields: dict[str, Any]) -> dict[str, Any]:
    confidence = fields.get("_confidence") if isinstance(fields.get("_confidence"), dict) else {}
    low_fields = [k for k, v in confidence.items() if isinstance(v, (int, float)) and v < LOW_CONFIDENCE_THRESHOLD]
    if low_fields:
        fields["status"] = "pending_review"
    return {"confidence": confidence, "low_confidence_fields": low_fields}


async def process_job(client_id: str, job_id: str, file_objs: list[dict[str, Any]]) -> None:
    update_job(client_id, job_id, "processing", increment_attempts=True)
    try:
        config = load_client_config(client_id)
        ai_provider = config.output_destination.config.get("ai_provider", "openai")
        ai_model = config.output_destination.config.get("ai_model", "gpt-4o")
        config_version = config.output_destination.config.get("config_version", "v1")
        results = []

        for file_data in file_objs:
            file_obj = NormalizedFile.model_validate(file_data)
            raw_text = extract_text(file_obj)
            fields = await extract_fields(raw_text, config.schema, config.extraction_prompt, model=ai_model, provider=ai_provider)
            token_usage = fields.pop("_token_usage", {}) if isinstance(fields, dict) else {}
            extraction_metrics = _confidence_metrics(fields)
            extraction_metrics.update({
                "input_tokens": int(token_usage.get("input_tokens", 0) or 0),
                "output_tokens": int(token_usage.get("output_tokens", 0) or 0),
                "total_tokens": int(token_usage.get("total_tokens", 0) or 0),
                "ai_provider": ai_provider,
                "ai_model": ai_model,
            })
            validated, validation_result = validate_record(fields, config.validation_rules)
            if extraction_metrics["low_confidence_fields"]:
                validation_result.status = "pending_review"
                validation_result.warnings.append(
                    "Low confidence fields: " + ", ".join(extraction_metrics["low_confidence_fields"])
                )
                validated["status"] = "pending_review"

            saved = save_record(
                validated,
                client_id,
                raw_text,
                validation_result,
                config_version=config_version,
                extraction_metrics=extraction_metrics,
            )
            add_audit_log(
                client_id,
                "extraction_completed",
                record_id=saved.id,
                job_id=job_id,
                actor="system",
                result=extraction_metrics,
            )
            results.append({"record_id": saved.id, "status": saved.status})

        update_job(client_id, job_id, "complete", result={"records": results})
    except Exception as exc:
        logger.exception("job_failed")
        update_job(client_id, job_id, "failed", error=str(exc))
        # RQ/Celery can retry the job; dead-letter is a final safety net for local/dev processing.
        move_job_to_dead_letter(client_id, job_id, str(exc), payload={"files": file_objs})
        raise
