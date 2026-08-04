"""
Tests for the Title & Hook Generator's honesty guardrails: 60-char flagging (never
truncating), thumbnail text-only/word-limit, and formula-diversity retry
(creator-tools-integration-spec.md §3; guardrails 10-12 in the STUDIO plan).

Run with: python -m pytest backend/tests/test_studio_titles.py -v
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import studio_prompts as sp  # noqa: E402

_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "model": "test-model"}


def _titles_result(formulas, texts=None):
    texts = texts or [f"Title {i}" for i in range(len(formulas))]
    return {
        "titles": [
            {"text": t, "formula": f, "why": "reason", "promise": "promise"}
            for t, f in zip(texts, formulas)
        ],
        "hooks": [{"text": "hook", "style": "style"}],
        "thumbnail_text": ["short text"],
    }


class TestCharLimitHonesty:
    def test_under_60_chars_not_flagged(self):
        result = _titles_result(["question"], texts=["Short title"])
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)):
            output, _u = sp._titles_run({"topic": "testing"}, "")
        assert output["titles"][0]["over_limit"] is False
        assert output["titles"][0]["char_count"] == len("Short title")

    def test_over_60_chars_is_flagged_not_truncated(self):
        long_title = "A" * 75
        result = _titles_result(["question"], texts=[long_title])
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)):
            output, _u = sp._titles_run({"topic": "testing"}, "")
        assert output["titles"][0]["over_limit"] is True
        assert output["titles"][0]["text"] == long_title  # never sliced


class TestThumbnailTextOnly:
    def test_thumbnail_under_word_limit(self):
        result = _titles_result(["question"])
        result["thumbnail_text"] = ["three word text"]
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)):
            output, _u = sp._titles_run({"topic": "testing"}, "")
        assert output["thumbnail_text"][0]["over_word_limit"] is False

    def test_thumbnail_over_word_limit_is_flagged(self):
        result = _titles_result(["question"])
        result["thumbnail_text"] = ["this is way too many words for a thumbnail"]
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)):
            output, _u = sp._titles_run({"topic": "testing"}, "")
        assert output["thumbnail_text"][0]["over_word_limit"] is True


class TestFormulaEnumValidation:
    def test_invalid_formula_becomes_unclassified(self):
        result = _titles_result(["not_a_real_formula"])
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)):
            output, _u = sp._titles_run({"topic": "testing"}, "")
        assert output["titles"][0]["formula"] == "unclassified"


class TestDiversityRetry:
    def test_low_diversity_triggers_a_retry(self):
        dominant_batch = _titles_result(["question"] * 8 + ["number_list"] * 2)
        diverse_batch = _titles_result(
            ["question", "number_list", "contrarian", "transformation", "mistake_warning",
             "comparison", "time_bound_challenge", "authority_credential", "beginner_framing", "question"]
        )
        with patch("studio_runner.call_llm", side_effect=[(dominant_batch, _USAGE), (diverse_batch, _USAGE)]) as mock_call:
            output, usage_totals = sp._titles_run({"topic": "testing"}, "")

        assert mock_call.call_count == 2
        assert output["guardrail_notes"].get("low_diversity") is not True
        assert usage_totals["prompt_tokens"] == 20

    def test_high_diversity_does_not_retry(self):
        diverse_batch = _titles_result(
            ["question", "number_list", "contrarian", "transformation", "mistake_warning"]
        )
        with patch("studio_runner.call_llm", return_value=(diverse_batch, _USAGE)) as mock_call:
            output, _u = sp._titles_run({"topic": "testing"}, "")
        assert mock_call.call_count == 1
        assert "low_diversity" not in output["guardrail_notes"]
