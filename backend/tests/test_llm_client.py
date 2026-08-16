"""
Tests for llm_client.py's schema-validation retry and unavailable-provider handling
(ENGINE-PLAN.md Phase 2). No real network calls — the OpenAI client is mocked throughout.

BASE_URL/API_KEY/MODEL are resolved dynamically via get_base_url()/get_api_key()/get_model()
(module __getattr__, PEP 562) rather than constants frozen at import time, so tests patch
those accessor functions directly instead of patching module attributes — patching
`lc.API_KEY` wouldn't touch what get_api_key() actually reads (os.environ).

Run with: python -m pytest backend/tests/test_llm_client.py -v
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import llm_client as lc  # noqa: E402


def _mock_response(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


class TestIsConfigured:
    def test_not_configured_without_api_key(self):
        with patch.object(lc, "get_api_key", return_value=None):
            assert lc.is_configured() is False

    def test_configured_with_api_key(self):
        with patch.object(lc, "get_api_key", return_value="fake-key-123"):
            assert lc.is_configured() is True


class TestCompleteJsonHappyPath:
    def test_valid_first_response_returns_parsed_array(self):
        schema = {"type": "array", "items": {"required": ["beat_type"]}}
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            json.dumps({"beats": [{"beat_type": "hook"}]})
        )
        with patch.object(lc, "get_api_key", return_value="fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            result = lc.complete_json("system", "user", schema)
        assert result == [{"beat_type": "hook"}]
        assert mock_client.chat.completions.create.call_count == 1

    def test_dict_wrapper_unwrapped_to_array(self):
        schema = {"type": "array", "items": {"required": ["index", "suggested_reply"]}}
        mock_client = MagicMock()
        # LLMs in json_object mode often wrap array outputs in dicts like {"replies": [...], "meta": "..."}
        mock_client.chat.completions.create.return_value = _mock_response(
            json.dumps({"replies": [{"index": 0, "suggested_reply": "Thanks!"}], "notes": "some text"})
        )
        with patch.object(lc, "get_api_key", return_value="fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            result = lc.complete_json("system", "user", schema)
        assert result == [{"index": 0, "suggested_reply": "Thanks!"}]


class TestCompleteJsonNotConfigured:
    def test_raises_llm_unavailable_when_no_key(self):
        with patch.object(lc, "get_api_key", return_value=None):
            with pytest.raises(lc.LLMUnavailable):
                lc.complete_json("system", "user", {"type": "array", "items": {"required": []}})


class TestSchemaValidationRetry:
    def test_invalid_then_valid_retries_once_and_succeeds(self):
        schema = {"type": "array", "items": {"required": ["beat_type"]}}
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _mock_response(json.dumps({"beats": [{"missing_field": True}]})),  # invalid: no beat_type
            _mock_response(json.dumps({"beats": [{"beat_type": "hook"}]})),    # valid retry
        ]
        with patch.object(lc, "get_api_key", return_value="fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            result = lc.complete_json("system", "user", schema, max_retries=1)
        assert result == [{"beat_type": "hook"}]
        assert mock_client.chat.completions.create.call_count == 2

    def test_invalid_twice_raises_llm_unavailable(self):
        schema = {"type": "array", "items": {"required": ["beat_type"]}}
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            json.dumps({"beats": [{"missing_field": True}]})
        )
        with patch.object(lc, "get_api_key", return_value="fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            with pytest.raises(lc.LLMUnavailable):
                lc.complete_json("system", "user", schema, max_retries=1)
        assert mock_client.chat.completions.create.call_count == 2


class TestCompleteJsonWithUsage:
    def test_returns_usage_alongside_parsed_result(self):
        schema = {"type": "array", "items": {"required": ["beat_type"]}}
        mock_client = MagicMock()
        resp = _mock_response(json.dumps({"beats": [{"beat_type": "hook"}]}))
        resp.usage = MagicMock(prompt_tokens=120, completion_tokens=40)
        mock_client.chat.completions.create.return_value = resp
        with patch.object(lc, "get_api_key", return_value="fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            parsed, usage = lc.complete_json_with_usage("system", "user", schema)
        assert parsed == [{"beat_type": "hook"}]
        assert usage["prompt_tokens"] == 120
        assert usage["completion_tokens"] == 40

    def test_missing_usage_block_defaults_to_zero(self):
        schema = {"type": "array", "items": {"required": ["beat_type"]}}
        mock_client = MagicMock()
        resp = _mock_response(json.dumps({"beats": [{"beat_type": "hook"}]}))
        del resp.usage  # simulate a provider that omits usage entirely
        mock_client.chat.completions.create.return_value = resp
        with patch.object(lc, "get_api_key", return_value="fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            parsed, usage = lc.complete_json_with_usage("system", "user", schema)
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 0

    def test_temperature_and_max_tokens_passed_through(self):
        schema = {"type": "array", "items": {"required": ["beat_type"]}}
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            json.dumps({"beats": [{"beat_type": "hook"}]})
        )
        with patch.object(lc, "get_api_key", return_value="fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            lc.complete_json("system", "user", schema, temperature=0.8, max_tokens=500)
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["temperature"] == 0.8
        assert kwargs["max_tokens"] == 500


class TestModelErrorSurfacesClearly:
    def test_model_not_found_raises_llm_unavailable_with_model_name(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception(
            "Error code: 404 - model 'bogus-model' not found"
        )
        with patch.object(lc, "get_api_key", return_value="fake-key"), patch.object(lc, "_get_client", return_value=mock_client), \
             patch.object(lc, "get_model", return_value="bogus-model"):
            with pytest.raises(lc.LLMUnavailable) as exc_info:
                lc.complete_json("system", "user", {"type": "array", "items": {"required": []}})
        assert "bogus-model" in str(exc_info.value)


class TestDynamicConfigAccessors:
    """Regression guard: every call site inside llm_client.py must use get_model()/
    get_api_key()/get_base_url() rather than the bare MODEL/API_KEY/BASE_URL names — a bare
    name inside this module's own functions resolves via LOAD_GLOBAL against this module's
    real globals and never reaches __getattr__, so it would raise NameError at call time
    instead of picking up the current env var."""

    def test_model_change_is_picked_up_without_reimport(self):
        with patch.object(lc, "get_api_key", return_value="fake-key"):
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _mock_response(
                json.dumps({"beats": [{"beat_type": "hook"}]})
            )
            with patch.object(lc, "_get_client", return_value=mock_client), \
                 patch.object(lc, "get_model", return_value="gemini-2.0-flash"):
                lc.complete_json("system", "user", {"type": "array", "items": {"required": ["beat_type"]}})
            _, kwargs = mock_client.chat.completions.create.call_args
            assert kwargs["model"] == "gemini-2.0-flash"

    def test_external_module_attribute_access_still_works(self):
        """agent_engine.py reads llm_client.MODEL/.BASE_URL as cross-module attribute
        access — that path IS covered by __getattr__, unlike bare names inside this file."""
        with patch.dict(os.environ, {"VAULT_LLM_MODEL": "gemini-2.5-flash"}):
            assert lc.MODEL == "gemini-2.5-flash"


class TestResolve:
    """resolve() and is_configured() must never disagree about whether a call can be made.

    The dual-provider fallback tests that used to live here were removed with the
    VAULT_TOOLS_LLM_* pair (STRATEGY.md 4) - there is now exactly one provider, so the
    "tools-only key constructs a None-key client" class of bug is gone by construction.
    The invariants below are the part that still matters."""

    def test_no_key_raises_llm_unavailable(self):
        with patch.object(lc, "get_api_key", return_value=None):
            assert lc.is_configured() is False
            with pytest.raises(lc.LLMUnavailable):
                lc.resolve()

    def test_key_present_resolves_to_that_provider(self):
        with patch.object(lc, "get_api_key", return_value="primary-key"), \
             patch.object(lc, "get_base_url", return_value="https://api.groq.com/openai/v1"), \
             patch.object(lc, "get_model", return_value="llama-3.3-70b-versatile"):
            assert lc.is_configured() is True
            resolved = lc.resolve()
        assert resolved.api_key == "primary-key"
        assert resolved.model == "llama-3.3-70b-versatile"


class TestErrorClassification:
    def test_context_length_message_is_not_a_rate_limit(self):
        # The old check (`"limit" in msg.lower()`) misclassified this as a rate limit and
        # silently slept-and-retried a request that could never succeed.
        msg = "Error: This model's maximum context length is 8192 tokens. Please reduce the length of the messages."
        assert lc.is_rate_limit_error(msg) is False
        assert lc.is_context_length_error(msg) is True

    def test_429_message_is_a_rate_limit_not_context_length(self):
        msg = "Error code: 429 - {'error': {'message': 'Rate limit reached', 'code': 'rate_limit_exceeded'}}"
        assert lc.is_rate_limit_error(msg) is True
        assert lc.is_context_length_error(msg) is False

    def test_model_not_found_message(self):
        msg = "Error code: 404 - model 'bogus-model' not found"
        assert lc.is_model_not_found_error(msg) is True
        assert lc.is_rate_limit_error(msg) is False

    def test_groq_tpm_too_large_message_is_context_length_not_plain_rate_limit(self):
        # Real production message hit during narrative_engine beat extraction against
        # llama-3.1-8b-instant's free-tier TPM cap. Groq's own `code` field is
        # 'rate_limit_exceeded', so without matching this exact phrasing the message was
        # classified as a plain (retryable) rate limit and given pointless backoff-and-retry
        # attempts against a model that can never succeed at that request size.
        msg = (
            "Error code: 413 - {'error': {'message': \"Request too large for model "
            "`llama-3.1-8b-instant` in organization `org_x` service tier `on_demand` on "
            "tokens per minute (TPM): Limit 6000, Requested 10086, please reduce your "
            "message size and try again.\", 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
        )
        assert lc.is_context_length_error(msg) is True


class TestCallWithBackoffModelFallback:
    """Real production failure: narrative_engine beat extraction hit Groq's
    llama-3.1-8b-instant 6000 TPM cap on the fallback model. The old classification treated
    this as a plain rate limit, wasting a full backoff-and-retry cycle against a model that
    could never succeed at that request size, and the final exception only ever showed the
    LAST model's error — silently discarding whatever the PRIMARY model actually failed
    with, which is usually the more actionable diagnostic."""

    def test_context_length_error_is_not_retried_and_moves_to_next_model(self):
        too_large_error = Exception(
            "Error code: 413 - {'error': {'message': 'Request too large for model `model-a` "
            "on tokens per minute (TPM): Limit 6000, Requested 9000, please reduce your "
            "message size and try again.', 'code': 'rate_limit_exceeded'}}"
        )
        rate_limited_error = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit reached', 'code': 'rate_limit_exceeded'}}"
        )

        mock_client = MagicMock()
        # model-a: ONE call only (too-large is non-retryable against the same model).
        # model-b: two calls (a genuine rate limit gets its normal backoff-and-retry).
        mock_client.chat.completions.create.side_effect = [too_large_error, rate_limited_error, rate_limited_error]

        with patch.object(lc, "get_api_key", return_value="fake-key"), \
             patch.object(lc, "_get_client", return_value=mock_client), \
             patch.object(lc, "fallback_models", return_value=["model-a", "model-b"]):
            with pytest.raises(lc.LLMUnavailable) as exc_info:
                lc.complete_json("system", "user", {"type": "array", "items": {"required": []}})

        assert mock_client.chat.completions.create.call_count == 3

        err = str(exc_info.value)
        # Both models' real failures survive into the final message — not just the last one.
        assert "model-a" in err
        assert "model-b" in err
        assert "Request too large" in err


class TestFallbackLadder:
    def test_ladder_resolved_from_the_actual_base_url_not_get_base_url(self):
        # _call_with_backoff used to pick its fallback ladder from get_base_url() even when
        # the TOOLS client (potentially on a different provider than the primary) was the
        # one making the call.
        ladder = lc.fallback_models("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")
        assert ladder[0] == "llama-3.3-70b-versatile"
        assert "llama-3.1-8b-instant" in ladder

    def test_sambanova_ladder(self):
        ladder = lc.fallback_models("https://api.sambanova.ai/v1", "Meta-Llama-3.3-70B-Instruct")
        assert "Qwen2.5-72B-Instruct" in ladder

    def test_unknown_provider_has_no_fallback(self):
        ladder = lc.fallback_models("https://api.example-unknown.com/v1", "some-model")
        assert ladder == ["some-model"]


def _mock_response_with_usage(content: str, prompt_tokens: int, completion_tokens: int):
    resp = _mock_response(content)
    resp.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return resp


class TestUsageAccountsForEveryAttempt:
    """The provider bills each attempt, including one whose JSON failed to parse — and this
    retry exists because that happens. usage used to be ASSIGNED per attempt rather than
    accumulated, so a call that succeeded on the retry reported only the retry's tokens and
    the monthly spend shown in the UI ran low by the attempts the user never saw."""

    SCHEMA = {"type": "object", "required": ["beats"]}

    def _run(self, responses):
        client = MagicMock()
        client.chat.completions.create.side_effect = responses
        resolved = MagicMock(client=client, model="m", base_url="b", bucket="x")
        with patch.object(lc, "resolve", return_value=resolved):
            return lc.complete_json_with_usage("system", "user", self.SCHEMA)

    def test_retry_tokens_are_added_not_replaced(self):
        _parsed, usage = self._run([
            _mock_response_with_usage("not valid json", 500, 120),
            _mock_response_with_usage(json.dumps({"beats": []}), 520, 40),
        ])
        assert usage["prompt_tokens"] == 1020
        assert usage["completion_tokens"] == 160

    def test_single_attempt_is_unchanged(self):
        _parsed, usage = self._run([
            _mock_response_with_usage(json.dumps({"beats": []}), 300, 25),
        ])
        assert usage["prompt_tokens"] == 300
        assert usage["completion_tokens"] == 25

    def test_exhausted_retries_still_report_what_was_spent(self):
        # Raising bare used to drop the spend entirely, even though both calls were billed.
        with pytest.raises(lc.LLMUnavailable) as excinfo:
            self._run([
                _mock_response_with_usage("nope", 300, 50),
                _mock_response_with_usage("still nope", 310, 55),
            ])
        assert excinfo.value.usage["prompt_tokens"] == 610
        assert excinfo.value.usage["completion_tokens"] == 105

    def test_failures_that_never_reached_the_provider_report_zero(self):
        with patch.object(lc, "get_api_key", return_value=None):
            with pytest.raises(lc.LLMUnavailable) as excinfo:
                lc.complete_json_with_usage("system", "user", self.SCHEMA)
        assert excinfo.value.usage["prompt_tokens"] == 0
        assert excinfo.value.usage["completion_tokens"] == 0
