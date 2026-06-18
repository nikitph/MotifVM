from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

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


class DeepSeekLLMClient:
    provider = "deepseek"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for --llm deepseek")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")

    def call_structured(self, spec: StructuredCallSpec, payload: Any) -> tuple[Any, dict[str, Any]]:
        started = time.time()
        retries = 0
        last_error = None
        for attempt in range(spec.maxRetries + 1):
            retries = attempt
            try:
                output = self._call_once(spec, payload)
                schema_ok = _validate_schema(output, spec.outputSchema)
                if schema_ok:
                    duration = time.time() - started
                    return output, self._record(spec, payload, output, "ok", retries, duration)
                last_error = "schema_failed"
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc.__class__.__name__
        if spec.fallback:
            output = spec.fallback(payload)
            schema_ok = _validate_schema(output, spec.outputSchema)
            duration = time.time() - started
            if schema_ok:
                return output, self._record(spec, payload, output, f"fallback_after_{last_error}", retries, duration)
        raise ValueError(f"DeepSeek structured call failed: {spec.callType} ({last_error})")

    def _call_once(self, spec: StructuredCallSpec, payload: Any) -> Any:
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a MotifVM structured call adapter. "
                        "Return only valid JSON matching the requested schema."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "callType": spec.callType,
                            "payload": payload,
                            "outputSchema": spec.outputSchema,
                        },
                        sort_keys=True,
                        default=str,
                    ),
                },
            ],
            "temperature": spec.temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        req = urlrequest.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=30) as response:
            raw = json.loads(response.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return json.loads(content)
        return content

    def _record(
        self,
        spec: StructuredCallSpec,
        payload: Any,
        output: Any,
        schema_status: str,
        retries: int,
        duration: float,
    ) -> dict[str, Any]:
        return {
            "callType": spec.callType,
            "provider": self.provider,
            "model": self.model,
            "promptVersion": "0.2.5",
            "inputHash": _hash(payload),
            "outputHash": _hash(output),
            "schemaStatus": schema_status,
            "retryCount": retries,
            "duration": duration,
            "cost": None,
        }


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
