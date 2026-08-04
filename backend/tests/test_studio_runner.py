"""
Tests for studio_runner.py's shared pipeline: word counting, source-verification, banned-word
stripping, windowing, plain-text pseudo-segmentation, and the run_tool/regenerate_block
orchestration (guardrails 9, 19, 20, 22, 24, 26 in creator-tools-integration-spec.md).

Run with: python -m pytest backend/tests/test_studio_runner.py -v
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import studio_runner as sr  # noqa: E402
import usage  # noqa: E402
import voice_profile  # noqa: E402


class TestSourceVerification:
    def test_exact_substring_matches(self):
        assert sr.appears_in_source("hello world", "well, hello world it is") is True

    def test_whitespace_and_case_insensitive(self):
        assert sr.appears_in_source("Hello   World", "some text hello world more text") is True

    def test_missing_claim_is_rejected(self):
        assert sr.appears_in_source("invented statistic", "totally unrelated source text") is False

    def test_empty_candidate_is_rejected(self):
        assert sr.appears_in_source("", "any source") is False


class TestBannedWords:
    def test_strip_removes_phrase_case_insensitively(self):
        cleaned, found = sr.strip_banned_words("Let's delve into this DELVE topic", ["delve"])
        assert "delve" not in cleaned.lower()
        assert found == ["delve"]  # one phrase in the banned list -> one entry, even with 2 occurrences

    def test_strip_with_no_matches(self):
        cleaned, found = sr.strip_banned_words("A clean sentence.", ["delve", "unlock"])
        assert cleaned == "A clean sentence."
        assert found == []

    def test_enforce_banned_words_walks_nested_structure(self):
        output = {"linkedin": {"hook": "Let's delve in", "body": "clean"}, "notes": ["delve here too"]}
        cleaned, found = sr.enforce_banned_words(output, ["delve"])
        assert "delve" not in cleaned["linkedin"]["hook"].lower()
        assert "delve" not in cleaned["notes"][0].lower()
        assert cleaned["linkedin"]["body"] == "clean"
        assert set(found) == {"delve"}

    def test_enforce_banned_words_preserves_none_values(self):
        output = {"replies": [{"suggested_reply": None}]}
        cleaned, found = sr.enforce_banned_words(output, ["delve"])
        assert cleaned["replies"][0]["suggested_reply"] is None
        assert found == []

    def test_no_banned_words_configured_is_a_noop(self):
        output = {"a": "text"}
        cleaned, found = sr.enforce_banned_words(output, [])
        assert cleaned == output
        assert found == []


class TestFormatting:
    def test_format_timestamp_under_an_hour(self):
        assert sr.format_timestamp(125) == "02:05"

    def test_format_timestamp_over_an_hour(self):
        assert sr.format_timestamp(3665) == "01:01:05"

    def test_format_timestamp_none_stays_none(self):
        assert sr.format_timestamp(None) is None

    def test_format_sentences_uses_bracketed_index(self):
        sentences = [{"sentence_idx": 3, "start_sec": 12, "text": "hello there"}]
        rendered = sr.format_sentences(sentences)
        assert "[3]" in rendered
        assert "hello there" in rendered


class TestWindowing:
    def test_short_input_is_a_single_window(self):
        sentences = [{"sentence_idx": i, "text": "short sentence here"} for i in range(10)]
        windows = sr.window_sentences(sentences)
        assert len(windows) == 1

    def test_long_input_is_split_with_overlap(self):
        sentences = [{"sentence_idx": i, "text": " ".join(["word"] * 100)} for i in range(120)]
        windows = sr.window_sentences(sentences, window_size=60, overlap=10)
        assert len(windows) > 1
        # consecutive windows overlap by `overlap` sentences
        assert windows[0][-10]["sentence_idx"] == windows[1][0]["sentence_idx"]


class TestPseudoSegmentation:
    def test_plain_text_chunks_by_word_count(self):
        text = " ".join(["word"] * 300)
        chunks = sr.pseudo_segment_plain_text(text, chunk_words=100)
        assert len(chunks) == 3
        assert all(c["start_sec"] is None for c in chunks)

    def test_duration_estimate_assigns_proportional_times(self):
        text = " ".join(["word"] * 200)
        chunks = sr.pseudo_segment_plain_text(text, chunk_words=100)
        estimated = sr.apply_duration_estimate(chunks, 100.0)
        assert estimated[0]["start_sec"] == 0.0
        assert estimated[1]["start_sec"] == 50.0
        assert estimated[-1]["end_sec"] == 100.0


class TestRunToolPipeline:
    def _stub_spec(self, run_fn, count_words=None):
        import studio_prompts

        spec = studio_prompts.ToolSpec(
            id="stub", label="Stub", description="test", needs_timestamps=False,
            count_words=count_words or (lambda inputs: sr.word_count(inputs.get("text", ""))),
            run_fn=run_fn,
        )
        return spec

    def test_run_tool_records_usage_and_history(self):
        import studio_prompts
        import tool_runs

        def fake_run(inputs, voice_block):
            return {"result": "ok"}, {"prompt_tokens": 10, "completion_tokens": 5, "model": "test-model"}

        spec = self._stub_spec(fake_run)
        with patch.object(studio_prompts, "get_tool", return_value=spec):
            output = sr.run_tool("stub", {"text": "hello"})

        assert output["result"] == "ok"
        assert "run_id" in output
        run = tool_runs.get(output["run_id"])
        assert run is not None
        assert run.tool_id == "stub"

        summary = usage.summary()
        assert summary["runs_today"] == 1

    def test_run_tool_rejects_oversized_input_before_any_llm_call(self):
        import studio_prompts

        called = {"count": 0}

        def fake_run(inputs, voice_block):
            called["count"] += 1
            return {}, {}

        spec = self._stub_spec(fake_run, count_words=lambda inputs: usage.MAX_INPUT_WORDS + 1)
        with patch.object(studio_prompts, "get_tool", return_value=spec):
            with pytest.raises(sr.InputRejected):
                sr.run_tool("stub", {"text": "doesn't matter"})
        assert called["count"] == 0

    def test_run_tool_applies_banned_word_backstop(self):
        import studio_prompts

        voice_profile.apply_edit({"banned_words": ["delve"]})

        def fake_run(inputs, voice_block):
            return {"body": "let's delve into this"}, {"prompt_tokens": 1, "completion_tokens": 1, "model": "m"}

        spec = self._stub_spec(fake_run)
        with patch.object(studio_prompts, "get_tool", return_value=spec):
            output = sr.run_tool("stub", {"text": "x"})

        assert "delve" not in output["body"].lower()
        assert "delve" in output["guardrail_notes"]["banned_words_removed"]

    def test_run_tool_unknown_tool_raises(self):
        import studio_prompts
        with patch.object(studio_prompts, "get_tool", return_value=None):
            with pytest.raises(sr.StudioError):
                sr.run_tool("nonexistent", {})


class TestRegenerateBlock:
    def test_regenerate_updates_only_the_requested_block(self):
        import studio_prompts
        import tool_runs

        def fake_run(inputs, voice_block):
            return {"linkedin": "v1", "x": "v1"}, {"prompt_tokens": 1, "completion_tokens": 1, "model": "m"}

        spec = studio_prompts.ToolSpec(
            id="stub2", label="Stub2", description="test", needs_timestamps=False,
            count_words=lambda inputs: 1, run_fn=fake_run,
        )
        with patch.object(studio_prompts, "get_tool", return_value=spec):
            output = sr.run_tool("stub2", {"text": "x"})
            run_id = output["run_id"]

            def fake_run_v2(inputs, voice_block):
                return {"linkedin": "v2", "x": "v2"}, {"prompt_tokens": 1, "completion_tokens": 1, "model": "m"}
            spec.run_fn = fake_run_v2

            updated = sr.regenerate_block(run_id, "linkedin")

        assert updated["linkedin"] == "v2"
        stored = tool_runs.get(run_id)
        assert stored.output["linkedin"] == "v2"

    def test_regenerate_unknown_run_raises(self):
        with pytest.raises(sr.StudioError):
            sr.regenerate_block("nonexistent-run-id", "linkedin")
