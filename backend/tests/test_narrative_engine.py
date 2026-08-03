"""
Tests for narrative_engine.py's constraint solver — the core claim of ENGINE-PLAN.md
Phase 2: given a beat that declares requires_setup_from_idx, no emitted clip candidate may
start after that index. This is the regression guard on "cannot cut between a setup and its
punchline by construction."

Run with: python -m pytest backend/tests/test_narrative_engine.py -v
"""
import os
import sys

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
