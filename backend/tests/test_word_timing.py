"""
Tests for word_timing.py's snap_to_words / silence_gap helpers (ENGINE-PLAN.md Phase 1).
The redirect_data autouse fixture in conftest.py already points paths.WORDS_DIR at a tmp_path
for every test here.

Run with: python -m pytest backend/tests/test_word_timing.py -v
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paths  # noqa: E402
import word_timing as wt  # noqa: E402


def _write_words(video_id: str, words):
    os.makedirs(paths.WORDS_DIR, exist_ok=True)
    with open(os.path.join(paths.WORDS_DIR, f"{video_id}.json"), 'w', encoding='utf-8') as f:
        json.dump(words, f)


SAMPLE_WORDS = [
    {"word": "So", "start": 10.0, "end": 10.3},
    {"word": "I", "start": 10.4, "end": 10.5},
    {"word": "walked", "start": 10.6, "end": 11.0},
    {"word": "in.", "start": 11.1, "end": 11.4},
    {"word": "Then", "start": 12.0, "end": 12.3},
    {"word": "it", "start": 12.4, "end": 12.5},
    {"word": "happened.", "start": 12.6, "end": 13.2},
]


class TestSnapToWords:
    def test_snaps_to_nearest_word_boundaries_with_lead_in_and_tail(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # Requested window [10.2, 11.3] should snap start to word "So" (10.0) and end to
        # "in." (11.4), then apply lead-in/tail.
        start, end = wt.snap_to_words("vid-1", 10.2, 11.3, lead_in=0.12, tail=0.25)
        assert start == 10.0 - 0.12
        assert end == 11.4 + 0.25

    def test_exact_boundary_input_stays_stable(self):
        _write_words("vid-1", SAMPLE_WORDS)
        start, end = wt.snap_to_words("vid-1", 10.0, 13.2, lead_in=0.0, tail=0.0)
        assert start == 10.0
        assert end == 13.2

    def test_missing_words_file_falls_back_to_input_unchanged(self):
        # No words file written for this video_id.
        start, end = wt.snap_to_words("vid-does-not-exist", 5.0, 9.0)
        assert (start, end) == (5.0, 9.0)

    def test_never_crosses_into_adjacent_word_beyond_requested_range(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # Request tightly inside the first clause only.
        start, end = wt.snap_to_words("vid-1", 10.05, 10.35, lead_in=0.0, tail=0.0)
        assert start == 10.0   # "So"
        assert end == 10.3     # "So"'s end, not "I"'s


class TestSilenceGaps:
    def test_silence_gap_before_and_after(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # Gap between "in." (ends 11.4) and "Then" (starts 12.0) = 0.6s
        assert abs(wt.silence_gap_after("vid-1", 11.4) - 0.6) < 1e-9
        assert abs(wt.silence_gap_before("vid-1", 12.0) - 0.6) < 1e-9

    def test_silence_gap_missing_words_file_is_zero(self):
        assert wt.silence_gap_before("vid-none", 5.0) == 0.0
        assert wt.silence_gap_after("vid-none", 5.0) == 0.0


class TestEnsureWordsCaching:
    def test_ensure_words_returns_cached_without_retranscribing(self):
        _write_words("vid-cached", SAMPLE_WORDS)
        calls = {"count": 0}

        def report(stage, progress, message):
            calls["count"] += 1

        result = wt.ensure_words("vid-cached", media_path="/nonexistent/path.mp4", report=report)
        assert result == SAMPLE_WORDS
        # Should report exactly one "using cached" call, never touch Whisper.
        assert calls["count"] == 1
