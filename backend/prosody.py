"""
Acoustic prosody: pitch and energy contours for a video, cached per video.

Why this exists: clip_scoring._emotional_delta measured "emotional arc" as a words-per-minute
delta between clip halves — one prosodic dimension of three, and the weakest one. A speaker
who drops to a whisper and then builds to a shout at a constant speaking rate registered as
flat. Pitch and loudness are where delivery actually lives.

The external evidence is unusually direct. The ICCV VQualA 2025 engagement challenge ran
head-to-head on SnapUGC (90,000 short videos, engagement labels from 2,000+ users each):
VideoLLaMA2-7B *with* audio scored 0.695, Qwen2.5-VL-7B — newer, vision-language only —
scored 0.664. The newer, stronger model lost to the older one that could hear. TF-SELECTOR
independently feeds raw audio volume into its scoring LLM alongside captions and ASR.

NO NEW DEPENDENCY. librosa would be the obvious tool and pulls in soundfile/audioread/pooch
behind it; torchaudio is not installed. This needs coarse prosody — is the delivery animated
or flat — not precise f0 tracking, so it decodes with the ffmpeg binary already bundled for
clip rendering and computes the contours with numpy and scipy, both already present as
scikit-learn dependencies. Nothing here touches the network, which keeps the local-first
positioning intact rather than fighting it.

Runs once per video, cached to paths.PROSODY_DIR, and is meant to be invoked through jobs.py
alongside word_timing.ensure_words — decoding and framing a 25-minute video is seconds, not
milliseconds, and does not belong on a request thread.
"""
import os
import subprocess
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

import media_service
import paths

SAMPLE_RATE = 16000

# 1024 samples = 64ms. The floor matters: resolving f0 down to F0_MIN_HZ needs at least two
# periods in the window (60 Hz -> 267 samples -> 534 needed), so 1024 clears it comfortably.
FRAME_LENGTH = 1024
HOP_LENGTH = 512  # 32ms — ~47k frames for a 25-minute video, a few hundred KB compressed

# Human speech f0. Wide enough to cover a low male voice through a high female one; anything
# outside is almost certainly an octave error or noise.
F0_MIN_HZ = 60.0
F0_MAX_HZ = 400.0

# Normalised autocorrelation peak below this is treated as unvoiced. Started at 0.3, raised
# after measurement: a missed voiced frame costs a little contour resolution, but admitting an
# aperiodic frame corrupts the pitch statistics this module exists to produce, and at 0.3 the
# corpus was carrying visible rail artifacts (see the local-maximum check in
# _f0_via_autocorrelation). Clearly voiced speech sits well above 0.45.
VOICING_THRESHOLD = 0.45

# Frames quieter than this fraction of the video's own peak RMS are unvoiced regardless of
# what autocorrelation says. Silence autocorrelates with itself perfectly well.
SILENCE_RMS_FRACTION = 0.02

# Voiced frames needed before pitch spread/direction are reported as usable. 30 frames at
# a 32ms hop is just under a second of actual voiced speech.
MIN_VOICED_FRAMES_FOR_PITCH = 30


class ProsodyUnavailable(Exception):
    """Raised when audio cannot be decoded. Callers should degrade, never fail the analysis."""


def _prosody_path(video_id: str) -> str:
    return os.path.join(paths.PROSODY_DIR, f"{video_id}.npz")


# Parsed contours keyed by path -> (mtime, data). Scoring touches this once per candidate and
# the arrays are tens of thousands of frames; re-reading per candidate would dominate ranking.
_PROSODY_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _decode_audio(media_path: str) -> np.ndarray:
    """Decode `media_path` to mono float32 PCM at SAMPLE_RATE via the bundled ffmpeg."""
    ffmpeg = media_service.ffmpeg_exe()
    cmd = [
        ffmpeg, "-nostdin", "-loglevel", "error", "-i", media_path,
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except OSError as e:
        raise ProsodyUnavailable(f"could not run ffmpeg: {e}") from e

    if proc.returncode != 0 or not proc.stdout:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise ProsodyUnavailable(f"ffmpeg produced no audio for {os.path.basename(media_path)}: {detail}")

    pcm = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if pcm.size < FRAME_LENGTH:
        raise ProsodyUnavailable("decoded audio is shorter than a single analysis frame")
    return pcm


def _frame(signal: np.ndarray) -> np.ndarray:
    """Split into overlapping frames as a (n_frames, FRAME_LENGTH) view — no copy."""
    n_frames = 1 + (len(signal) - FRAME_LENGTH) // HOP_LENGTH
    if n_frames < 1:
        return np.empty((0, FRAME_LENGTH), dtype=np.float32)
    stride = signal.strides[0]
    return np.lib.stride_tricks.as_strided(
        signal, shape=(n_frames, FRAME_LENGTH), strides=(stride * HOP_LENGTH, stride),
        writeable=False,
    )


def _f0_via_autocorrelation(frames: np.ndarray, rms: np.ndarray) -> np.ndarray:
    """
    Per-frame f0 in Hz (0.0 where unvoiced), by normalised autocorrelation.

    A simplified YIN: FFT-based autocorrelation, peak-picked inside the lag range that
    corresponds to plausible speech f0. Cheaper and far less code than a real pitch tracker,
    and sufficient for the statistics downstream actually uses — spread and direction of the
    contour, never an exact note.
    """
    if frames.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)

    min_lag = max(int(SAMPLE_RATE / F0_MAX_HZ), 1)
    max_lag = min(int(SAMPLE_RATE / F0_MIN_HZ), FRAME_LENGTH - 1)
    if max_lag <= min_lag:
        return np.zeros(frames.shape[0], dtype=np.float32)

    # Remove per-frame DC so a constant offset can't dominate the correlation.
    centred = frames - frames.mean(axis=1, keepdims=True)

    n_fft = 1 << int(np.ceil(np.log2(2 * FRAME_LENGTH)))
    spectrum = np.fft.rfft(centred, n=n_fft, axis=1)
    autocorr = np.fft.irfft(spectrum * np.conjugate(spectrum), n=n_fft, axis=1)

    zero_lag = autocorr[:, 0:1]
    # Frames with no energy have a zero-lag of 0; guard before dividing.
    safe = np.where(zero_lag > 1e-10, zero_lag, 1.0)
    normalised = autocorr[:, min_lag:max_lag + 1] / safe

    best_offset = np.argmax(normalised, axis=1)
    rows = np.arange(normalised.shape[0])
    best_value = normalised[rows, best_offset]
    lags = best_offset + min_lag

    # The peak must be a genuine interior local maximum. Without this, a frame with no real
    # periodicity still yields an argmax, which lands on whichever end of the search range the
    # correlation happens to slope toward — so aperiodic frames pile up at exactly F0_MIN_HZ
    # and F0_MAX_HZ and read as extreme pitch.
    #
    # Measured before this check existed, on the real 25-minute video: raw f0 percentiles were
    # p1=60.2Hz and p99=400.0Hz — the search bounds themselves, to one decimal — with 29% of
    # "voiced" frames beyond +/-9 semitones of the speaker's own median. The rails, not the
    # speaker. A median filter cannot fix this because the errors are sustained, not isolated.
    interior = (best_offset > 0) & (best_offset < normalised.shape[1] - 1)
    safe_offset = np.clip(best_offset, 1, max(normalised.shape[1] - 2, 1))
    is_local_max = (
        (normalised[rows, safe_offset] > normalised[rows, safe_offset - 1])
        & (normalised[rows, safe_offset] > normalised[rows, safe_offset + 1])
    )

    voiced = (
        (best_value >= VOICING_THRESHOLD)
        & interior
        & is_local_max
        & (zero_lag[:, 0] > 1e-10)
        & (rms > SILENCE_RMS_FRACTION * max(float(rms.max()), 1e-10))
    )
    f0 = np.where(voiced, SAMPLE_RATE / np.maximum(lags, 1), 0.0)
    return _smooth_octave_errors(f0.astype(np.float32))


# Autocorrelation's characteristic failure is the octave error: a peak at twice or half the
# true period reads as an f0 an octave out. They are isolated frame-level jumps against a
# contour that is otherwise continuous, so a short median filter removes them.
#
# Not a cosmetic detail. Measured on the real 439-sentence corpus BEFORE this filter existed,
# median pitch_range_st was 17.0 semitones with a p99 of 32.8 — 2.7 octaves. Human speaking
# range is roughly 10-12 semitones end to end, so the feature was mostly reporting octave
# errors rather than delivery, and every clip would have scored as animated.
_OCTAVE_MEDIAN_KERNEL = 5  # 5 frames at a 32ms hop = 160ms, shorter than any real pitch move


def _smooth_octave_errors(f0: np.ndarray) -> np.ndarray:
    """Median-filter the voiced pitch track, leaving unvoiced frames at zero."""
    from scipy.signal import medfilt

    voiced_mask = f0 > 0
    if voiced_mask.sum() < _OCTAVE_MEDIAN_KERNEL:
        return f0

    # Bridge unvoiced gaps before filtering — a median over a track punctuated by zeros would
    # drag voiced frames toward zero rather than toward their neighbours' pitch.
    idx = np.arange(f0.size)
    voiced_idx = idx[voiced_mask]
    bridged = np.interp(idx, voiced_idx, f0[voiced_mask]).astype(np.float32)

    smoothed = medfilt(bridged, kernel_size=_OCTAVE_MEDIAN_KERNEL).astype(np.float32)
    return np.where(voiced_mask, smoothed, 0.0).astype(np.float32)


def analyze_signal(pcm: np.ndarray) -> Dict[str, Any]:
    """Contours for an already-decoded mono signal. Split out so tests can drive it with
    synthetic tones instead of needing a media file and an ffmpeg round-trip."""
    frames = _frame(pcm)
    if frames.shape[0] == 0:
        raise ProsodyUnavailable("signal too short to frame")

    rms = np.sqrt(np.maximum((frames.astype(np.float32) ** 2).mean(axis=1), 0.0)).astype(np.float32)
    f0 = _f0_via_autocorrelation(frames, rms)

    voiced_f0 = f0[f0 > 0]
    # The speaker's own baseline. Every pitch figure downstream is expressed in semitones
    # relative to this, which is what makes the features comparable across speakers instead of
    # just reporting that one person has a deeper voice than another.
    baseline = float(np.median(voiced_f0)) if voiced_f0.size else 0.0

    return {
        "rms": rms,
        "f0": f0,
        "baseline_f0": baseline,
        "hop_sec": HOP_LENGTH / SAMPLE_RATE,
        "n_frames": int(frames.shape[0]),
    }


def load_prosody(video_id: str) -> Optional[Dict[str, Any]]:
    path = _prosody_path(video_id)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _PROSODY_CACHE.pop(path, None)
        return None

    cached = _PROSODY_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with np.load(path) as npz:
            data = {
                "rms": npz["rms"],
                "f0": npz["f0"],
                "baseline_f0": float(npz["baseline_f0"]),
                "hop_sec": float(npz["hop_sec"]),
                "n_frames": int(npz["n_frames"]),
            }
    except Exception:
        return None

    _PROSODY_CACHE[path] = (mtime, data)
    return data


def ensure_prosody(
    video_id: str,
    media_path: str,
    report: Optional[Callable[[str, float, str], None]] = None,
) -> Dict[str, Any]:
    """Return cached contours for `video_id`, extracting them from `media_path` if absent."""
    cached = load_prosody(video_id)
    if cached is not None:
        if report:
            report("prosody", 1.0, "using cached prosody")
        return cached

    if report:
        report("prosody", 0.1, "decoding audio")
    pcm = _decode_audio(media_path)

    if report:
        report("prosody", 0.5, "measuring pitch and energy")
    data = analyze_signal(pcm)

    os.makedirs(paths.PROSODY_DIR, exist_ok=True)
    np.savez_compressed(
        _prosody_path(video_id),
        rms=data["rms"], f0=data["f0"],
        baseline_f0=data["baseline_f0"], hop_sec=data["hop_sec"], n_frames=data["n_frames"],
    )
    _PROSODY_CACHE.pop(_prosody_path(video_id), None)

    if report:
        report("prosody", 1.0, f"analysed {data['n_frames']} frames")
    return data


def _semitones(f0: np.ndarray, baseline: float) -> np.ndarray:
    """Voiced f0 as semitones relative to the speaker's median. Speaker-independent by
    construction — a deep voice and a high one both centre on zero."""
    if baseline <= 0:
        return np.zeros(0, dtype=np.float32)
    voiced = f0[f0 > 0]
    if voiced.size == 0:
        return np.zeros(0, dtype=np.float32)
    return 12.0 * np.log2(voiced / baseline)


def window_features(video_id: str, start_sec: float, end_sec: float) -> Optional[Dict[str, float]]:
    """
    Prosodic features for one clip window, or None when there is no prosody for this video.

    None means "not measured" and callers must treat it as unknown rather than as zero — the
    same distinction clip_scoring.BOUNDARY_UNKNOWN_SCORE draws for word timing.

      pitch_range_st   spread of the pitch contour, in semitones (p90-p10). Monotone delivery
                       sits near 0; an animated read runs several semitones.
      pitch_delta_st   median pitch of the second half minus the first, signed. Positive is a
                       build, negative a drop-off.
      energy_delta     |second half - first half| RMS, normalised by the louder half.
      energy_mean      mean RMS over the window, relative to the video's own peak.
      voiced_fraction  share of frames carrying pitch — low means mostly silence or noise.
      pitch_reliable   False when too few voiced frames to stand behind the pitch figures;
                       callers should drop the pitch terms rather than average in a guess.
    """
    data = load_prosody(video_id)
    if data is None or end_sec <= start_sec:
        return None

    hop = data["hop_sec"]
    n = data["n_frames"]
    lo = max(int(start_sec / hop), 0)
    hi = min(int(end_sec / hop) + 1, n)
    if hi - lo < 4:
        return None

    rms = data["rms"][lo:hi]
    f0 = data["f0"][lo:hi]
    baseline = data["baseline_f0"]

    mid = (hi - lo) // 2
    first_rms, second_rms = rms[:mid], rms[mid:]
    mean_first = float(first_rms.mean()) if first_rms.size else 0.0
    mean_second = float(second_rms.mean()) if second_rms.size else 0.0
    louder = max(mean_first, mean_second, 1e-10)

    st = _semitones(f0, baseline)
    # Pitch statistics over a handful of voiced frames are noise. ~1 second of voiced speech
    # is the floor for a spread figure to mean anything; below it callers should drop the
    # pitch terms rather than average in a number they cannot stand behind.
    pitch_reliable = st.size >= MIN_VOICED_FRAMES_FOR_PITCH
    pitch_range = float(np.percentile(st, 90) - np.percentile(st, 10)) if pitch_reliable else 0.0

    st_first = _semitones(f0[:mid], baseline)
    st_second = _semitones(f0[mid:], baseline)
    pitch_delta = (
        float(np.median(st_second) - np.median(st_first))
        if pitch_reliable and st_first.size and st_second.size else 0.0
    )

    peak = float(data["rms"].max()) or 1e-10

    return {
        "pitch_reliable": pitch_reliable,
        "pitch_range_st": pitch_range,
        "pitch_delta_st": pitch_delta,
        "energy_delta": abs(mean_second - mean_first) / louder,
        "energy_mean": float(rms.mean()) / peak,
        "voiced_fraction": float((f0 > 0).mean()),
    }
