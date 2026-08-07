"""
Tests for clip_scoring.py's five-signal composite ranking (ENGINE-PLAN.md Phase 2).

Run with: python -m pytest backend/tests/test_clip_scoring.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import clip_scoring as cs  # noqa: E402


def _sentence(idx, text, start, end):
    return {"sentence_idx": idx, "text": text, "start_sec": start, "end_sec": end}


def _candidate(start_idx, end_idx, start_sec, end_sec, quotable="", beats=None, seed_beat=None):
    return {
        "start_sentence_idx": start_idx,
        "end_sentence_idx": end_idx,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "beats": beats or [],
        "seed_beat": seed_beat or {},
        "title": "t",
        "quotable_line": quotable,
    }


class TestSignalsAreBounded:
    def test_all_signals_in_zero_one_range(self):
        cand = _candidate(0, 3, 0.0, 20.0, quotable="a distinctive quote here")
        cand["_opening_text"] = "So here's the thing nobody tells you."
        result = cs.score_candidate(cand, "vid-x", {"thing": 2.0, "thing2": 1.5})
        for name, value in result["signals"].items():
            assert 0.0 <= value <= 1.0, f"{name} = {value} out of bounds"
        assert 0.0 <= result["composite"] <= 1.0

    def test_taste_match_absent_below_min_labels(self, tmp_path, monkeypatch):
        import paths
        monkeypatch.setattr(paths, "CLIP_FEEDBACK_FILE", str(tmp_path / "clip_feedback.json"))
        monkeypatch.setattr(paths, "CLIPS_FILE", str(tmp_path / "clips.json"))
        # No feedback file at all -> compute_taste_centroid must return None.
        centroid = cs.compute_taste_centroid()
        assert centroid is None

    def test_taste_match_signal_omitted_when_centroid_is_none(self):
        cand = _candidate(0, 3, 0.0, 20.0)
        cand["_opening_text"] = "opening text"
        result = cs.score_candidate(cand, "vid-x", {}, taste_centroid=None)
        assert "taste_match" not in result["signals"]

    def test_signal_details_carries_hook_cues_not_signals(self):
        # hook_strength's lexical-cue breakdown must NOT end up as extra keys in `signals` —
        # score_candidate's composite is `sum(signals[k] * weights[k] for k in signals)`, so
        # any key in `signals` without a matching WEIGHTS entry would KeyError there.
        cand = _candidate(0, 3, 0.0, 20.0, quotable="a distinctive quote here")
        cand["_opening_text"] = "Why has no one told me this before?"
        result = cs.score_candidate(cand, "vid-x", {"thing": 2.0})
        assert set(result["signals"].keys()) <= set(cs.WEIGHTS.keys())
        assert "hook_cues" in result["signal_details"]
        assert "question" in result["signal_details"]["hook_cues"]


class TestHookStrength:
    def test_hook_score_is_not_degenerate(self):
        # Direct regression guard on "hook_strength is always ~0" — the cross-encoder used to
        # score every real clip opening at 0.0001-0.0005 regardless of content.
        openings = [
            "Why has no one told me this before?",
            "Have you ever wondered why this happens?",
            "You won't believe what happened next.",
            "Here's the secret nobody tells you about this.",
            "The 5 mistakes everyone makes when starting out.",
            "This is a plain statement about something ordinary today.",
            "We continued the meeting after a short break.",
            "The weather was mild and nothing unusual occurred.",
            "Quarterly revenue increased by three percent this year.",
            "I want to talk about a topic that matters to me.",
            "So then I opened the file and started reading.",
            "It was a Tuesday afternoon like any other.",
            "The report covers the same material as last time.",
            "Let's move on to the next agenda item now.",
            "There is nothing special about this particular sentence.",
            "What's the one mistake that ruins everything?",
            "Never do this if you want to succeed.",
            "I used to think this was impossible until today.",
            "The document lists the standard configuration values.",
            "Most people get this completely wrong from the start.",
        ]
        scores = []
        for text in openings:
            cand = _candidate(0, 0, 0.0, 15.0)
            cand["_opening_text"] = text
            score, _cues = cs._hook_strength(cand)
            scores.append(score)
        assert max(scores) - min(scores) > 0.4, f"scores too narrow: {scores}"
        assert max(scores) > 0.5

    def test_question_opening_beats_flat_statement(self):
        question = _candidate(0, 0, 0.0, 15.0)
        question["_opening_text"] = "Why does this keep happening to me every single day?"
        flat = _candidate(0, 0, 0.0, 15.0)
        flat["_opening_text"] = "The meeting continued after the scheduled break today."
        q_score, _ = cs._hook_strength(question)
        f_score, _ = cs._hook_strength(flat)
        assert q_score > f_score

    def test_lexical_only_path_when_no_dense_model(self, monkeypatch):
        monkeypatch.setattr(cs, "_archetype_matrix", lambda: None)
        cand = _candidate(0, 0, 0.0, 15.0)
        cand["_opening_text"] = "Why has no one told me this crucial secret before?"
        score, cues = cs._hook_strength(cand)
        assert 0.0 <= score <= 1.0
        assert cues["_semantic"] == -1.0
        # Still spread, not the old constant 0.4/0.7 pair regardless of content.
        flat = _candidate(0, 0, 0.0, 15.0)
        flat["_opening_text"] = "The report covers the same material as last time."
        flat_score, _ = cs._hook_strength(flat)
        assert score != flat_score

    def test_missing_opening_text_returns_neutral(self):
        cand = _candidate(0, 0, 0.0, 15.0)
        score, cues = cs._hook_strength(cand)
        assert score == 0.5
        assert cues == {}

    def test_beat_bonus_applies_from_opening_beat_type(self):
        base = _candidate(0, 0, 0.0, 15.0)
        base["_opening_text"] = "This is a plain statement about something ordinary today."
        without_bonus, _ = cs._hook_strength(base)

        with_bonus_cand = dict(base)
        with_bonus_cand["opening_beat_type"] = "hook"
        with_bonus, _ = cs._hook_strength(with_bonus_cand)

        assert with_bonus >= without_bonus
        expected_delta = min(cs.HOOK_BEAT_BONUS, 1.0 - without_bonus)
        assert with_bonus - without_bonus == pytest.approx(expected_delta, abs=1e-6)

    def test_archetype_matrix_encoded_once_per_process(self, monkeypatch):
        import vector_store
        if not vector_store.HAS_DENSE_MODEL:
            pytest.skip("no dense embedding model available in this environment")

        monkeypatch.setattr(cs, "_ARCHETYPE_MATRIX", None)  # force a fresh encode
        original_encode = vector_store.EMBEDDING_MODEL.encode
        archetype_encode_calls = {"n": 0}

        def counting_encode(texts, **kwargs):
            if isinstance(texts, list) and list(texts) == list(cs.HOOK_ARCHETYPES):
                archetype_encode_calls["n"] += 1
            return original_encode(texts, **kwargs)

        monkeypatch.setattr(vector_store.EMBEDDING_MODEL, "encode", counting_encode)

        for i in range(5):
            cand = _candidate(i, i, float(i), float(i) + 5)
            cand["_opening_text"] = f"This is opening sentence number {i} with some words."
            cs._hook_strength(cand)

        assert archetype_encode_calls["n"] == 1


class TestCalibrationConstants:
    """Cheap guard against a bad edit to the measured constants — see the calibration note
    above clip_scoring.WEIGHTS for how these were actually derived (eval/hook_eval.py against
    backend/data/chunks.json), not asserting the exact values here since re-calibration is
    expected to change them; just that they stay internally consistent."""

    def test_hook_constants_are_ordered(self):
        assert cs.HOOK_RAW_FLOOR < cs.HOOK_RAW_CEIL
        assert 0.0 < cs.HOOK_LEX_ONLY_CEIL <= 1.0
        assert abs(cs.HOOK_SEM_WEIGHT + cs.HOOK_LEX_WEIGHT - 1.0) < 1e-9
        assert sum(cs.HOOK_CUE_WEIGHTS.values()) <= 1.5

    def test_quotability_constants_are_ordered(self):
        assert cs.QUOTABILITY_IDF_FLOOR < cs.QUOTABILITY_IDF_CEIL


class TestDeterministicOrdering:
    def test_repeated_ranking_produces_identical_order(self):
        sentences_by_idx = {i: _sentence(i, f"sentence {i} words here today", i * 3, (i + 1) * 3) for i in range(20)}
        candidates = [
            _candidate(0, 4, 0.0, 15.0, quotable="first quote text"),
            _candidate(5, 9, 15.0, 30.0, quotable="second quote text"),
            _candidate(10, 14, 30.0, 45.0, quotable="third quote text"),
        ]
        corpus = [s["text"] for s in sentences_by_idx.values()]

        order_1 = [c["start_sentence_idx"] for c in cs.rank(candidates, sentences_by_idx, "vid-x", corpus, max_clips=6)]
        order_2 = [c["start_sentence_idx"] for c in cs.rank(candidates, sentences_by_idx, "vid-x", corpus, max_clips=6)]
        assert order_1 == order_2

    def test_rank_respects_max_clips_truncation(self):
        sentences_by_idx = {i: _sentence(i, f"sentence {i} words here today", i * 3, (i + 1) * 3) for i in range(30)}
        candidates = [_candidate(i, i + 2, i * 3, (i + 3) * 3, quotable=f"quote {i}") for i in range(0, 24, 3)]
        corpus = [s["text"] for s in sentences_by_idx.values()]
        results = cs.rank(candidates, sentences_by_idx, "vid-x", corpus, max_clips=3)
        assert len(results) == 3

    def test_rank_output_has_no_percentage_field(self):
        """No fabricated 'predicted engagement %' anywhere in the ranked output."""
        sentences_by_idx = {i: _sentence(i, f"sentence {i} words here today", i * 3, (i + 1) * 3) for i in range(10)}
        candidates = [_candidate(0, 4, 0.0, 15.0, quotable="a quote")]
        corpus = [s["text"] for s in sentences_by_idx.values()]
        results = cs.rank(candidates, sentences_by_idx, "vid-x", corpus, max_clips=6)
        for r in results:
            for key in r:
                assert "percent" not in key.lower()
                assert "engagement" not in key.lower()


class TestFeedbackRecording:
    def test_record_feedback_increments_label_count(self, tmp_path, monkeypatch):
        import paths
        monkeypatch.setattr(paths, "CLIP_FEEDBACK_FILE", str(tmp_path / "clip_feedback.json"))
        monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
        count1 = cs.record_feedback("clip-1", "winner")
        count2 = cs.record_feedback("clip-2", "dud")
        assert count1 == 1
        assert count2 == 2
