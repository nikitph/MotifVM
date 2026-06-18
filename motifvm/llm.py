from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from .model import StatePatch


@dataclass
class StructuredCallSpec:
    callType: str
    inputSchema: dict[str, Any]
    outputSchema: dict[str, Any]
    temperature: float
    maxRetries: int
    fallback: Callable[[Any], Any] | None = None


class MockLLMClient:
    provider = "mock"
    model = "mock-structured-v0"

    def call_structured(self, spec: StructuredCallSpec, payload: Any) -> tuple[Any, dict[str, Any]]:
        started = time.time()
        output = _mock_output(spec.callType, payload)
        schema_ok = _validate_schema(output, spec.outputSchema)
        retries = 0
        if not schema_ok and spec.fallback:
            output = spec.fallback(payload)
            schema_ok = _validate_schema(output, spec.outputSchema)
            retries = 1
        duration = time.time() - started
        record = {
            "callType": spec.callType,
            "provider": self.provider,
            "model": self.model,
            "promptVersion": "0.1.8",
            "inputHash": _hash(payload),
            "outputHash": _hash(output),
            "schemaStatus": "ok" if schema_ok else "failed",
            "retryCount": retries,
            "duration": duration,
        }
        if not schema_ok:
            raise ValueError(f"Structured call failed schema validation: {spec.callType}")
        return output, record


def _mock_output(call_type: str, payload: Any) -> Any:
    if call_type == "CALL_PARSE":
        return payload.get("fallbackTaskAst")
    if call_type == "CALL_DIAGNOSE":
        return payload.get("fallbackMotifVector")
    if call_type == "CALL_PASS_ASSIST":
        return StatePatch().to_dict()
    if call_type == "CALL_VERIFY_COHERENCE":
        return {"passed": True, "message": "Mock coherence check passed."}
    if call_type == "CALL_EMIT":
        return {"text": payload.get("fallbackText", "")}
    return {}


def _validate_schema(value: Any, schema: dict[str, Any]) -> bool:
    required = schema.get("required", [])
    if required and not isinstance(value, dict):
        return False
    for key in required:
        if key not in value:
            return False
    expected_type = schema.get("type")
    if expected_type == "object" and not isinstance(value, dict):
        return False
    if expected_type == "array" and not isinstance(value, list):
        return False
    return True


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
