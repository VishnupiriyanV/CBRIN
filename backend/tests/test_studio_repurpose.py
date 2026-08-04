"""
Tests for the Repurposer tool's two-stage pipeline and framework-preservation guardrail
(creator-tools-integration-spec.md §1, guardrail 7 in the STUDIO plan).

Run with: python -m pytest backend/tests/test_studio_repurpose.py -v
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import studio_prompts as sp  # noqa: E402

_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "model": "test-model"}


class TestRepurposeTwoStagePipeline:
    def test_extraction_runs_before_generation(self):
        extraction = {
            "core_argument": "arg", "frameworks": ["The Loop Method"],
            "strongest_example": "ex", "contrarian_line": "line",
        }
        generation = {
            "linkedin": {"hook": "h", "body": "Using The Loop Method changes everything.", "cta": "c"},
            "thread": [{"n": 1, "text": "t"}],
            "notes": ["n1", "n2", "n3"],
            "carousel": {"title": "t", "slides": [{"n": 1, "headline": "h", "body": "b"}], "caption": "c"},
        }
        with patch("studio_runner.call_llm", side_effect=[(extraction, _USAGE), (generation, _USAGE)]) as mock_call:
            output, usage_totals = sp._repurpose_run({"text": "source text"}, "")

        assert mock_call.call_count == 2
        assert output["extraction"] == extraction
        assert output["linkedin"]["hook"] == "h"
        assert usage_totals["prompt_tokens"] == 20

    def test_framework_verbatim_preservation_passes_when_present(self):
        extraction = {"core_argument": "a", "frameworks": ["The Loop Method"], "strongest_example": "e", "contrarian_line": "l"}
        generation = {
            "linkedin": {"hook": "h", "body": "The Loop Method is the key idea here.", "cta": "c"},
            "thread": [{"n": 1, "text": "t"}], "notes": ["n"],
            "carousel": {"title": "t", "slides": [], "caption": "c"},
        }
        with patch("studio_runner.call_llm", side_effect=[(extraction, _USAGE), (generation, _USAGE)]):
            output, _u = sp._repurpose_run({"text": "source"}, "")

        assert output["guardrail_notes"]["frameworks_missing"] == []

    def test_framework_dropped_from_output_is_flagged(self):
        extraction = {"core_argument": "a", "frameworks": ["The Loop Method"], "strongest_example": "e", "contrarian_line": "l"}
        generation = {
            "linkedin": {"hook": "h", "body": "generic content with no framework mentioned", "cta": "c"},
            "thread": [{"n": 1, "text": "t"}], "notes": ["n"],
            "carousel": {"title": "t", "slides": [], "caption": "c"},
        }
        with patch("studio_runner.call_llm", side_effect=[(extraction, _USAGE), (generation, _USAGE)]):
            output, _u = sp._repurpose_run({"text": "source"}, "")

        assert "The Loop Method" in output["guardrail_notes"]["frameworks_missing"]

    def test_no_named_framework_is_not_flagged(self):
        extraction = {"core_argument": "a", "frameworks": [], "strongest_example": "e", "contrarian_line": "l"}
        generation = {
            "linkedin": {"hook": "h", "body": "b", "cta": "c"}, "thread": [], "notes": [],
            "carousel": {"title": "t", "slides": [], "caption": "c"},
        }
        with patch("studio_runner.call_llm", side_effect=[(extraction, _USAGE), (generation, _USAGE)]):
            output, _u = sp._repurpose_run({"text": "source"}, "")
        assert output["guardrail_notes"]["frameworks_missing"] == []
