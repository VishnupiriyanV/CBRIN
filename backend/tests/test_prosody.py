"""
Tests for prosody.py — pitch and energy contours.

Driven with synthetic signals rather than media files: a tone of known frequency is the only
way to assert that the pitch tracker is actually right, and it needs no ffmpeg round-trip.
The redirect_data fixture in conftest.py points paths.PROSODY_DIR at a tmp_path.

Run with: python -m pytest backend/tests/test_prosody.py -v
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import prosody  # noqa: E402


def _tone(hz, seconds=3.0, amplitude=0.5):
    """A sawtooth-ish tone with harmonics — closer to voiced speech than a pure sine, which
    is degenerate for autocorrelation."""
    t = np.arange(int(prosody.SAMPLE_RATE * seconds)) / prosody.SAMPLE_RATE
    wave = sum((amplitude / k) * np.sin(2 * np.pi * hz * k * t) for k in (1, 2, 3))
    return wave.astype(np.float32)


def _silence(seconds=2.0):
    return np.zeros(int(prosody.SAMPLE_RATE * seconds), dtype=np.float32)


class TestPitchTracking:
    @pytest.mark.parametrize("hz", [90.0, 110.0, 150.0, 220.0, 300.0])
    def test_recovers_known_pitch(self, hz):
        data = prosody.analyze_signal(_tone(hz))
        voiced = data["f0"][data["f0"] > 0]
        assert voiced.size > 0
        # Within a semitone of truth across the speech range.
        assert abs(12 * np.log2(float(np.median(voiced)) / hz)) < 1.0

    def test_silence_produces_no_voiced_frames(self):
        data = prosody.analyze_signal(_silence())
        assert int((data["f0"] > 0).sum()) == 0
        assert data["baseline_f0"] == 0.0

    def test_white_noise_is_mostly_unvoiced(self):
        rng = np.random.default_rng(0)
        noise = rng.standard_normal(prosody.SAMPLE_RATE * 3).astype(np.float32) * 0.3
        data = prosody.analyze_signal(noise)
        # Aperiodic input must not read as pitched. Before the interior-local-maximum check in
        # _f0_via_autocorrelation, frames like these pinned to the F0_MIN/F0_MAX search bounds
        # and reported extreme pitch.
        assert float((data["f0"] > 0).mean()) < 0.2

    def test_no_pitch_pinned_to_the_search_bounds(self):
        rng = np.random.default_rng(1)
        mixed = np.concatenate([
            _tone(140.0, 1.5),
            rng.standard_normal(prosody.SAMPLE_RATE).astype(np.float32) * 0.2,
            _tone(140.0, 1.5),
        ])
        data = prosody.analyze_signal(mixed)
        voiced = data["f0"][data["f0"] > 0]
        assert voiced.size > 0
        at_rails = np.mean(
            (voiced <= prosody.F0_MIN_HZ + 1.0) | (voiced >= prosody.F0_MAX_HZ - 1.0))
        assert at_rails < 0.05

    def test_baseline_is_the_median_of_voiced_frames(self):
        data = prosody.analyze_signal(_tone(180.0))
        assert abs(data["baseline_f0"] - 180.0) < 6.0


class TestWindowFeatures:
    @staticmethod
    def _write(video_id, signal):
        data = prosody.analyze_signal(signal)
        os.makedirs(prosody.paths.PROSODY_DIR, exist_ok=True)
        np.savez_compressed(
            os.path.join(prosody.paths.PROSODY_DIR, f"{video_id}.npz"),
            rms=data["rms"], f0=data["f0"], baseline_f0=data["baseline_f0"],
            hop_sec=data["hop_sec"], n_frames=data["n_frames"],
        )

    def test_missing_prosody_returns_none_not_zero(self):
        # None means "not measured" — callers must not read it as a flat delivery.
        assert prosody.window_features("vid-absent", 0.0, 10.0) is None

    def test_monotone_scores_a_narrower_pitch_range_than_varied(self):
        self._write("vid-flat", _tone(150.0, 6.0))
        varied = np.concatenate([_tone(120.0, 2.0), _tone(190.0, 2.0), _tone(150.0, 2.0)])
        self._write("vid-varied", varied)

        flat = prosody.window_features("vid-flat", 0.0, 6.0)
        moved = prosody.window_features("vid-varied", 0.0, 6.0)
        assert flat["pitch_range_st"] < moved["pitch_range_st"]

    def test_energy_delta_detects_a_build(self):
        quiet_then_loud = np.concatenate([_tone(150.0, 3.0, 0.05), _tone(150.0, 3.0, 0.9)])
        self._write("vid-build", quiet_then_loud)
        f = prosody.window_features("vid-build", 0.0, 6.0)
        assert f["energy_delta"] > 0.5

    def test_pitch_delta_is_signed_by_direction(self):
        self._write("vid-up", np.concatenate([_tone(120.0, 3.0), _tone(200.0, 3.0)]))
        self._write("vid-down", np.concatenate([_tone(200.0, 3.0), _tone(120.0, 3.0)]))
        assert prosody.window_features("vid-up", 0.0, 6.0)["pitch_delta_st"] > 3.0
        assert prosody.window_features("vid-down", 0.0, 6.0)["pitch_delta_st"] < -3.0

    def test_pitch_marked_unreliable_when_too_few_voiced_frames(self):
        self._write("vid-mostly-silent", np.concatenate([_tone(150.0, 0.3), _silence(6.0)]))
        f = prosody.window_features("vid-mostly-silent", 0.0, 6.0)
        assert f is not None
        assert f["pitch_reliable"] is False
        assert f["pitch_range_st"] == 0.0

    def test_degenerate_window_returns_none(self):
        self._write("vid-ok", _tone(150.0, 4.0))
        assert prosody.window_features("vid-ok", 3.0, 3.0) is None
        assert prosody.window_features("vid-ok", 5.0, 4.0) is None


class TestCaching:
    def test_load_is_cached_and_invalidated_by_mtime(self):
        TestWindowFeatures._write("vid-cache", _tone(150.0, 4.0))
        first = prosody.load_prosody("vid-cache")
        assert first is not None
        assert prosody.load_prosody("vid-cache") is first  # same object, not re-parsed

        TestWindowFeatures._write("vid-cache", _tone(220.0, 4.0))
        os.utime(os.path.join(prosody.paths.PROSODY_DIR, "vid-cache.npz"), (0, 0))
        assert prosody.load_prosody("vid-cache") is not first
