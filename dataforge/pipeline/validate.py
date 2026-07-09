from __future__ import annotations

import re
from typing import Any
from dataforge.models import ValidationRules, ValidationResult


def validate_record(record: dict[str, Any], rules: ValidationRules | dict) -> tuple[dict[str, Any], ValidationResult]:
    if isinstance(rules, dict):
        rules = ValidationRules.model_validate(rules)

    errors: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []

    for field in rules.required_fields:
        if record.get(field) in (None, "", []):
            missing.append(field)
            errors.append(f"Missing required field: {field}")

    combined_text = " ".join(str(v).lower() for v in record.values() if v is not None)
    urgent = any(keyword.lower() in combined_text for keyword in rules.urgent_keywords)
    if urgent:
        warnings.append("Urgency keyword detected")

    for custom_rule in rules.custom_rules:
        value = record.get(custom_rule.field)
        if value is None:
            continue
        if custom_rule.rule == "regex" and not re.match(str(custom_rule.value), str(value)):
            errors.append(f"Field {custom_rule.field} failed regex validation")
        elif custom_rule.rule == "range":
            min_value, max_value = custom_rule.value
            try:
                numeric_value = float(value)
                if numeric_value < min_value or numeric_value > max_value:
                    errors.append(f"Field {custom_rule.field} outside allowed range")
            except (TypeError, ValueError):
                errors.append(f"Field {custom_rule.field} must be numeric")
        elif custom_rule.rule == "enum" and value not in custom_rule.value:
            errors.append(f"Field {custom_rule.field} must be one of {custom_rule.value}")

    status = "pending_review" if errors or urgent else "approved"
    result = ValidationResult(
        status=status,
        errors=errors,
        warnings=warnings,
        urgent=urgent,
        missing_required_fields=missing,
    )
    record["status"] = status
    return record, result
