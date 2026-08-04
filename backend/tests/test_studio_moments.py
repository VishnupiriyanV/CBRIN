"""
Tests for the Clip-Moment Finder's hard timestamp requirement, lead-in expansion, and type
diversity enforcement (creator-tools-integration-spec.md §6; guardrails 3, 16, 17, 18 in the
STUDIO plan).

Uses source="library" with hand-built sentence lists throughout so these tests never import
multimodal_engine (a heavy torch/sentence-transformers import) — that path is only exercised
by the "paste" source, covered separately in test_studio_shownotes.py's SRT tests, which share
the same _resolve_sentences_or_reject() helper.

Run with: python -m pytest backend/tests/test_studio_moments.py -v
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import studio_prompts as sp  # noqa: E402
import studio_runner as sr  # noqa: E402

_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "model": "test-model"}


def _sentence(idx, start, end, text="filler text here"):
    return {"sentence_idx": idx, "start_sec": start, "end_sec": end, "text": text}


class TestHardTimestampRequirement:
    def test_plain_text_paste_is_rejected_with_422(self):
        with pytest.raises(sr.InputRejected):
            sp._moments_run({"source": "paste", "transcript_text": "just plain text, no timing at all"}, "")

    def test_library_source_with_no_sentences_is_rejected(self):
        with pytest.raises(sr.InputRejected):
            sp._moments_run({"source": "library", "sentences": []}, "")


class TestLeadInExpansion:
    def test_start_time_expands_backward_for_setup(self):
        sentences = [
            _sentence(0, 0, 5, "setup line one"),
            _sentence(1, 5, 10, "setup line two"),
            _sentence(2, 10, 15, "the punchline"),
        ]
        moments = {"moments": [{
            "start_sentence_idx": 2, "end_sentence_idx": 2, "score": 9,
            "reason": "funny payoff", "suggested_title": "title", "type": "funny",
            "visual_dependent": False,
        }]}
        with patch("studio_runner.call_llm", return_value=(moments, _USAGE)):
            output, _u = sp._moments_run({"source": "library", "sentences": sentences}, "")

        # start_sentence_idx=2 is at t=10; LEAD_IN_SEC=15 pulls the start back to sentence 0 (t=0)
        assert output["moments"][0]["start"] == "00:00"
        assert output["moments"][0]["end"] == "00:15"


class TestHallucinatedIndicesDropped:
    def test_out_of_range_index_is_dropped_not_guessed(self):
        sentences = [_sentence(0, 0, 5)]
        moments = {"moments": [{
            "start_sentence_idx": 999, "end_sentence_idx": 999, "score": 5,
            "reason": "r", "suggested_title": "t", "type": "funny", "visual_dependent": False,
        }]}
        with patch("studio_runner.call_llm", return_value=(moments, _USAGE)):
            output, _u = sp._moments_run({"source": "library", "sentences": sentences}, "")
        assert output["moments"] == []

    def test_invalid_type_is_dropped(self):
        sentences = [_sentence(0, 0, 5)]
        moments = {"moments": [{
            "start_sentence_idx": 0, "end_sentence_idx": 0, "score": 5,
            "reason": "r", "suggested_title": "t", "type": "not_a_real_type", "visual_dependent": False,
        }]}
        with patch("studio_runner.call_llm", return_value=(moments, _USAGE)):
            output, _u = sp._moments_run({"source": "library", "sentences": sentences}, "")
        assert output["moments"] == []


class TestTypeDiversity:
    def test_all_same_type_is_capped_to_60_percent_of_the_original_batch(self):
        # With every moment the same type, there's no other type to diversify with — the
        # guardrail can only cap the dominant type's count, not invent variety that wasn't
        # in the model's output. cap = int(10 * 0.6) = 6.
        sentences = [_sentence(i, i * 5, i * 5 + 5) for i in range(10)]
        moments = {"moments": [
            {"start_sentence_idx": i, "end_sentence_idx": i, "score": 10 - i,
             "reason": "r", "suggested_title": "t", "type": "funny", "visual_dependent": False}
            for i in range(10)
        ]}
        with patch("studio_runner.call_llm", return_value=(moments, _USAGE)):
            output, _u = sp._moments_run({"source": "library", "sentences": sentences}, "")
        assert len(output["moments"]) == 6

    def test_mixed_batch_reduces_dominant_share(self):
        sentences = [_sentence(i, i * 5, i * 5 + 5) for i in range(10)]
        types_in = ["funny"] * 8 + ["insight", "story"]
        moments = {"moments": [
            {"start_sentence_idx": i, "end_sentence_idx": i, "score": 10 - i,
             "reason": "r", "suggested_title": "t", "type": types_in[i], "visual_dependent": False}
            for i in range(10)
        ]}
        with patch("studio_runner.call_llm", return_value=(moments, _USAGE)):
            output, _u = sp._moments_run({"source": "library", "sentences": sentences}, "")

        types = [m["type"] for m in output["moments"]]
        assert types.count("funny") <= 6  # capped from 8 down to the int(10*0.6) cap
        assert "insight" in types and "story" in types  # minority types survive uncapped

    def test_diverse_batch_is_untouched(self):
        types_in = ["funny", "insight", "reaction", "story", "hot_take"]
        sentences = [_sentence(i, i * 5, i * 5 + 5) for i in range(5)]
        moments = {"moments": [
            {"start_sentence_idx": i, "end_sentence_idx": i, "score": 5,
             "reason": "r", "suggested_title": "t", "type": types_in[i], "visual_dependent": False}
            for i in range(5)
        ]}
        with patch("studio_runner.call_llm", return_value=(moments, _USAGE)):
            output, _u = sp._moments_run({"source": "library", "sentences": sentences}, "")
        assert len(output["moments"]) == 5


class TestVisualDependentPassthrough:
    def test_visual_dependent_flag_is_preserved(self):
        sentences = [_sentence(0, 0, 5)]
        moments = {"moments": [{
            "start_sentence_idx": 0, "end_sentence_idx": 0, "score": 5,
            "reason": "a visual gag", "suggested_title": "t", "type": "funny", "visual_dependent": True,
        }]}
        with patch("studio_runner.call_llm", return_value=(moments, _USAGE)):
            output, _u = sp._moments_run({"source": "library", "sentences": sentences}, "")
        assert output["moments"][0]["visual_dependent"] is True
