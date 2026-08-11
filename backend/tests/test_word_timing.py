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
        start, end, info = wt.snap_to_words("vid-1", 10.2, 11.3, lead_in=0.12, tail=0.25)
        assert start == 10.0 - 0.12
        assert end == 11.4 + 0.25
        assert info["snapped"] is True
        assert info["start_moved_by"] < 0        # in-point pulled earlier onto "So"
        assert info["end_moved_by"] > 0          # out-point pushed later onto "in."
        assert info["reason"] == "snapped to nearest word start; snapped to nearest word end"

    def test_exact_boundary_input_stays_stable(self):
        _write_words("vid-1", SAMPLE_WORDS)
        start, end, info = wt.snap_to_words("vid-1", 10.0, 13.2, lead_in=0.0, tail=0.0)
        assert start == 10.0
        assert end == 13.2
        # Both edges were searched and matched; they simply had nowhere to move.
        assert info["snapped"] is False
        assert "snapped to nearest word start" in info["reason"]

    def test_missing_words_file_falls_back_to_input_unchanged(self):
        # No words file written for this video_id.
        start, end, info = wt.snap_to_words("vid-does-not-exist", 5.0, 9.0)
        assert (start, end) == (5.0, 9.0)
        assert info["snapped"] is False
        assert info["reason"] == "no word timing for this video"

    def test_picks_the_nearest_edge_of_the_enclosing_word(self):
        # Previously named test_never_crosses_into_adjacent_word_beyond_requested_range, which
        # asserted no range bound at all — the bound is covered by the window tests below.
        # What this actually pins is edge selection: within one clause, each boundary lands on
        # the enclosing word's own start/end rather than a neighbour's.
        _write_words("vid-1", SAMPLE_WORDS)
        # Request tightly inside the first clause only.
        start, end, _info = wt.snap_to_words("vid-1", 10.05, 10.35, lead_in=0.0, tail=0.0)
        assert start == 10.0   # "So"
        assert end == 10.3     # "So"'s end, not "I"'s

    def test_refuses_to_drag_a_boundary_across_a_long_silence(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # A handle dropped at 3.0s — 7 seconds of silence before any speech. The nearest word
        # edge is at 10.0, far outside the window, so the in-point must be left alone rather
        # than yanked across the gap. The out-point is in range and still snaps.
        start, end, info = wt.snap_to_words("vid-1", 3.0, 13.1, lead_in=0.12, tail=0.25)
        assert start == 3.0
        assert end == 13.2 + 0.25
        # The refusal is reported per-edge, so the client can explain the untouched in-point
        # while the out-point legitimately moved.
        assert info["snapped"] is True
        assert info["start_moved_by"] == 0.0
        assert info["reason"] == "no word start within snap window; snapped to nearest word end"

    def test_both_edges_in_silence_leave_the_range_untouched(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # Entirely inside the dead air after the last word (ends 13.2): nothing to snap to.
        start, end, info = wt.snap_to_words("vid-1", 30.0, 35.0)
        assert (start, end) == (30.0, 35.0)
        assert info["snapped"] is False
        assert info["reason"] == (
            "no word start within snap window; no word end within snap window"
        )

    def test_out_point_in_silence_keeps_its_place_while_start_snaps(self):
        _write_words("vid-1", SAMPLE_WORDS)
        start, end, info = wt.snap_to_words("vid-1", 10.2, 40.0, lead_in=0.12, tail=0.25)
        assert start == 10.0 - 0.12   # in-point still snaps to "So"
        assert end == 40.0            # out-point left where the user put it, no tail applied
        assert info["end_moved_by"] == 0.0
        assert info["reason"] == "snapped to nearest word start; no word end within snap window"

    def test_window_is_configurable(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # 3.0 is 7s from the onset at 10.0: outside the default window, inside a widened one.
        assert wt.snap_to_words("vid-1", 3.0, 13.2, lead_in=0.0, tail=0.0)[0] == 3.0
        widened = wt.snap_to_words("vid-1", 3.0, 13.2, lead_in=0.0, tail=0.0, window=8.0)
        assert widened[0] == 10.0

    def test_window_limit_separates_just_inside_from_just_outside(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # Onset at 10.0. A request 1.1s earlier is inside the 1.2s window; 1.5s earlier is not.
        inside = wt.snap_to_words("vid-1", 8.9, 13.2, lead_in=0.0, tail=0.0)[0]
        outside = wt.snap_to_words("vid-1", 8.5, 13.2, lead_in=0.0, tail=0.0)[0]
        assert inside == 10.0
        assert outside == 8.5


class TestSilenceGaps:
    def test_silence_gap_before_and_after(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # Gap between "in." (ends 11.4) and "Then" (starts 12.0) = 0.6s
        assert abs(wt.silence_gap_after("vid-1", 11.4) - 0.6) < 1e-9
        assert abs(wt.silence_gap_before("vid-1", 12.0) - 0.6) < 1e-9

    def test_silence_gap_missing_words_file_is_zero(self):
        assert wt.silence_gap_before("vid-none", 5.0) == 0.0
        assert wt.silence_gap_after("vid-none", 5.0) == 0.0


class TestSnapClipBounds:
    """Candidate boundaries arrive quantised to whole seconds (multimodal_engine.py:362
    stores math.floor/math.ceil), so these tests use integer inputs like the real pipeline."""

    def test_removes_leading_dead_air_from_floored_start(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # floor() put the in-point at 10.0 while speech starts at 10.0 exactly; use a
        # candidate floored to 9 to represent the up-to-1s of dead air the real corpus has.
        start, end, info = wt.snap_clip_bounds("vid-1", 9.0, 14.0, lead_in=0.12, tail=0.25)
        assert start == 10.0 - 0.12       # onset of "So", minus lead-in
        assert info["snapped"] is True
        assert info["start_moved_by"] > 0.8

    def test_lead_in_never_bleeds_the_previous_word(self):
        # "prev" ends at 9.98, only 0.02s before the clip's first word at 10.0 — the 0.12
        # lead-in must be suppressed rather than open on the tail of a foreign word.
        words = [{"word": "prev", "start": 9.5, "end": 9.98}] + SAMPLE_WORDS
        _write_words("vid-2", words)
        start, _end, _info = wt.snap_clip_bounds("vid-2", 9.99, 14.0, lead_in=0.12, tail=0.25)
        assert start == 10.0              # clamped to onset, no lead-in applied
        assert start > 9.98               # provably past the previous word's end

    def test_tail_is_clamped_short_of_the_next_word(self):
        # "next" starts at 13.35, far enough that the 0.06 margin fits: the 0.25 tail would
        # reach 13.45 and must be pulled back to 13.29 instead.
        words = SAMPLE_WORDS + [{"word": "next", "start": 13.35, "end": 13.9}]
        _write_words("vid-3", words)
        _start, end, _info = wt.snap_clip_bounds("vid-3", 10.0, 13.34, lead_in=0.12, tail=0.25)
        assert end == 13.35 - wt.ADJACENT_MARGIN_SEC
        assert end >= 13.2                # still contains the whole final word

    def test_final_word_integrity_wins_over_the_adjacent_margin(self):
        # "next" starts 0.05s after "happened." ends — closer than ADJACENT_MARGIN_SEC, so
        # the margin CANNOT be honoured without truncating the clip's own last word.
        # Keeping the word whole is the correct precedence; the cut still lands before "next".
        words = SAMPLE_WORDS + [{"word": "next", "start": 13.25, "end": 13.9}]
        _write_words("vid-5", words)
        _start, end, _info = wt.snap_clip_bounds("vid-5", 10.0, 13.24, lead_in=0.12, tail=0.25)
        assert end == 13.2                # exactly the final word's offset, no tail
        assert end < 13.25                # never reaches the next word's onset

    def test_out_point_never_extends_past_the_requested_bound(self):
        # ceil() only ever moves the out-point later, so a snap may pull it in but must never
        # push it out. "next" ends at 13.9, inside the 1.2s window below — without the cap it
        # would be chosen as the offset and the clip would swallow a word it never claimed.
        words = SAMPLE_WORDS + [{"word": "next", "start": 13.25, "end": 13.9}]
        _write_words("vid-3", words)
        _start, end, _info = wt.snap_clip_bounds("vid-3", 10.0, 14.0, lead_in=0.12, tail=0.25)
        assert end <= 14.0

    def test_trailing_dead_air_is_trimmed_from_ceiled_end(self):
        _write_words("vid-1", SAMPLE_WORDS)
        start, end, info = wt.snap_clip_bounds("vid-1", 10.0, 14.0, lead_in=0.0, tail=0.25)
        assert start == 10.0
        assert end == 13.2 + 0.25         # last word's offset plus tail, not the ceiled 14.0
        assert info["end_moved_by"] < 0

    def test_refuses_to_move_beyond_the_search_window(self):
        _write_words("vid-1", SAMPLE_WORDS)
        # In-point 5s before any speech: the onset at 10.0 is outside the 1.2s window, so the
        # boundary must be left alone rather than dragged across the silence.
        start, _end, info = wt.snap_clip_bounds("vid-1", 5.0, 13.2, window=1.2)
        assert start == 5.0
        assert "no word onset within snap window" in info["reason"]

    def test_missing_words_file_leaves_bounds_unchanged(self):
        start, end, info = wt.snap_clip_bounds("vid-does-not-exist", 5.0, 9.0)
        assert (start, end) == (5.0, 9.0)
        assert info["snapped"] is False
        assert info["reason"] == "no word timing for this video"

    def test_degenerate_window_is_rejected(self):
        _write_words("vid-1", SAMPLE_WORDS)
        start, end, info = wt.snap_clip_bounds("vid-1", 12.0, 12.0)
        assert (start, end) == (12.0, 12.0)
        assert info["snapped"] is False

    def test_snap_never_collapses_a_clip(self):
        # A window containing exactly one short word: snapping must not produce something
        # shorter than 0.5s, it must decline instead.
        _write_words("vid-4", [{"word": "hi", "start": 20.0, "end": 20.2}])
        start, end, info = wt.snap_clip_bounds("vid-4", 20.0, 20.3, lead_in=0.0, tail=0.0)
        assert (start, end) == (20.0, 20.3)
        assert info["snapped"] is False
        assert "collapse" in info["reason"]


class TestWordsCache:
    def test_rewriting_words_file_invalidates_cache(self):
        _write_words("vid-cache", SAMPLE_WORDS)
        assert len(wt.load_words("vid-cache")) == len(SAMPLE_WORDS)

        # Rewrite with different content; mtime-keyed cache must not serve the stale list.
        replacement = [{"word": "new", "start": 1.0, "end": 1.5}]
        os.utime(
            os.path.join(paths.WORDS_DIR, "vid-cache.json"),
            (0, 0),
        )
        _write_words("vid-cache", replacement)
        assert wt.load_words("vid-cache") == replacement

    def test_deleted_words_file_returns_none(self):
        _write_words("vid-gone", SAMPLE_WORDS)
        assert wt.load_words("vid-gone") is not None
        os.remove(os.path.join(paths.WORDS_DIR, "vid-gone.json"))
        assert wt.load_words("vid-gone") is None


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
