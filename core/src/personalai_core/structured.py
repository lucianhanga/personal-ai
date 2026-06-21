"""Bounded, fail-closed structured-output generation (M8.2, #261).

Ask a model for output matching a Pydantic contract, validate it, and on failure feed a
:class:`RepairRequest` (the invalid payload + the validation errors) back for a bounded number of
repair attempts. If every attempt fails the function returns ``None`` — the caller MUST fail closed
(never act on an unvalidated payload). This is the reusable primitive behind the verification ladder
(the LLM-judge tier emits a structured verdict) and any future structured node.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import BaseModel, ValidationError

from personalai_contracts.ports import ChatMessage, GenerationRequest, ModelProvider, Role
from personalai_contracts.schemas import RepairRequest


def _extract_json(text: str) -> str:
    """Pull the first JSON object out of a model reply (tolerates prose / ```json fences)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text.strip()
    return text[start : end + 1]


async def _generate_text(provider: ModelProvider, request: GenerationRequest) -> str:
    text = ""
    async for chunk in provider.stream(request):
        if chunk.delta:
            text += chunk.delta
    return text


async def generate_structured[T: BaseModel](
    *,
    provider: ModelProvider,
    model: str,
    messages: Sequence[ChatMessage],
    schema: type[T],
    max_attempts: int = 2,
) -> T | None:
    """Generate output validated against ``schema``; repair-retry up to ``max_attempts`` then fail
    closed (return ``None``). The model is asked for JSON constrained to the schema; on a parse or
    validation error the next attempt is given a :class:`RepairRequest` (invalid payload + errors).
    """
    json_schema = schema.model_json_schema()
    convo = list(messages)
    for attempt in range(1, max_attempts + 1):
        raw = await _generate_text(
            provider,
            GenerationRequest(messages=convo, model=model, json_schema=json_schema, think=False),
        )
        errors: list[str]
        try:
            payload = json.loads(_extract_json(raw))
        except json.JSONDecodeError as exc:
            payload, errors = {"_raw": raw}, [f"not valid JSON: {exc}"]
        else:
            try:
                return schema.model_validate(payload)
            except ValidationError as exc:
                errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        if attempt < max_attempts:
            # Feed the structured repair request back so the next attempt can fix the exact errors.
            schema_id = getattr(schema, "SCHEMA_ID", schema.__name__)
            target_version = getattr(schema, "SCHEMA_VERSION", "1.0.0")
            repair = RepairRequest(
                schema_id=schema_id,
                target_version=target_version,
                invalid_payload=payload,
                errors=errors,
                attempt=attempt,
            )
            convo.append(
                ChatMessage(
                    Role.USER,
                    "Your previous output was invalid. Fix it and return ONLY valid JSON for the "
                    f"schema. Errors: {repair.errors}. Invalid payload: {json.dumps(payload)}",
                )
            )
    return None


__all__ = ["generate_structured"]
