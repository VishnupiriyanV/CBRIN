"""
Tests for narrative_engine.py's constraint solver — the core claim of ENGINE-PLAN.md
Phase 2: given a beat that declares requires_setup_from_idx, no emitted clip candidate may
start after that index. This is the regression guard on "cannot cut between a setup and its
punchline by construction."

Run with: python -m pytest backend/tests/test_narrative_engine.py -v
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import narrative_engine as ne  # noqa: E402


def _sentence(idx, text, start, end):
    return {"sentence_idx": idx, "text": text, "start_sec": start, "end_sec": end}


def _sentences(n, sec_per_sentence=3):
    return [
        _sentence(i, f"This is sentence number {i} with some words in it.", i * sec_per_sentence, (i + 1) * sec_per_sentence)
        for i in range(n)
    ]


def _beat(beat_type, start, end, requires=None, **kw):
    b = {
        "beat_type": beat_type,
        "start_sentence_idx": start,
        "end_sentence_idx": end,
        "requires_setup_from_idx": requires,
        "title": kw.get("title", "t"),
        "why_it_lands": "",
        "emotional_arc": {},
        "self_contained": requires is None,
        "quotable_line": kw.get("quotable_line", ""),
    }
    return b


class TestDependencyConstraintIsHard:
    def test_candidate_never_starts_after_required_setup_index(self):
        sentences = _sentences(10)
        beats = [
            _beat("setup", 3, 4, requires=None),
            _beat("punchline", 7, 7, requires=3, title="The punchline"),
        ]
        candidates = ne.beats_to_candidates(sentences, beats)
        assert len(candidates) == 1
        assert candidates[0]["start_sentence_idx"] <= 3

    def test_transitive_dependency_chain_is_followed(self):
        sentences = _sentences(20, sec_per_sentence=2)
        beats = [
            _beat("setup", 1, 1, requires=None),
            _beat("setup", 5, 5, requires=1),
            _beat("punchline", 10, 10, requires=5),
        ]
        candidates = ne.beats_to_candidates(sentences, beats)
        assert len(candidates) == 1
        # Must reach all the way back to sentence 1, not just the direct requirement (5).
        assert candidates[0]["start_sentence_idx"] <= 1

    def test_cycle_guard_does_not_infinite_loop(self):
        sentences = _sentences(10, sec_per_sentence=3)
        # Pathological: two beats point at each other's ranges.
        beats = [
            _beat("setup", 0, 2, requires=5),
            _beat("punchline", 5, 6, requires=1),
        ]
        # Should return without hanging.
        candidates = ne.beats_to_candidates(sentences, beats)
        assert isinstance(candidates, list)


class TestDurationBounds:
    def test_too_short_candidate_is_rejected(self):
        sentences = _sentences(5, sec_per_sentence=1)  # whole transcript is 5s
        beats = [_beat("punchline", 2, 2, requires=None)]
        candidates = ne.beats_to_candidates(sentences, beats)
        # 1 sentence at 1s each is far under MIN_CLIP_SEC=12
        assert candidates == []

    def test_within_bounds_candidate_is_kept(self):
        sentences = _sentences(10, sec_per_sentence=3)  # 3s/sentence -> 30s total
        beats = [_beat("punchline", 0, 9, requires=None)]
        candidates = ne.beats_to_candidates(sentences, beats)
        assert len(candidates) == 1
        assert ne.MIN_CLIP_SEC <= (candidates[0]["end_sec"] - candidates[0]["start_sec"]) <= ne.MAX_CLIP_SEC

    def test_overlong_candidate_drops_deep_requirement_but_keeps_direct_one(self):
        # 40 sentences x 3s = 120s total, exceeds MAX_CLIP_SEC=75 if fully expanded to sentence 0.
        sentences = _sentences(40, sec_per_sentence=3)
        beats = [
            _beat("setup", 0, 0, requires=None),       # deep/transitive requirement
            _beat("setup", 20, 20, requires=0),         # direct requirement's own dependency
            _beat("punchline", 30, 30, requires=20),    # seed's direct requirement is idx 20
        ]
        candidates = ne.beats_to_candidates(sentences, beats)
        assert len(candidates) == 1
        cand = candidates[0]
        # Direct requirement (20) must still be honored even though the deep one (0) was dropped.
        assert cand["start_sentence_idx"] <= 20
        assert (cand["end_sec"] - cand["start_sec"]) <= ne.MAX_CLIP_SEC

    def test_candidate_dies_if_even_direct_requirement_cannot_fit(self):
        # Direct requirement is so far back that even the minimal (direct-only) window
        # blows past MAX_CLIP_SEC — must not be emitted at all.
        sentences = _sentences(60, sec_per_sentence=3)  # 180s total
        beats = [_beat("punchline", 59, 59, requires=0)]
        candidates = ne.beats_to_candidates(sentences, beats)
        assert candidates == []


class TestOpeningBeatType:
    def test_candidate_carries_opening_beat_type_preferring_hook(self):
        # The opening sentence (idx 0) is covered by BOTH a "setup" beat and a "hook" beat —
        # _covering_beat (used elsewhere for dependency resolution) returns whichever comes
        # first in list order, which is usually the setup. clip_scoring's beat_bonus needs
        # "hook" specifically, so _covering_beat_type must prefer it when both overlap.
        sentences = _sentences(10, sec_per_sentence=3)
        beats = [
            _beat("setup", 0, 1, requires=None),
            _beat("hook", 0, 0, requires=None),
            _beat("punchline", 7, 7, requires=0, title="The punchline"),
        ]
        candidates = ne.beats_to_candidates(sentences, beats)
        assert len(candidates) == 1
        assert candidates[0]["opening_beat_type"] == "hook"

    def test_opening_beat_type_falls_back_to_the_only_covering_beat(self):
        # No dedicated hook beat here — the opening sentence is only covered by the seed
        # (punchline) beat itself, so that's what opening_beat_type reports. Spans several
        # sentences (not a single one) so the candidate clears MIN_CLIP_SEC=12s.
        sentences = _sentences(10, sec_per_sentence=3)
        beats = [_beat("punchline", 2, 6, requires=None)]
        candidates = ne.beats_to_candidates(sentences, beats)
        assert len(candidates) == 1
        assert candidates[0]["opening_beat_type"] == "punchline"


class TestMerging:
    def test_overlapping_candidates_are_merged(self):
        sentences = _sentences(15, sec_per_sentence=3)
        beats = [
            _beat("punchline", 5, 8, requires=2),
            _beat("payoff", 6, 9, requires=2),  # heavily overlapping range
        ]
        candidates = ne.beats_to_candidates(sentences, beats)
        assert len(candidates) == 1


class TestHeuristicBeatsDegradedMode:
    def test_heuristic_beats_returns_something_for_plain_transcript(self):
        sentences = [
            _sentence(0, "Today I want to talk about something important.", 0, 3),
            _sentence(1, "What happened next surprised everyone.", 3, 6),
            _sentence(2, "But then I realized the truth.", 6, 9),
            _sentence(3, "It changed everything for me.", 9, 12),
        ]
        beats = ne.heuristic_beats(sentences)
        assert len(beats) > 0
        assert all(b["beat_type"] in ne.BEAT_TYPES for b in beats)

    def test_heuristic_beats_empty_transcript(self):
        assert ne.heuristic_beats([]) == []


class TestBeatSchemaObjectShape:
    def test_beat_schema_is_object_not_array(self):
        # _SYSTEM_PROMPT demands {"beats": [...]} — the schema used to declare
        # {"type": "array", ...}, which only worked because llm_client's unwrap heuristic
        # happened to fall through to "pick the longest list value" and guess right.
        assert ne._BEAT_SCHEMA["type"] == "object"
        assert "beats" in ne._BEAT_SCHEMA["required"]

    def test_extract_beats_for_window_reads_beats_key_directly(self):
        with patch.object(ne.llm_client, "complete_json_with_usage", return_value=(
            {"beats": [{
                "beat_type": "hook", "start_sentence_idx": 0, "end_sentence_idx": 0,
                "requires_setup_from_idx": None, "title": "t", "why_it_lands": "",
                "emotional_arc": {}, "self_contained": True, "quotable_line": "",
            }]},
            {"prompt_tokens": 1, "completion_tokens": 1, "model": "m"},
        )):
            beats, usage = ne._extract_beats_for_window([_sentence(0, "hello world", 0, 3)])
        assert len(beats) == 1
        assert beats[0]["beat_type"] == "hook"
        assert usage["model"] == "m"


class TestWindowedExtractionTolerance:
    def test_one_failed_window_does_not_discard_the_others(self, monkeypatch):
        # A single LLMUnavailable from one window used to discard every beat successfully
        # extracted from every OTHER window — 6 good windows + 1 bad one meant a full
        # heuristic fallback for the whole video. Force 3 tiny windows (2 sentences each) and
        # fail only the middle one.
        monkeypatch.setattr(ne, "WORD_COUNT_WINDOW_THRESHOLD", 0)
        monkeypatch.setattr(ne, "WINDOW_SENTENCE_COUNT", 2)
        monkeypatch.setattr(ne, "WINDOW_OVERLAP", 0)
        sentences = _sentences(6)  # -> 3 windows of 2 sentences: [0,1] [2,3] [4,5]

        call_count = {"n": 0}

        def fake_complete(system, user, schema, max_retries=1, temperature=0.2, max_tokens=None, for_tools=False):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise ne.llm_client.LLMUnavailable("simulated rate limit on window 2")
            start = 0 if call_count["n"] == 1 else 4
            return (
                {"beats": [{
                    "beat_type": "punchline", "start_sentence_idx": start, "end_sentence_idx": start + 1,
                    "requires_setup_from_idx": None, "title": "t", "why_it_lands": "",
                    "emotional_arc": {}, "self_contained": True, "quotable_line": "",
                }]},
                {"prompt_tokens": 10, "completion_tokens": 5, "model": "test-model"},
            )

        with patch.object(ne.llm_client, "complete_json_with_usage", side_effect=fake_complete):
            beats, report = ne.extract_beats_with_report(sentences)

        assert report["windows_total"] == 3
        assert report["windows_ok"] == 2
        assert report["windows_failed"] == 1
        assert len(report["errors"]) == 1
        start_indices = {b["start_sentence_idx"] for b in beats}
        assert start_indices == {0, 4}

    def test_all_windows_failing_raises_llm_unavailable(self, monkeypatch):
        monkeypatch.setattr(ne, "WORD_COUNT_WINDOW_THRESHOLD", 0)
        monkeypatch.setattr(ne, "WINDOW_SENTENCE_COUNT", 2)
        monkeypatch.setattr(ne, "WINDOW_OVERLAP", 0)
        sentences = _sentences(4)

        def always_fail(*a, **kw):
            raise ne.llm_client.LLMUnavailable("simulated total failure")

        with patch.object(ne.llm_client, "complete_json_with_usage", side_effect=always_fail):
            with pytest.raises(ne.llm_client.LLMUnavailable):
                ne.extract_beats_with_report(sentences)


class TestAnalyzeVideoHonestDegradation:
    """analyze_video's `degraded` flag used to be computed once from is_configured() before
    extraction even ran, and never updated when extract_beats threw (the exception was only
    print()'d) — so heuristic beats could be persisted with degraded=False. Proof this
    happened for real: backend/data/clips.json had 8 clips, all degraded=false, yet 6 carried
    titles ("Question and answer", "Turning point") that only heuristic_beats() produces."""

    def test_partial_window_failure_reports_llm_partial_with_honest_reason(self, monkeypatch):
        monkeypatch.setattr(ne, "WORD_COUNT_WINDOW_THRESHOLD", 0)
        monkeypatch.setattr(ne, "WINDOW_SENTENCE_COUNT", 2)
        monkeypatch.setattr(ne, "WINDOW_OVERLAP", 0)
        sentences = _sentences(4)  # -> 2 windows

        call_count = {"n": 0}

        def fake_complete(system, user, schema, max_retries=1, temperature=0.2, max_tokens=None, for_tools=False):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (
                    {"beats": [{
                        "beat_type": "punchline", "start_sentence_idx": 0, "end_sentence_idx": 1,
                        "requires_setup_from_idx": None, "title": "t", "why_it_lands": "",
                        "emotional_arc": {}, "self_contained": True, "quotable_line": "",
                    }]},
                    {"prompt_tokens": 5, "completion_tokens": 5, "model": "m"},
                )
            raise ne.llm_client.LLMUnavailable("simulated failure")

        with patch.object(ne.llm_client, "complete_json_with_usage", side_effect=fake_complete), \
             patch.object(ne.llm_client, "is_configured", return_value=True):
            result = ne.analyze_video(sentences)

        assert result["mode"] == "llm_partial"
        assert result["degraded"] is True
        assert result["degraded_reason"] is not None
        assert "1" in result["degraded_reason"]

    def test_all_windows_failing_falls_back_to_heuristic_and_says_so(self, monkeypatch):
        monkeypatch.setattr(ne, "WORD_COUNT_WINDOW_THRESHOLD", 0)
        monkeypatch.setattr(ne, "WINDOW_SENTENCE_COUNT", 2)
        monkeypatch.setattr(ne, "WINDOW_OVERLAP", 0)
        sentences = _sentences(4)

        def always_fail(*a, **kw):
            raise ne.llm_client.LLMUnavailable("simulated total failure")

        with patch.object(ne.llm_client, "complete_json_with_usage", side_effect=always_fail), \
             patch.object(ne.llm_client, "is_configured", return_value=True):
            result = ne.analyze_video(sentences)

        assert result["mode"] == "heuristic"
        assert result["degraded"] is True
        assert result["degraded_reason"] is not None
        assert "heuristic" in result["degraded_reason"].lower()
        # Beat titles are the retroactive discriminator: heuristic_beats() only ever emits
        # these three literals — any other title means an LLM wrote it.
        assert all(b["title"] in ("Opening line", "Question and answer", "Turning point") for b in result["beats"])

    def test_no_key_configured_is_heuristic_with_honest_reason(self, monkeypatch):
        sentences = _sentences(4)
        with patch.object(ne.llm_client, "is_configured", return_value=False):
            result = ne.analyze_video(sentences)
        assert result["mode"] == "heuristic"
        assert result["degraded"] is True
        assert "no llm key" in result["degraded_reason"].lower() or "not configured" in result["degraded_reason"].lower()


class TestBeatValidation:
    def test_hallucinated_sentence_index_is_dropped(self):
        sentences_by_idx = {0: _sentence(0, "hello world today", 0, 3)}
        beats = [
            {"beat_type": "punchline", "start_sentence_idx": 0, "end_sentence_idx": 99,
             "requires_setup_from_idx": None, "title": "", "why_it_lands": "",
             "emotional_arc": {}, "self_contained": True, "quotable_line": ""},
        ]
        cleaned = ne._validate_and_clean_beats(beats, sentences_by_idx)
        assert cleaned == []

    def test_invalid_beat_type_is_dropped(self):
        sentences_by_idx = {0: _sentence(0, "hello world today", 0, 3)}
        beats = [
            {"beat_type": "not_a_real_type", "start_sentence_idx": 0, "end_sentence_idx": 0,
             "requires_setup_from_idx": None, "title": "", "why_it_lands": "",
             "emotional_arc": {}, "self_contained": True, "quotable_line": ""},
        ]
        cleaned = ne._validate_and_clean_beats(beats, sentences_by_idx)
        assert cleaned == []

    def test_fabricated_quotable_line_is_stripped_not_kept(self):
        sentences_by_idx = {0: _sentence(0, "hello world today", 0, 3)}
        beats = [
            {"beat_type": "punchline", "start_sentence_idx": 0, "end_sentence_idx": 0,
             "requires_setup_from_idx": None, "title": "", "why_it_lands": "",
             "emotional_arc": {}, "self_contained": True,
             "quotable_line": "this sentence was never actually said"},
        ]
        cleaned = ne._validate_and_clean_beats(beats, sentences_by_idx)
        assert len(cleaned) == 1
        assert cleaned[0]["quotable_line"] == ""
