"""
Tests for the Show Notes tool's timestamp-honesty guardrails (creator-tools-integration-spec.md
§2 — "never fabricate precise timestamps"; guardrails 1 and 2 in the STUDIO plan). The model
never emits a time value in these tests' mocked responses on purpose: the point is that the
*backend* derives every displayed time from parsed cue data, not from the model.

Run with: python -m pytest backend/tests/test_studio_shownotes.py -v
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import studio_prompts as sp  # noqa: E402

_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "model": "test-model"}

_SRT = """1
00:00:00,000 --> 00:00:03,000
Welcome to the show today we're talking about testing.

2
00:00:03,000 --> 00:00:07,000
Our guest has a lot to say about it.
"""

_LLM_RESULT = {
    "summary": "A show about testing.",
    "show_notes": ["Testing matters."],
    "chapters": [{"start_sentence_idx": 0, "title": "Intro to testing"}],
    "titles": ["Why Testing Matters"],
    "promo": "Check out this episode on testing.",
    "clip_worthy_sentence_indices": [0],
}


class TestRealTimestampMode:
    def test_srt_input_produces_real_non_estimated_times(self):
        with patch("studio_runner.call_llm", return_value=(_LLM_RESULT, _USAGE)):
            output, _u = sp._show_notes_run({"source": "paste", "transcript_text": _SRT}, "")

        assert output["timestamp_mode"] == "real"
        assert output["chapters"][0]["estimated"] is False
        assert output["chapters"][0]["time"] is not None

    def test_hallucinated_chapter_index_is_dropped_not_guessed(self):
        bad_result = dict(_LLM_RESULT)
        bad_result["chapters"] = [{"start_sentence_idx": 999, "title": "Fake chapter"}]
        with patch("studio_runner.call_llm", return_value=(bad_result, _USAGE)):
            output, _u = sp._show_notes_run({"source": "paste", "transcript_text": _SRT}, "")
        assert output["chapters"] == []


class TestPlainTextNoTimeMode:
    def test_plain_text_without_duration_hint_has_no_times(self):
        plain = "This is a plain paragraph with no timing information at all in it whatsoever."
        with patch("studio_runner.call_llm", return_value=(_LLM_RESULT, _USAGE)):
            output, _u = sp._show_notes_run({"source": "paste", "transcript_text": plain}, "")

        assert output["timestamp_mode"] == "none"
        assert output["chapters"][0]["time"] is None
        assert output["chapters"][0]["estimated"] is False


class TestPlainTextEstimatedMode:
    def test_plain_text_with_duration_hint_is_marked_estimated(self):
        plain = " ".join(["word"] * 300)
        with patch("studio_runner.call_llm", return_value=(_LLM_RESULT, _USAGE)):
            output, _u = sp._show_notes_run(
                {"source": "paste", "transcript_text": plain, "duration_hint_sec": 600}, ""
            )

        assert output["timestamp_mode"] == "estimated"
        assert output["chapters"][0]["estimated"] is True
        assert output["chapters"][0]["time"] is not None


class TestLibrarySource:
    def test_library_source_uses_supplied_sentences_directly(self):
        sentences = [
            {"sentence_idx": 0, "start_sec": 10, "end_sec": 15, "text": "hello from the library"},
        ]
        with patch("studio_runner.call_llm", return_value=(_LLM_RESULT, _USAGE)):
            output, _u = sp._show_notes_run({"source": "library", "sentences": sentences}, "")
        assert output["timestamp_mode"] == "real"
        assert output["chapters"][0]["time"] == "00:10"

    def test_library_source_with_no_sentences_raises(self):
        import studio_runner as sr
        import pytest
        with pytest.raises(sr.InputRejected):
            sp._show_notes_run({"source": "library", "sentences": []}, "")
