"""
Provider-agnostic OpenAI-wire-compatible chat/JSON adapter for ENGINE's narrative analysis.

Google's Gemini API exposes an OpenAI-wire-compatible endpoint
(https://generativelanguage.googleapis.com/v1beta/openai/), so this needs zero new packages —
`openai>=1.0` is already a dependency (backend/requirements.txt), currently also used for
hosted Whisper at transcript_service.py. Keeping the provider behind VAULT_LLM_BASE_URL/
VAULT_LLM_MODEL env vars means Gemini, Groq, Cerebras, OpenRouter's free tier, or a local
Ollama/llama.cpp server all work without a code change — default is Gemini 2.0 Flash's free
tier (see .env.example).

Verify the exact model ID against the provider's current model list before deploying — free
tiers rotate and retire model IDs, so `gemini-2.0-flash` below is a starting point, not a
guarantee.

BASE_URL/API_KEY/MODEL are exposed as module-level "attributes" via __getattr__ (PEP 562)
rather than constants set once at import time, so a value change to VAULT_LLM_* env vars is
picked up by every *cross-module* access (e.g. `llm_client.MODEL` from agent_engine.py).
That mechanism does NOT cover bare-name references inside this module's own functions —
Python resolves `MODEL` used directly in a function body via LOAD_GLOBAL against this
module's real globals, never through __getattr__, so every call site in this file must use
get_model()/get_base_url()/get_api_key() instead of the bare names.
"""
import json
import os
import time
from typing import Any, Dict, List, NamedTuple, Optional

import llm_throttle

def get_base_url() -> str:
    return os.getenv("VAULT_LLM_BASE_URL", "https://api.sambanova.ai/v1")


def get_api_key() -> Optional[str]:
    return os.getenv("VAULT_LLM_API_KEY")


def get_model() -> str:
    return os.getenv("VAULT_LLM_MODEL", "Meta-Llama-3.3-70B-Instruct")


def __getattr__(name: str) -> Any:
    if name == "BASE_URL":
        return get_base_url()
    if name == "API_KEY":
        return get_api_key()
    if name == "MODEL":
        return get_model()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


_client = None
_client_config = None


class LLMUnavailable(Exception):
    """No key configured, provider unreachable, or the response never validated against the
    requested schema even after one retry. Callers should fall back to heuristic analysis.

    `usage` carries whatever tokens were spent before giving up. A call that exhausts its
    retries still costs money — the provider billed every attempt — and raising without it
    meant that spend vanished from the monthly total entirely. It is zeroed for the failures
    that never reached the provider (no key, unreachable), which genuinely cost nothing.
    """

    def __init__(self, message: str, usage: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.usage = usage or {"prompt_tokens": 0, "completion_tokens": 0}


def is_configured() -> bool:
    return bool(get_api_key())


def _get_client():
    global _client, _client_config
    current_config = (get_base_url(), get_api_key())
    if _client is None or _client_config != current_config:
        import openai
        _client = openai.OpenAI(base_url=current_config[0], api_key=current_config[1])
        _client_config = current_config
    return _client


class Resolved(NamedTuple):
    client: Any
    model: str
    base_url: str
    api_key: Optional[str]
    bucket: str


def resolve() -> "Resolved":
    """Single source of truth for which (client, model, base_url) a call actually uses.

    Single provider by design (STRATEGY.md §4): the VAULT_TOOLS_LLM_* pair existed only to
    dodge free-tier rate limits by splitting traffic across two accounts. That is solved by
    a paid key or BYO key, not by config complexity.
    """
    if get_api_key():
        return Resolved(_get_client(), get_model(), get_base_url(), get_api_key(),
                        llm_throttle.bucket_key(get_base_url(), get_model()))
    raise LLMUnavailable("VAULT_LLM_API_KEY is not set.")


# Candidate fallback models per provider, tried in order if the primary model is rate limited.
# Keyed on the base_url a call is ACTUALLY going to (see fallback_models below) — not on
# get_base_url(), which used to pick the wrong ladder whenever the TOOLS client (potentially a
# different provider) was the one making the call.
_FALLBACK_MODELS = {
    "groq.com": ["llama-3.1-8b-instant"],
    "sambanova": ["Qwen2.5-72B-Instruct"],
}


def fallback_models(base_url: str, model: str) -> List[str]:
    """Primary model first, then provider-appropriate cheaper models to retry a rate-limited
    call against — resolved from the base_url the call is actually using."""
    models = [model]
    base_lower = (base_url or "").lower()
    for host, fallbacks in _FALLBACK_MODELS.items():
        if host in base_lower:
            for fb in fallbacks:
                if fb not in models:
                    models.append(fb)
            break
    return models


def is_rate_limit_error(msg: str) -> bool:
    """429 / rate_limit / rate limit / resource_exhausted / quota / too many requests.

    Deliberately does NOT match the bare substring 'limit' — the old check
    (`"limit" in msg.lower()`) misclassified 'maximum context length exceeded' and 'token
    limit exceeded' as rate limits, which made the client silently sleep-and-retry (then
    swap models) a request that could never succeed no matter how long it waited."""
    lowered = msg.lower()
    return (
        "429" in msg
        or "rate_limit" in lowered
        or "rate limit" in lowered
        or "resource_exhausted" in lowered
        or "quota" in lowered
        or "too many requests" in lowered
    )


def is_context_length_error(msg: str) -> bool:
    """Non-retryable against the SAME model at the SAME size: the request is too large for
    either the model's context window or its per-minute token budget. No amount of backoff
    fixes this — it needs a smaller request (a smaller window) or a different model.

    Groq's TPM-budget rejections ("Request too large for model `X` ... on tokens per minute
    (TPM): Limit 6000, Requested 10086, please reduce your message size") carry
    `code: rate_limit_exceeded`, so without matching this exact phrasing they were
    misclassified as a plain rate limit and given 2 pointless backoff-and-retry attempts
    against a model that can never succeed at that request size no matter how long it waits —
    confirmed against a real production failure on `llama-3.1-8b-instant`'s 6000 TPM cap
    during narrative_engine beat extraction (a ~60-sentence window's prompt runs ~10k tokens)."""
    lowered = msg.lower()
    return (
        "context_length_exceeded" in lowered
        or "context length" in lowered
        or "maximum context" in lowered
        or "too many tokens" in lowered
        or "reduce the length" in lowered
        or "request too large" in lowered
        or "reduce your message size" in lowered
    )


def is_model_not_found_error(msg: str) -> bool:
    lowered = msg.lower()
    return "model" in lowered and ("not found" in lowered or "404" in msg or "does not exist" in lowered)


def _validate(parsed: Dict[str, Any], schema: Dict[str, Any]) -> Optional[str]:
    """
    Minimal structural validation against a JSON-schema-like dict.
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
    resolved = resolve()
    client, model_name = resolved.client, resolved.model

    attempt_user = user
    last_error = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "model": model_name}

    for attempt in range(max_retries + 1):
        try:
            response = _call_with_backoff(
                client, model_name, system, attempt_user, resolved.base_url, resolved.bucket,
                temperature=temperature, max_tokens=max_tokens,
            )
            # ACCUMULATE, don't replace. Every attempt is billed by the provider, including
            # one whose JSON failed to parse or validate — and this retry exists precisely
            # because that happens. Assigning here meant a call that succeeded on the retry
            # reported only the retry's tokens: measured on a mocked two-attempt call, 500
            # prompt + 120 completion tokens were billed and never recorded. usage.record()
            # feeds the monthly total shown in the UI, so the spend figure ran low by exactly
            # the attempts the user could not see.
            attempt_usage = _extract_usage(response, model_name)
            usage["prompt_tokens"] += attempt_usage.get("prompt_tokens", 0) or 0
            usage["completion_tokens"] += attempt_usage.get("completion_tokens", 0) or 0
            usage["model"] = attempt_usage.get("model") or usage["model"]

            raw = response.choices[0].message.content
            parsed = json.loads(raw)

            # Robust unwrapping for JSON arrays wrapped in objects by LLMs
            if schema.get("type") == "array" and isinstance(parsed, dict):
                unwrapped = None
                for key in ("items", "comments", "replies", "flags", "results", "data", "list", "array", "output", "response", "suggestions", "result", "reply", "beats", "queries"):
                    if key in parsed and isinstance(parsed[key], list):
                        unwrapped = parsed[key]
                        break

                if unwrapped is None:
                    list_values = [v for v in parsed.values() if isinstance(v, list)]
                    if len(list_values) >= 1:
                        unwrapped = max(list_values, key=len)
                    elif parsed and all(isinstance(v, (dict, list)) for v in parsed.values()):
                        unwrapped = list(parsed.values())

                if unwrapped is not None:
                    parsed = unwrapped

            error = _validate(parsed, schema)
            if error is None:
                return parsed, usage
            last_error = error
        except LLMUnavailable:
            raise
        except json.JSONDecodeError as e:
            last_error = f"Response was not valid JSON: {e}"
        except Exception as e:
            # Was `except (json.JSONDecodeError, Exception)` — a redundant tuple (JSONDecodeError
            # IS an Exception) that quietly turned any programming error in the unwrap/validate
            # block above into a generic "schema validation failed after retry" message,
            # indistinguishable from an actual provider problem.
            last_error = f"{type(e).__name__}: {e}"

        attempt_user = (
            f"{user}\n\nYour previous response was invalid: {last_error}. "
            f"Respond again with ONLY valid JSON matching the required shape."
        )

    raise LLMUnavailable(
        f"LLM response failed schema validation after retry: {last_error}", usage=usage
    )


def _extract_usage(response, model_name: str) -> Dict[str, Any]:
    try:
        raw_usage = response.usage
        finish_reason = None
        try:
            finish_reason = response.choices[0].finish_reason
        except Exception:
            pass
        return {
            "prompt_tokens": int(getattr(raw_usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(raw_usage, "completion_tokens", 0) or 0),
            "model": model_name,
            "finish_reason": finish_reason,
        }
    except Exception:
        return {"prompt_tokens": 0, "completion_tokens": 0, "model": model_name, "finish_reason": None}


def _call_with_backoff(
    client, model_name: str, system: str, user: str, base_url: str, bucket: str,
    max_attempts: int = 2, temperature: float = 0.2, max_tokens: Optional[int] = None,
):
    delay = 1.0

    # Candidate fallback models if primary model is rate limited, resolved from the base_url
    # this call is ACTUALLY using — not get_base_url(), which used to pick the wrong ladder
    # whenever the TOOLS client (potentially a different provider) made the call.
    models_to_try = fallback_models(base_url, model_name)

    # One entry per model actually tried, so the final error (if every model fails) reports
    # what happened at EACH of them — not just the last one. Before this, a primary model
    # that failed for a real, actionable reason (e.g. a transient rate limit) had its error
    # silently discarded once the ladder moved to the fallback model, so a "too large" error
    # from a small fallback model was the ONLY thing ever surfaced to the user, hiding
    # whatever actually happened with the model they configured.
    attempts_summary: List[str] = []

    for current_model in models_to_try:
        last_exc_for_model: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                llm_throttle.acquire(bucket)
                kwargs: Dict[str, Any] = dict(
                    model=current_model,
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
                if is_model_not_found_error(msg):
                    raise LLMUnavailable(
                        f"LLM provider rejected model '{current_model}': {msg}. Verify model ID against provider list."
                    )
                if is_context_length_error(msg):
                    # Non-retryable against THIS model at THIS size — no amount of backoff
                    # fixes an oversized request. Record it and move on to the next model in
                    # the ladder (if any) rather than burning the remaining attempts on a
                    # request that can never succeed here no matter how long it waits — the
                    # old bare-"limit" substring match used to treat this as a plain rate
                    # limit and sleep-retry it pointlessly.
                    last_exc_for_model = e
                    break
                if is_rate_limit_error(msg):
                    last_exc_for_model = e
                    if attempt < max_attempts - 1:
                        time.sleep(delay)
                        delay *= 1.5
                        continue
                    break
                raise LLMUnavailable(f"LLM call failed: {msg}") from e
        attempts_summary.append(f"{current_model}: {last_exc_for_model}")

    raise LLMUnavailable(
        "LLM call failed after attempts across models — " + "; ".join(attempts_summary)
    )
