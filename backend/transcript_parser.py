"""
Shared transcript input parser for STUDIO tools 2 (Show Notes) and 6 (Clip-Moment Finder).

Nothing in the backend previously parsed SRT/VTT (confirmed by grep before writing this
module) — YouTube ingest and Whisper transcription both produce the canonical
`{text, start, duration}` segment shape directly, without ever touching subtitle files.
This module produces that same shape from pasted SRT, WebVTT, or plain text, so its output
feeds straight into MultimodalEngine.segment_transcript_into_sentences (multimodal_engine.py)
exactly like a YouTube or Whisper transcript would.

Deliberately lenient rather than strict: it extracts whatever valid cues it can find and
only falls back to "plain" when nothing usable was extracted, rather than raising on a
malformed file. The one hard rule (creator-tools-integration-spec.md §2): never invent a
timestamp. A cue is only ever reported at the time value actually present in the input.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

_TAG_RE = re.compile(r'<[^>]+>')


def _clean_lines(raw: str) -> List[str]:
    if raw.startswith('﻿'):  # UTF-8 BOM
        raw = raw[1:]
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')
    return raw.split('\n')


def _parse_timestamp_token(token: str) -> Optional[float]:
    """Accepts SRT's comma decimal (00:01:02,500) and VTT's dot (00:01:02.500), plus the
    hours-omitted MM:SS(.mmm) form some VTT files use."""
    token = token.strip().replace(',', '.')
    parts = token.split(':')
    if len(parts) not in (2, 3):
        return None
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        h, m, s = nums
    else:
        h, (m, s) = 0.0, nums
    return h * 3600 + m * 60 + s


def _try_parse_timestamp_line(line: str) -> Optional[Tuple[float, float]]:
    if '-->' not in line:
        return None
    left, right = line.split('-->', 1)
    left_token = left.strip().split()[0] if left.strip() else ''
    right_tokens = right.strip().split()  # first token is the end time; rest is cue settings
    if not right_tokens:
        return None
    start = _parse_timestamp_token(left_token)
    end = _parse_timestamp_token(right_tokens[0])
    if start is None or end is None:
        return None
    return start, end


def _extract_cues(lines: List[str]) -> List[Tuple[float, float, str]]:
    """Scans line-by-line for `-->` timestamp lines rather than assuming strict SRT/VTT
    block structure (index line, timestamp, text, blank). An SRT index line or a VTT cue
    identifier before the timestamp is simply skipped as a non-matching line — no special
    casing needed. VTT `NOTE` blocks are skipped explicitly since they never contain cues."""
    cues: List[Tuple[float, float, str]] = []
    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()

        if stripped.upper() == 'NOTE' or stripped.upper().startswith('NOTE '):
            i += 1
            while i < n and lines[i].strip():
                i += 1
            i += 1
            continue

        ts = _try_parse_timestamp_line(stripped)
        if ts is None:
            i += 1
            continue

        start, end = ts
        i += 1
        text_lines = []
        while i < n and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        cue_text = ' '.join(text_lines).strip()
        cues.append((start, end, cue_text))
        i += 1  # consume the blank separator

    return cues


def parse_timed_input(text: str) -> Dict[str, Any]:
    """
    Returns:
        {
          "format": "srt" | "vtt" | "plain",
          "has_timestamps": bool,
          "segments": [{"text": str, "start": float, "duration": float}, ...],
          "duration_sec": float | None,   # None whenever has_timestamps is False
        }
    """
    if not text or not text.strip():
        return {"format": "plain", "has_timestamps": False, "segments": [], "duration_sec": None}

    lines = _clean_lines(text)
    is_vtt_header = bool(lines) and lines[0].strip().upper().startswith('WEBVTT')

    cues = sorted(_extract_cues(lines), key=lambda c: c[0])

    segments = []
    prev_text: Optional[str] = None
    for start, end, cue_text in cues:
        clean_text = _TAG_RE.sub('', cue_text).strip()
        if not clean_text:
            continue  # empty cue
        if clean_text == prev_text:
            continue  # YouTube rolling-caption duplicate line
        segments.append({"text": clean_text, "start": start, "duration": max(0.0, end - start)})
        prev_text = clean_text

    if segments:
        fmt = "vtt" if is_vtt_header else "srt"
        duration_sec = max(s["start"] + s["duration"] for s in segments)
        return {"format": fmt, "has_timestamps": True, "segments": segments, "duration_sec": duration_sec}

    # No usable cues (including a file that is nearly-SRT but malformed) -> plain fallback,
    # never a half-parsed result.
    return {
        "format": "plain",
        "has_timestamps": False,
        "segments": [{"text": text.strip(), "start": 0.0, "duration": 0.0}],
        "duration_sec": None,
    }


def word_count(text: str) -> int:
    return len(text.split())
