"""
Word-level timestamps for a video, precise to fractions of a second.

Why this exists: MultimodalEngine.segment_transcript_into_sentences stores
math.floor(start)/math.ceil(end) — integer seconds (see multimodal_engine.py). A clip cut
on those boundaries can clip the first word or leave up to ~1s of dead air, which is the
"starts mid-sentence" complaint in a different costume. This module re-transcribes the
source media once per video with Whisper's word_timestamps=True and exposes snap_to_words()
so clip boundaries can be nudged onto exact word edges.

Runs once per video and is meant to be invoked through jobs.py (a 25-minute video on Whisper
'base'/CPU takes minutes) — not on a request thread.
"""
import json
import os
from typing import Callable, List, Optional, Tuple, TypedDict

import media_service
import paths
import transcript_service

DEFAULT_LEAD_IN_SEC = 0.12
DEFAULT_TAIL_SEC = 0.25


class Word(TypedDict):
    word: str
    start: float
    end: float


def _words_path(video_id: str) -> str:
    return os.path.join(paths.WORDS_DIR, f"{video_id}.json")


def load_words(video_id: str) -> Optional[List[Word]]:
    path = _words_path(video_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def ensure_words(
    video_id: str,
    media_path: str,
    report: Optional[Callable[[str, float, str], None]] = None,
) -> List[Word]:
    """
    Return word-level timestamps for `video_id`, transcribing with Whisper
    (word_timestamps=True) if not already cached. Reuses
    transcript_service.preload_whisper_model()'s loaded model rather than a separate
    faster-whisper instance (ENGINE-PLAN.md explicitly defers that upgrade).
    """
    cached = load_words(video_id)
    if cached is not None:
        if report:
            report("words", 1.0, "using cached word timings")
        return cached

    if report:
        report("words", 0.05, "loading Whisper model")

    media_service.ffmpeg_exe()  # ensures ffmpeg is on PATH before Whisper shells out to it
    if not transcript_service.HAS_LOCAL_WHISPER or transcript_service.local_whisper is None:
        raise RuntimeError(
            "Local Whisper ('openai-whisper') is not installed — word-level timing "
            "requires it. Install backend/requirements.txt."
        )
    # Reuses whichever tier the ingest path last loaded for this process (cached per-tier in
    # transcript_service._LOCAL_WHISPER_MODELS) rather than a separate faster-whisper instance
    # (ENGINE-PLAN.md explicitly defers that upgrade).
    model = transcript_service._get_local_whisper_model(transcript_service._resolve_model_tier(None))

    if report:
        report("words", 0.15, "transcribing with word-level timestamps")

    result = model.transcribe(media_path, word_timestamps=True)

    words: List[Word] = []
    for seg in result.get('segments', []):
        for w in seg.get('words', []) or []:
            text = (w.get('word') or '').strip()
            if not text:
                continue
            words.append({
                "word": text,
                "start": float(w.get('start', 0.0)),
                "end": float(w.get('end', 0.0)),
            })

    os.makedirs(paths.WORDS_DIR, exist_ok=True)
    with open(_words_path(video_id), 'w', encoding='utf-8') as f:
        json.dump(words, f, indent=2, ensure_ascii=False)

    if report:
        report("words", 1.0, f"transcribed {len(words)} words")

    return words


def _nearest_word_boundary(words: List[Word], t: float, prefer: str) -> float:
    """Nearest word start (prefer='start') or end (prefer='end') to timestamp t."""
    if not words:
        return t
    key = "start" if prefer == "start" else "end"
    closest = min(words, key=lambda w: abs(w[key] - t))
    return closest[key]


def snap_to_words(
    video_id: str,
    start_sec: float,
    end_sec: float,
    lead_in: float = DEFAULT_LEAD_IN_SEC,
    tail: float = DEFAULT_TAIL_SEC,
) -> Tuple[float, float]:
    """
    Snap [start_sec, end_sec] onto exact word boundaries for `video_id`, then apply a small
    lead-in/tail so the cut breathes instead of starting exactly on the first phoneme.

    Falls back to the input unchanged (never crosses into an adjacent word) if no word
    timing file exists yet for this video — callers should treat that as
    `timing_precise: false` rather than fail outright (ENGINE-PLAN.md Phase 1).
    """
    words = load_words(video_id)
    if not words:
        return start_sec, end_sec

    snapped_start = _nearest_word_boundary(words, start_sec, prefer="start")
    snapped_end = _nearest_word_boundary(words, end_sec, prefer="end")

    if snapped_end <= snapped_start:
        # Degenerate window (e.g. a single-word clip where nearest boundaries collapsed) —
        # don't let lead-in/tail push start past end.
        return snapped_start, max(snapped_end, snapped_start + 0.1)

    final_start = max(0.0, snapped_start - lead_in)
    final_end = snapped_end + tail
    return final_start, final_end


def _boundary_words(video_id: str) -> Optional[List[Word]]:
    return load_words(video_id)


def silence_gap_before(video_id: str, t: float) -> float:
    """Seconds of silence between the previous word's end and t. 0.0 if no words data or t
    is before/at the first word."""
    words = load_words(video_id)
    if not words:
        return 0.0
    preceding = [w for w in words if w["end"] <= t]
    if not preceding:
        return 0.0
    return max(0.0, t - max(w["end"] for w in preceding))


def silence_gap_after(video_id: str, t: float) -> float:
    """Seconds of silence between t and the next word's start. 0.0 if no words data or t is
    after/at the last word."""
    words = load_words(video_id)
    if not words:
        return 0.0
    following = [w for w in words if w["start"] >= t]
    if not following:
        return 0.0
    return max(0.0, min(w["start"] for w in following) - t)
