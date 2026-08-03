"""
Tests for clip_renderer.py's preset validation and word-time clipping (ENGINE-PLAN.md
Phase 4). The actual ffmpeg subprocess call is mocked here — an end-to-end smoke test with
real ffmpeg was run manually against a synthetic test source and confirmed both aspect
ratio and duration are exact; that's not re-run on every test invocation since it needs a
real ffmpeg binary and takes several seconds per preset.

Run with: python -m pytest backend/tests/test_clip_renderer.py -v
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import clip_renderer as cr  # noqa: E402


class TestPresetValidation:
    def test_unknown_preset_raises_before_touching_ffmpeg(self):
        with patch("clip_renderer._run_ffmpeg") as mock_ffmpeg:
            with pytest.raises(ValueError):
                cr.render_clip(
                    clip_id="c1", source_path="fake.mp4", start_sec=0.0, end_sec=10.0,
                    words=[], brand_kit={}, presets=["not-a-real-preset"],
                )
            mock_ffmpeg.assert_not_called()

    def test_invalid_time_range_raises(self):
        with pytest.raises(ValueError):
            cr.render_clip(
                clip_id="c1", source_path="fake.mp4", start_sec=10.0, end_sec=5.0,
                words=[], brand_kit={}, presets=["tiktok"],
            )


class TestClipRelativeWords:
    def test_words_outside_range_are_excluded(self):
        words = [
            {"word": "before", "start": 0.0, "end": 1.0},
            {"word": "inside", "start": 5.0, "end": 6.0},
            {"word": "after", "start": 20.0, "end": 21.0},
        ]
        result = cr._clip_relative_words(words, start_sec=4.0, end_sec=10.0)
        assert len(result) == 1
        assert result[0]["word"] == "inside"

    def test_word_times_are_shifted_relative_to_clip_start(self):
        words = [{"word": "hello", "start": 12.0, "end": 12.5}]
        result = cr._clip_relative_words(words, start_sec=10.0, end_sec=20.0)
        assert result[0]["start"] == 2.0
        assert result[0]["end"] == 2.5


class TestPresetsShape:
    def test_all_presets_have_required_dims(self):
        for name, preset in cr.PRESETS.items():
            assert "width" in preset and "height" in preset
            assert preset["width"] > 0 and preset["height"] > 0

    def test_vertical_presets_are_9x16(self):
        for name in ("tiktok", "shorts"):
            p = cr.PRESETS[name]
            assert p["width"] / p["height"] == pytest.approx(9 / 16, rel=0.01)
