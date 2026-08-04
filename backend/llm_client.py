"""
Provider-agnostic OpenAI-wire-compatible chat/JSON adapter for ENGINE's narrative analysis.

Groq's API is OpenAI-wire-compatible, so this needs zero new packages — `openai>=1.0` is
already a dependency (backend/requirements.txt), currently used only for hosted Whisper at
transcript_service.py. Keeping the provider behind VAULT_LLM_BASE_URL/VAULT_LLM_MODEL env
vars means Groq, Cerebras, OpenRouter's free tier, or a local Ollama/llama.cpp server all
work without a code change.

Verify the exact model ID against the provider's current model list before deploying —
Groq rotates and retires model IDs, so `llama-3.3-70b-versatile` below is a starting point,
not a guarantee.
"""
import json
import os
import time
from typing import Any, Dict, Optional

BASE_URL = os.getenv("VAULT_LLM_BASE_URL", "https://api.groq.com/openai/v1")
API_KEY = os.getenv("VAULT_LLM_API_KEY")
MODEL = os.getenv("VAULT_LLM_MODEL", "llama-3.3-70b-versatile")

_client = None


class LLMUnavailable(Exception):
    """No key configured, provider unreachable, or the response never validated against the
    requested schema even after one retry. Callers should fall back to heuristic analysis."""


def is_configured() -> bool:
    return bool(API_KEY)


def _get_client():
    global _client
    if _client is None:
        import openai
        _client = openai.OpenAI(base_url=BASE_URL, api_key=API_KEY)
    return _client


def _validate(parsed: Dict[str, Any], schema: Dict[str, Any]) -> Optional[str]:
    """
    Minimal structural validation against a JSON-schema-like dict: checks the top-level
    'type' (object/array) and, for arrays of objects, that each item has the 'required'
    keys listed in schema['items']['required']. Not a full JSON Schema validator — just
    enough to catch a malformed or truncated LLM response before it reaches narrative_engine.
    Returns an error message string, or None if valid.
    """
    expected_type = schema.get("type")
    if expected_type == "array":
        if not isinstance(parsed, list):
            return f"Expected a JSON array, got {type(parsed).__name__}"
        item_schema = schema.get("items", {})
        required = item_schema.get("required", [])
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                return f"Item {i} is not an object"
            missing = [k for k in required if k not in item]
            if missing:
                return f"Item {i} missing required field(s): {missing}"
    elif expected_type == "object":
        if not isinstance(parsed, dict):
            return f"Expected a JSON object, got {type(parsed).__name__}"
        required = schema.get("required", [])
        missing = [k for k in required if k not in parsed]
        if missing:
            return f"Missing required field(s): {missing}"
    return None


def complete_json(
    system: str,
    user: str,
    schema: Dict[str, Any],
    max_retries: int = 1,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
) -> Any:
    """
    Call the configured LLM with response_format=json_object, validate the parse against
    `schema`, retry once with the validation error appended on failure, then raise
    LLMUnavailable. Also retries on HTTP 429 (free-tier rate limits) with jittered backoff.

    `temperature` defaults to the original 0.2 (narrative_engine's extraction use case).
    STUDIO's idea-generation tools (repurposer, title generator) pass a higher value —
    0.2 is too conservative for "give me 15 varied title ideas".
    """
    parsed, _usage = complete_json_with_usage(
        system, user, schema, max_retries=max_retries, temperature=temperature, max_tokens=max_tokens
    )
    return parsed


def complete_json_with_usage(
    system: str,
    user: str,
    schema: Dict[str, Any],
    max_retries: int = 1,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
) -> "tuple[Any, Dict[str, Any]]":
    """
    Same contract as complete_json, but also returns a usage dict:
    {"prompt_tokens": int, "completion_tokens": int, "model": str}. Introduced for
    STUDIO's usage meter (backend/usage.py) — narrative_engine's existing call sites don't
    need token counts, so complete_json stays the primary entry point and just discards
    the second return value.
    """
    if not is_configured():
        raise LLMUnavailable("VAULT_LLM_API_KEY is not set.")

    client = _get_client()
    attempt_user = user
    last_error = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "model": MODEL}

    for attempt in range(max_retries + 1):
        try:
            response = _call_with_backoff(
                client, system, attempt_user, temperature=temperature, max_tokens=max_tokens
            )
            usage = _extract_usage(response)
            raw = response.choices[0].message.content
            parsed = json.loads(raw)
            # The model may wrap the array in {"items": [...]}, {"replies": [...]}, etc., since
            # json_object mode requires a top-level object — unwrap the list if present.
            if schema.get("type") == "array" and isinstance(parsed, dict):
                unwrapped = None
                # Check standard list wrapper keys first
                for key in ("items", "comments", "replies", "flags", "results", "data", "list", "array"):
                    if key in parsed and isinstance(parsed[key], list):
                        unwrapped = parsed[key]
                        break

                if unwrapped is None:
                    list_values = [v for v in parsed.values() if isinstance(v, list)]
                    if len(list_values) == 1:
                        unwrapped = list_values[0]
                    elif len(list_values) > 1:
                        unwrapped = max(list_values, key=len)
                    elif parsed and all(isinstance(v, dict) for v in parsed.values()):
                        unwrapped = list(parsed.values())

                if unwrapped is not None:
                    parsed = unwrapped

            error = _validate(parsed, schema)
            if error is None:
                return parsed, usage
            last_error = error
        except (json.JSONDecodeError, Exception) as e:  # noqa: BLE001 - narrowed by re-raise below
            if isinstance(e, LLMUnavailable):
                raise
            last_error = str(e)

        attempt_user = (
            f"{user}\n\nYour previous response was invalid: {last_error}. "
            f"Respond again with ONLY valid JSON matching the required shape."
        )

    raise LLMUnavailable(f"LLM response failed schema validation after retry: {last_error}")


def _extract_usage(response) -> Dict[str, Any]:
    """Defensive extraction — some OpenAI-wire-compatible providers omit `usage` entirely,
    and test mocks never populate it. Never let a missing/malformed usage block fail a
    successful generation."""
    try:
        raw_usage = response.usage
        return {
            "prompt_tokens": int(getattr(raw_usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(raw_usage, "completion_tokens", 0) or 0),
            "model": MODEL,
        }
    except Exception:
        return {"prompt_tokens": 0, "completion_tokens": 0, "model": MODEL}


def _call_with_backoff(
    client, system: str, user: str, max_attempts: int = 3, temperature: float = 0.2,
    max_tokens: Optional[int] = None,
):
    delay = 1.0
    last_exc = None
    for attempt in range(max_attempts):
        try:
            kwargs: Dict[str, Any] = dict(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            msg = str(e)
            is_rate_limit = "429" in msg or "rate" in msg.lower()
            is_model_error = "model" in msg.lower() and ("not found" in msg.lower() or "404" in msg)
            if is_model_error:
                # A typo'd/retired model ID deserves a clear diagnosis, not a silent
                # degraded-mode fallback that hides a one-line config fix.
                raise LLMUnavailable(
                    f"LLM provider rejected model '{MODEL}': {msg}. Verify VAULT_LLM_MODEL "
                    f"against the provider's current model list."
                )
            if is_rate_limit and attempt < max_attempts - 1:
                time.sleep(delay + (0.1 * attempt))
                delay *= 2
                last_exc = e
                continue
            raise LLMUnavailable(f"LLM call failed: {msg}") from e
    raise LLMUnavailable(f"LLM call failed after {max_attempts} attempts: {last_exc}")
