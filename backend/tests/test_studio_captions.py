"""
Tests for the Caption Reformatter's config-driven limits and never-truncate guardrail
(creator-tools-integration-spec.md §5; guardrails 13-15 in the STUDIO plan).

Run with: python -m pytest backend/tests/test_studio_captions.py -v
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import platform_rules  # noqa: E402
import studio_prompts as sp  # noqa: E402

_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "model": "test-model"}


class TestCharLimitEnforcement:
    def test_within_limit_caption_passes_through(self):
        result = {"caption": "short caption", "hashtags": ["#one", "#two"]}
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)) as mock_call:
            output, _u = sp._captions_run({"text": "source", "platforms": ["x"]}, "")
        assert mock_call.call_count == 1
        assert output["x"]["over_limit"] is False

    def test_over_limit_triggers_a_regenerate_not_a_truncation(self):
        char_limit = platform_rules.DEFAULT_PLATFORM_RULES["x"]["char_limit"]
        too_long = {"caption": "x" * (char_limit + 50), "hashtags": []}
        compliant = {"caption": "short enough now", "hashtags": []}
        with patch("studio_runner.call_llm", side_effect=[(too_long, _USAGE), (compliant, _USAGE)]) as mock_call:
            output, _u = sp._captions_run({"text": "source", "platforms": ["x"]}, "")

        assert mock_call.call_count == 2
        assert output["x"]["caption"] == "short enough now"
        assert output["x"]["over_limit"] is False

    def test_still_over_limit_after_retry_is_flagged_never_sliced(self):
        char_limit = platform_rules.DEFAULT_PLATFORM_RULES["x"]["char_limit"]
        still_too_long_1 = {"caption": "x" * (char_limit + 50), "hashtags": []}
        still_too_long_2 = {"caption": "y" * (char_limit + 10), "hashtags": []}
        with patch("studio_runner.call_llm", side_effect=[(still_too_long_1, _USAGE), (still_too_long_2, _USAGE)]):
            output, _u = sp._captions_run({"text": "source", "platforms": ["x"]}, "")

        assert output["x"]["over_limit"] is True
        assert output["x"]["caption"] == "x" * (char_limit + 50)  # the original, not a sliced version


class TestHashtagCap:
    def test_excess_hashtags_are_trimmed_to_the_configured_max(self):
        max_tags = platform_rules.DEFAULT_PLATFORM_RULES["x"]["hashtag_max"]
        result = {"caption": "caption", "hashtags": [f"#tag{i}" for i in range(max_tags + 10)]}
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)):
            output, _u = sp._captions_run({"text": "source", "platforms": ["x"]}, "")
        assert len(output["x"]["hashtags"]) == max_tags


class TestMultiPlatformRun:
    def test_runs_once_per_requested_platform(self):
        result = {"caption": "c", "hashtags": []}
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)) as mock_call:
            output, _u = sp._captions_run({"text": "source", "platforms": ["x", "linkedin", "tiktok"]}, "")
        assert mock_call.call_count == 3
        assert set(output.keys()) == {"x", "linkedin", "tiktok"}

    def test_defaults_to_all_six_platforms_when_unspecified(self):
        result = {"caption": "c", "hashtags": []}
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)):
            output, _u = sp._captions_run({"text": "source"}, "")
        assert set(output.keys()) == set(sp.DEFAULT_CAPTION_PLATFORMS)


class TestRegenerateOnePlatform:
    def test_regenerate_only_calls_llm_once_for_the_target_platform(self):
        result = {"caption": "regenerated", "hashtags": ["#a"]}
        with patch("studio_runner.call_llm", return_value=(result, _USAGE)) as mock_call:
            block_output, _u = sp._captions_regenerate({"text": "source", "cta": ""}, "x", "")
        assert mock_call.call_count == 1
        assert block_output["caption"] == "regenerated"
