"""
Tests for clip_scoring.py's five-signal composite ranking (ENGINE-PLAN.md Phase 2).

Run with: python -m pytest backend/tests/test_clip_scoring.py -v
"""
import os
import sys

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


def _no_reranker():
    return None


class TestSignalsAreBounded:
    def test_all_signals_in_zero_one_range(self):
        cand = _candidate(0, 3, 0.0, 20.0, quotable="a distinctive quote here")
        cand["_opening_text"] = "So here's the thing nobody tells you."
        result = cs.score_candidate(cand, "vid-x", {"thing": 2.0, "thing2": 1.5}, _no_reranker)
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
        result = cs.score_candidate(cand, "vid-x", {}, _no_reranker, taste_centroid=None)
        assert "taste_match" not in result["signals"]


class TestDeterministicOrdering:
    def test_repeated_ranking_produces_identical_order(self):
        sentences_by_idx = {i: _sentence(i, f"sentence {i} words here today", i * 3, (i + 1) * 3) for i in range(20)}
        candidates = [
            _candidate(0, 4, 0.0, 15.0, quotable="first quote text"),
            _candidate(5, 9, 15.0, 30.0, quotable="second quote text"),
            _candidate(10, 14, 30.0, 45.0, quotable="third quote text"),
        ]
        corpus = [s["text"] for s in sentences_by_idx.values()]

        order_1 = [c["start_sentence_idx"] for c in cs.rank(candidates, sentences_by_idx, "vid-x", corpus, _no_reranker, max_clips=6)]
        order_2 = [c["start_sentence_idx"] for c in cs.rank(candidates, sentences_by_idx, "vid-x", corpus, _no_reranker, max_clips=6)]
        assert order_1 == order_2

    def test_rank_respects_max_clips_truncation(self):
        sentences_by_idx = {i: _sentence(i, f"sentence {i} words here today", i * 3, (i + 1) * 3) for i in range(30)}
        candidates = [_candidate(i, i + 2, i * 3, (i + 3) * 3, quotable=f"quote {i}") for i in range(0, 24, 3)]
        corpus = [s["text"] for s in sentences_by_idx.values()]
        results = cs.rank(candidates, sentences_by_idx, "vid-x", corpus, _no_reranker, max_clips=3)
        assert len(results) == 3

    def test_rank_output_has_no_percentage_field(self):
        """No fabricated 'predicted engagement %' anywhere in the ranked output."""
        sentences_by_idx = {i: _sentence(i, f"sentence {i} words here today", i * 3, (i + 1) * 3) for i in range(10)}
        candidates = [_candidate(0, 4, 0.0, 15.0, quotable="a quote")]
        corpus = [s["text"] for s in sentences_by_idx.values()]
        results = cs.rank(candidates, sentences_by_idx, "vid-x", corpus, _no_reranker, max_clips=6)
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
