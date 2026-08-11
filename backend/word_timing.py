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


# Parsed word lists, keyed by path -> (mtime, words). load_words() is called several times
# per candidate (snap_clip_bounds once, silence_gap_before/after once each, _emotional_delta
# once), so ranking 8 candidates re-read and re-parsed the same multi-thousand-entry JSON
# ~32 times. Keyed on mtime so a re-transcribe invalidates it without a manual flush.
_WORDS_CACHE: "dict[str, Tuple[float, List[Word]]]" = {}


def load_words(video_id: str) -> Optional[List[Word]]:
    path = _words_path(video_id)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _WORDS_CACHE.pop(path, None)
        return None

    cached = _WORDS_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with open(path, 'r', encoding='utf-8') as f:
            words = json.load(f)
    except Exception:
        return None

    _WORDS_CACHE[path] = (mtime, words)
    return words


def ensure_words(
    video_id: str,
    media_path: str,
    report: Optional[Callable[[str, float, str], None]] = None,
) -> List[Word]:
    """
    Return word-level timestamps for `video_id`, transcribing with word_timestamps=True if
    not already cached. Goes through transcript_service._transcribe_local, which prefers
    faster-whisper (native word timestamps, ~4x faster on GPU) and falls back to
    openai-whisper transparently — this module doesn't need to know which one ran.
    """
    cached = load_words(video_id)
    if cached is not None:
        if report:
            report("words", 1.0, "using cached word timings")
        return cached

    if report:
        report("words", 0.05, "loading transcription model")

    media_service.ffmpeg_exe()  # ensures ffmpeg is on PATH before Whisper shells out to it
    if not transcript_service.HAS_FASTER_WHISPER and (
        not transcript_service.HAS_LOCAL_WHISPER or transcript_service.local_whisper is None
    ):
        raise RuntimeError(
            "No local transcription engine available — word-level timing requires "
            "faster-whisper or openai-whisper. Install backend/requirements.txt."
        )

    if report:
        report("words", 0.15, "transcribing with word-level timestamps")

    local_result = transcript_service._transcribe_local(
        media_path, transcript_service._resolve_model_tier(None), word_timestamps=True
    )

    words: List[Word] = []
    for seg in local_result["segments"]:
        for w in seg.get("words", []) or []:
            words.append({"word": w["word"], "start": w["start"], "end": w["end"]})

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
    is before/at the first word.

    NOT a boundary-quality metric — use phrase_gap_before() for that. This measures dead air
    adjacent to an arbitrary timestamp, so it is maximised by placing the cut in the middle of
    a pause, and clip_scoring._boundary_cleanliness scored exactly backwards for as long as it
    called this. Kept because "how much silence is at time t" is still a legitimate question
    (trimming, UI scrubbing); just don't rank clips with it.
    """
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


def phrase_gap_before(video_id: str, start_sec: float) -> Optional[float]:
    """
    Seconds of silence preceding the first word at or after `start_sec` — a property of the
    SPEECH, not of where the cut timestamp happens to sit.

    silence_gap_before() answers "how much dead air is next to my cut", which is maximised by
    cutting in the middle of a pause — i.e. by the exact defect snap_clip_bounds() removes.
    This answers "did the clip's first word follow a real pause", which is what actually makes
    a boundary clean, and it does not change when lead-in/tail move the cut a few frames.

    Returns None when nothing precedes the clip (it opens the recording) — no adjacent speech
    to cut into, which callers should treat as a perfectly clean boundary rather than a zero.
    """
    words = load_words(video_id)
    if not words:
        return None
    following = [w["start"] for w in words if w["start"] >= start_sec]
    if not following:
        return None
    onset = min(following)
    prior_ends = [w["end"] for w in words if w["end"] <= onset]
    if not prior_ends:
        return None
    return max(0.0, onset - max(prior_ends))


def phrase_gap_after(video_id: str, end_sec: float) -> Optional[float]:
    """Mirror of phrase_gap_before for the out-point: silence following the last word ending
    at or before `end_sec`. None when the clip runs to the end of the recording."""
    words = load_words(video_id)
    if not words:
        return None
    preceding = [w["end"] for w in words if w["end"] <= end_sec]
    if not preceding:
        return None
    offset = max(preceding)
    later_starts = [w["start"] for w in words if w["start"] >= offset]
    if not later_starts:
        return None
    return max(0.0, min(later_starts) - offset)


# --- Clip boundary snapping --------------------------------------------------------------
#
# Sentence timings are quantised to whole seconds by MultimodalEngine (multimodal_engine.py
# :362 stores math.floor(start_sec) / math.ceil(end_sec)) — confirmed against the real
# corpus, where every start_sec/end_sec in data/chunks.json is an integer. So a candidate
# built from sentence bounds is wrong by up to 1.0s on EACH side, in two distinguishable ways:
#
#   1. floor() moves the in-point earlier, so the common case is up to a second of dead air
#      before the first word — fatal for a short-form hook, where the first second is the
#      whole pitch.
#   2. When the PREVIOUS sentence's last word ends after that floored second, the same cut
#      opens on the tail of a foreign word. That's the "starts mid-sentence" complaint, and
#      it is the reason a plain "trim the silence" pass is not sufficient.
#
# ceil() is the mirror image on the out-point. SNAP_WINDOW_SEC is 1.2 rather than 1.0 to
# cover the quantisation plus the segment-boundary slop Whisper itself introduces; a window
# much wider than that starts reaching into genuinely adjacent speech.
#
# This is deliberately NOT snap_to_words(): that helper takes a globally nearest word edge
# (min over ALL words), which is correct for a human dragging a handle in the UI but wrong
# here — an unbounded search can drag a boundary seconds across a silence. Everything below
# is bounded by `window` and refuses to move rather than move badly.

SNAP_WINDOW_SEC = 1.2

# Never place a cut closer than this to a neighbouring word, so lead-in/tail can't bleed a
# syllable of the sentence before or after into the clip.
ADJACENT_MARGIN_SEC = 0.06


class SnapInfo(TypedDict):
    snapped: bool           # did either edge move?
    start_moved_by: float   # seconds, signed (positive = start moved later)
    end_moved_by: float     # seconds, signed (positive = end moved later)
    reason: str


def _no_snap(reason: str) -> SnapInfo:
    return {"snapped": False, "start_moved_by": 0.0, "end_moved_by": 0.0, "reason": reason}


def snap_clip_bounds(
    video_id: str,
    start_sec: float,
    end_sec: float,
    lead_in: float = DEFAULT_LEAD_IN_SEC,
    tail: float = DEFAULT_TAIL_SEC,
    window: float = SNAP_WINDOW_SEC,
) -> Tuple[float, float, SnapInfo]:
    """
    Move a candidate's [start_sec, end_sec] onto the real speech onset/offset, bounded by
    `window` seconds of search on each side.

    In-point: the first word starting at or after `start_sec` within the window is the clip's
    true first word. Back off by `lead_in` so the cut doesn't land on the first phoneme, then
    clamp so it can't reach the previous word's tail.

    Out-point: the last word ending at or before `end_sec` within the window is the true last
    word. Extend by `tail`, clamped short of the next word's onset.

    Both edges are independent — one can snap while the other doesn't. Returns the input
    unchanged (with snapped=False and a reason) when there is no word timing for this video,
    or when no word edge falls inside the window. Refusing to move is always preferred over
    moving to a worse place; a boundary this function declines to fix is still scored honestly
    by clip_scoring._boundary_cleanliness.
    """
    words = load_words(video_id)
    if not words:
        return start_sec, end_sec, _no_snap("no word timing for this video")
    if end_sec <= start_sec:
        return start_sec, end_sec, _no_snap("degenerate input window")

    # --- in-point -----------------------------------------------------------------------
    onsets = [w for w in words if start_sec <= w["start"] <= start_sec + window]
    new_start = start_sec
    start_reason = "no word onset within snap window"
    if onsets:
        onset = min(onsets, key=lambda w: w["start"])["start"]
        # Don't let lead_in reach back into whatever was being said before the clip.
        prior_ends = [w["end"] for w in words if w["end"] <= onset]
        floor_bound = (max(prior_ends) + ADJACENT_MARGIN_SEC) if prior_ends else 0.0
        new_start = max(0.0, onset - lead_in, min(floor_bound, onset))
        start_reason = "snapped to speech onset"

    # --- out-point ----------------------------------------------------------------------
    offsets = [w for w in words if end_sec - window <= w["end"] <= end_sec]
    new_end = end_sec
    end_reason = "no word offset within snap window"
    if offsets:
        offset = max(offsets, key=lambda w: w["end"])["end"]
        later_starts = [w["start"] for w in words if w["start"] >= offset]
        ceil_bound = (min(later_starts) - ADJACENT_MARGIN_SEC) if later_starts else offset + tail
        # Capped at the original end_sec: ceil() only ever moved the out-point LATER, so a
        # correct snap can only pull it earlier. Without the cap, `offset + tail` can push
        # past the raw bound — and because ceil() rounds up by as much as a second, the next
        # sentence's opening word can legitimately start AND end inside the search window, so
        # `max(offsets)` will happily pick it. Capping means the worst case is "no
        # improvement", never "swallowed a word the candidate never claimed".
        new_end = min(offset + tail, max(ceil_bound, offset), end_sec)
        end_reason = "snapped to speech offset"

    # A snap that inverts or collapses the window is a bug in the making — discard both edges
    # rather than emit a clip shorter than the sentences it claims to contain.
    if new_end - new_start < 0.5:
        return start_sec, end_sec, _no_snap("snap would collapse the clip window")

    start_moved = round(new_start - start_sec, 4)
    end_moved = round(new_end - end_sec, 4)
    return new_start, new_end, {
        "snapped": bool(start_moved or end_moved),
        "start_moved_by": start_moved,
        "end_moved_by": end_moved,
        "reason": f"{start_reason}; {end_reason}",
    }
