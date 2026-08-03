"""
Tests for caption_render.py's cue grouping and PNG frame emission (ENGINE-PLAN.md Phase 4).

Run with: python -m pytest backend/tests/test_caption_render.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import caption_render as cr  # noqa: E402


WORDS = [
    {"word": "So", "start": 0.0, "end": 0.3},
    {"word": "I", "start": 0.3, "end": 0.4},
    {"word": "walked", "start": 0.4, "end": 0.8},
    {"word": "in", "start": 0.8, "end": 1.0},
    {"word": "and", "start": 1.0, "end": 1.2},
    {"word": "sat", "start": 1.2, "end": 1.5},
    {"word": "down.", "start": 1.5, "end": 1.9},
]


class TestBuildCues:
    def test_groups_respect_max_words_per_cue(self):
        cues = cr.build_cues(WORDS, max_words_per_cue=4)
        assert len(cues) == 2  # 7 words / 4 per cue -> ceil(7/4) = 2
        assert len(cues[0].words) == 4
        assert len(cues[1].words) == 3

    def test_cue_spans_first_to_last_word(self):
        cues = cr.build_cues(WORDS, max_words_per_cue=4)
        assert cues[0].start == WORDS[0]["start"]
        assert cues[0].end == WORDS[3]["end"]

    def test_upper_case_applied(self):
        cues = cr.build_cues(WORDS, max_words_per_cue=4, case="upper")
        assert cues[0].words[0]["text"] == "SO"

    def test_empty_words_yields_no_cues(self):
        assert cr.build_cues([], max_words_per_cue=4) == []


class TestActiveWordIndex:
    def test_active_word_tracks_current_time(self):
        cues = cr.build_cues(WORDS, max_words_per_cue=7)
        cue = cues[0]
        assert cr._active_word_index(cue, 0.1) == 0   # "So"
        assert cr._active_word_index(cue, 0.5) == 2    # "walked"
        assert cr._active_word_index(cue, 1.6) == 6    # "down."


class TestRenderCuePngsFrameCount:
    def test_png_count_matches_duration_and_fps(self, tmp_path):
        cues = cr.build_cues(WORDS, max_words_per_cue=4)
        brand_kit = {
            "fonts": {"caption": "Inter"},
            "colors": {"text": "#ffffff", "accent": "#ff7a17", "stroke": "#000000"},
            "caption": {"position": "bottom-center", "max_words_per_cue": 4},
            "safe_margins": {"top": 0.12, "bottom": 0.18},
        }
        out_dir = str(tmp_path / "frames")
        result_dir = cr.render_cue_pngs(
            clip_id="test-clip", cues=cues, brand_kit=brand_kit,
            size=(1080, 1920), duration_sec=2.0, fps=12, out_dir=out_dir,
        )
        files = sorted(f for f in os.listdir(result_dir) if f.endswith(".png"))
        assert len(files) == int(2.0 * 12)  # 24 frames

    def test_zero_cues_still_renders_blank_frames_without_crashing(self, tmp_path):
        """Regression: a clip with no detected speech (e.g. no words transcribed) has zero
        cues. The initial 'not yet rendered' sentinel used to collide with the legitimate
        'no active cue' state (both None), so the first frame's bytes were never populated
        and writing them crashed with TypeError. Verified via an end-to-end render test."""
        brand_kit = {
            "fonts": {"caption": "Inter"},
            "colors": {"text": "#ffffff", "accent": "#ff7a17", "stroke": "#000000"},
            "caption": {"position": "bottom-center", "max_words_per_cue": 4},
            "safe_margins": {"top": 0.12, "bottom": 0.18},
        }
        out_dir = str(tmp_path / "frames_empty")
        result_dir = cr.render_cue_pngs(
            clip_id="test-clip-empty", cues=[], brand_kit=brand_kit,
            size=(1080, 1920), duration_sec=1.0, fps=12, out_dir=out_dir,
        )
        files = sorted(f for f in os.listdir(result_dir) if f.endswith(".png"))
        assert len(files) == 12
        # Every frame must be a valid, fully-written PNG (non-empty bytes).
        for fname in files:
            assert os.path.getsize(os.path.join(result_dir, fname)) > 0

    def test_state_changes_produce_distinct_frame_bytes(self, tmp_path):
        cues = cr.build_cues(WORDS, max_words_per_cue=7)
        brand_kit = {
            "fonts": {"caption": "Inter"},
            "colors": {"text": "#ffffff", "accent": "#ff7a17", "stroke": "#000000"},
            "caption": {"position": "bottom-center", "max_words_per_cue": 7},
            "safe_margins": {"top": 0.12, "bottom": 0.18},
        }
        out_dir = str(tmp_path / "frames2")
        result_dir = cr.render_cue_pngs(
            clip_id="test-clip-2", cues=cues, brand_kit=brand_kit,
            size=(1080, 1920), duration_sec=1.9, fps=12, out_dir=out_dir,
        )
        files = sorted(os.listdir(result_dir))
        first_bytes = open(os.path.join(result_dir, files[0]), 'rb').read()
        later_bytes = open(os.path.join(result_dir, files[-1]), 'rb').read()
        assert first_bytes != later_bytes  # different active word -> different pixels
