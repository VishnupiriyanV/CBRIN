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


class TestEncoderSelectionProbesBeforeCommitting:
    """`ffmpeg -encoders` reports what the BINARY was built with, not what the machine can
    do — and imageio-ffmpeg ships one build to every install. Proven on the dev box: the same
    ffmpeg lists h264_nvenc, h264_amf and h264_qsv, but h264_amf fails to encode.

    Selecting on presence alone therefore chose h264_nvenc everywhere, including machines with
    no NVIDIA GPU, where every render died with "ffmpeg failed (exit N)". _BEST_ENCODER_FLAGS
    is cached after the first call, so that was unrecoverable for the process lifetime — no
    renders at all, on hardware this local-first tool targets."""

    ALL_LISTED = "h264_nvenc h264_amf h264_qsv libx264"

    def _select(self, monkeypatch, works):
        monkeypatch.setattr(cr, "_BEST_ENCODER_FLAGS", None)
        monkeypatch.setattr(cr.media_service, "ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(
            cr.subprocess, "run",
            lambda *a, **k: type("R", (), {"stdout": self.ALL_LISTED, "returncode": 0})(),
        )
        monkeypatch.setattr(cr, "_encoder_actually_works", works)
        return cr._get_video_encoder_flags()

    def test_unusable_encoder_is_skipped_for_the_next_one(self, monkeypatch):
        flags = self._select(monkeypatch, lambda exe, f: f[1] != "h264_nvenc")
        assert flags[1] == "h264_amf"

    def test_falls_back_to_libx264_when_no_hardware_encoder_works(self, monkeypatch):
        flags = self._select(monkeypatch, lambda exe, f: False)
        assert flags[1] == "libx264"

    def test_first_working_encoder_is_chosen(self, monkeypatch):
        flags = self._select(monkeypatch, lambda exe, f: True)
        assert flags[1] == "h264_nvenc"

    def test_a_probe_that_raises_counts_as_unusable(self, monkeypatch):
        def boom(exe, f):
            raise OSError("probe blew up")
        monkeypatch.setattr(cr, "_BEST_ENCODER_FLAGS", None)
        monkeypatch.setattr(cr.media_service, "ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(
            cr.subprocess, "run",
            lambda *a, **k: type("R", (), {"stdout": self.ALL_LISTED, "returncode": 0})(),
        )
        monkeypatch.setattr(cr, "_encoder_actually_works", boom)
        # The outer try/except catches it and drops to CPU rather than failing selection.
        assert cr._get_video_encoder_flags()[1] == "libx264"

    def test_selection_is_cached_so_the_probe_runs_once(self, monkeypatch):
        calls = {"n": 0}

        def counting(exe, f):
            calls["n"] += 1
            return True

        self._select(monkeypatch, counting)
        first = calls["n"]
        cr._get_video_encoder_flags()
        cr._get_video_encoder_flags()
        assert calls["n"] == first
        monkeypatch.setattr(cr, "_BEST_ENCODER_FLAGS", None)
