"""
Tests for topic_segmenter.py — divisive clustering over sentence embeddings.

Driven with synthetic vectors rather than the real embedding model: the objective is pure
linear algebra, and constructing vectors with a KNOWN topic structure is the only way to
assert the split lands where it should.

Run with: python -m pytest backend/tests/test_topic_segmenter.py -v
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import topic_segmenter as ts  # noqa: E402


def _unit(vec):
    vec = np.asarray(vec, dtype=np.float32)
    return vec / np.linalg.norm(vec)


def _topic_block(direction, count, jitter=0.02, seed=0):
    """`count` near-identical unit vectors pointing along `direction`."""
    rng = np.random.default_rng(seed)
    base = _unit(direction)
    rows = base + rng.standard_normal((count, base.size)).astype(np.float32) * jitter
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def _sentences(texts):
    return [
        {"sentence_idx": i, "text": t, "start_sec": i * 3, "end_sec": (i + 1) * 3}
        for i, t in enumerate(texts)
    ]


class TestSplitPoints:
    def test_finds_the_boundary_between_two_topics(self):
        vectors = np.vstack([
            _topic_block([1, 0, 0], 20, seed=1),
            _topic_block([0, 1, 0], 20, seed=2),
        ])
        cuts = ts.split_points(vectors)
        assert 20 in cuts

    def test_finds_multiple_boundaries(self):
        vectors = np.vstack([
            _topic_block([1, 0, 0], 15, seed=1),
            _topic_block([0, 1, 0], 15, seed=2),
            _topic_block([0, 0, 1], 15, seed=3),
        ])
        cuts = ts.split_points(vectors)
        assert 15 in cuts and 30 in cuts

    def test_single_topic_is_not_split(self):
        # The gain threshold is what handles "the number of segments is unknown" — a
        # transcript that never changes subject must produce no splits at all rather than
        # being forced into a preset count.
        vectors = _topic_block([1, 0, 0], 60, seed=4)
        assert ts.split_points(vectors) == []

    def test_respects_the_minimum_segment_size(self):
        vectors = np.vstack([
            _topic_block([1, 0, 0], 30, seed=1),
            _topic_block([0, 1, 0], 30, seed=2),
        ])
        cuts = ts.split_points(vectors, min_segment=12)
        bounds = [0] + cuts + [len(vectors)]
        assert all(b - a >= 12 for a, b in zip(bounds, bounds[1:]))

    def test_too_short_to_split(self):
        assert ts.split_points(_topic_block([1, 0, 0], 5, seed=1)) == []

    def test_cuts_are_sorted_and_unique(self):
        vectors = np.vstack([
            _topic_block([1, 0, 0], 12, seed=1),
            _topic_block([0, 1, 0], 12, seed=2),
            _topic_block([0, 0, 1], 12, seed=3),
            _topic_block([1, 1, 0], 12, seed=4),
        ])
        cuts = ts.split_points(vectors)
        assert cuts == sorted(set(cuts))

    def test_higher_threshold_yields_fewer_segments(self):
        vectors = np.vstack([
            _topic_block([1, 0, 0], 15, seed=1),
            _topic_block([0.9, 0.1, 0], 15, seed=2),  # only slightly different
            _topic_block([0, 1, 0], 15, seed=3),
        ])
        permissive = ts.split_points(vectors, min_relative_gain=0.001)
        strict = ts.split_points(vectors, min_relative_gain=0.2)
        assert len(strict) <= len(permissive)


class TestSegmentSentences:
    @staticmethod
    def _embed_by_marker(texts):
        """Embed on a topic marker in the text, so a test can state the intended structure."""
        axes = {"A": [1, 0, 0], "B": [0, 1, 0], "C": [0, 0, 1]}
        rng = np.random.default_rng(7)
        rows = []
        for t in texts:
            base = _unit(axes.get(t[0], [1, 1, 1]))
            rows.append(base + rng.standard_normal(3).astype(np.float32) * 0.02)
        rows = np.asarray(rows, dtype=np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)

    def test_groups_sentences_by_topic(self):
        texts = ["A sentence"] * 15 + ["B sentence"] * 15
        segments = ts.segment_sentences(_sentences(texts), self._embed_by_marker)
        assert len(segments) == 2
        assert [s["text"][0] for s in segments[0]] == ["A"] * 15
        assert [s["text"][0] for s in segments[1]] == ["B"] * 15

    def test_segments_cover_every_sentence_exactly_once(self):
        texts = ["A x"] * 12 + ["B x"] * 12 + ["C x"] * 12
        sentences = _sentences(texts)
        segments = ts.segment_sentences(sentences, self._embed_by_marker)
        seen = [s["sentence_idx"] for seg in segments for s in seg]
        assert seen == sorted(seen) == [s["sentence_idx"] for s in sentences]

    def test_short_transcript_returns_one_segment(self):
        segments = ts.segment_sentences(_sentences(["A x"] * 5), self._embed_by_marker)
        assert len(segments) == 1

    def test_empty_input(self):
        assert ts.segment_sentences([], self._embed_by_marker) == []

    def test_embedding_failure_degrades_to_one_segment(self):
        # Must never fail an analysis — the caller falls back to fixed windows.
        segments = ts.segment_sentences(_sentences(["A x"] * 30), lambda texts: None)
        assert len(segments) == 1

    def test_wrong_embedding_count_degrades_to_one_segment(self):
        segments = ts.segment_sentences(
            _sentences(["A x"] * 30), lambda texts: np.zeros((3, 4), dtype=np.float32))
        assert len(segments) == 1

    def test_input_is_sorted_by_sentence_index(self):
        shuffled = list(reversed(_sentences(["A x"] * 12 + ["B x"] * 12)))
        segments = ts.segment_sentences(shuffled, self._embed_by_marker)
        flat = [s["sentence_idx"] for seg in segments for s in seg]
        assert flat == sorted(flat)


class TestSummariseSegment:
    def test_uses_verbatim_opening_text(self):
        seg = _sentences(["The first hire was a disaster.", "He lasted six weeks."])
        assert ts.summarise_segment(seg).startswith("The first hire was a disaster.")

    def test_truncates_long_segments(self):
        seg = _sentences(["word " * 200])
        out = ts.summarise_segment(seg, max_chars=60)
        assert len(out) <= 60
        assert out.endswith("…")

    def test_empty_segment(self):
        assert ts.summarise_segment([]) == ""
