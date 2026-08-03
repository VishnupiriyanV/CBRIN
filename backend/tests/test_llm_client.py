"""
Tests for llm_client.py's schema-validation retry and unavailable-provider handling
(ENGINE-PLAN.md Phase 2). No real network calls — the OpenAI client is mocked throughout.

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
        with patch.object(lc, "API_KEY", None):
            assert lc.is_configured() is False

    def test_configured_with_api_key(self):
        with patch.object(lc, "API_KEY", "fake-key-123"):
            assert lc.is_configured() is True


class TestCompleteJsonHappyPath:
    def test_valid_first_response_returns_parsed_array(self):
        schema = {"type": "array", "items": {"required": ["beat_type"]}}
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            json.dumps({"beats": [{"beat_type": "hook"}]})
        )
        with patch.object(lc, "API_KEY", "fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            result = lc.complete_json("system", "user", schema)
        assert result == [{"beat_type": "hook"}]
        assert mock_client.chat.completions.create.call_count == 1


class TestCompleteJsonNotConfigured:
    def test_raises_llm_unavailable_when_no_key(self):
        with patch.object(lc, "API_KEY", None):
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
        with patch.object(lc, "API_KEY", "fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            result = lc.complete_json("system", "user", schema, max_retries=1)
        assert result == [{"beat_type": "hook"}]
        assert mock_client.chat.completions.create.call_count == 2

    def test_invalid_twice_raises_llm_unavailable(self):
        schema = {"type": "array", "items": {"required": ["beat_type"]}}
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            json.dumps({"beats": [{"missing_field": True}]})
        )
        with patch.object(lc, "API_KEY", "fake-key"), patch.object(lc, "_get_client", return_value=mock_client):
            with pytest.raises(lc.LLMUnavailable):
                lc.complete_json("system", "user", schema, max_retries=1)
        assert mock_client.chat.completions.create.call_count == 2


class TestModelErrorSurfacesClearly:
    def test_model_not_found_raises_llm_unavailable_with_model_name(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception(
            "Error code: 404 - model 'bogus-model' not found"
        )
        with patch.object(lc, "API_KEY", "fake-key"), patch.object(lc, "_get_client", return_value=mock_client), \
             patch.object(lc, "MODEL", "bogus-model"):
            with pytest.raises(lc.LLMUnavailable) as exc_info:
                lc.complete_json("system", "user", {"type": "array", "items": {"required": []}})
        assert "bogus-model" in str(exc_info.value)
