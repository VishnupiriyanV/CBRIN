"""
Transcript -> narrative beats -> constraint-satisfying clip candidates.

This is ENGINE's core claim (ENGINE-PLAN.md Phase 2, the checkpoint phase): a clip
candidate is a contiguous sentence range that PROVABLY includes every beat its payoff
depends on. `requires_setup_from_idx` is a hard constraint enforced by a small solver in
beats_to_candidates(), not a suggestion an LLM can shrug off — so it is structurally
impossible for this module to emit a clip that cuts between a setup and its punchline.

Input is always the sentence list the Vault already produced
(MultimodalEngine.segment_transcript_into_sentences, surfaced as store.chunks with
sentence_idx/start_sec/end_sec) — never re-derived, because reusing the same units is what
makes the mid-sentence-start guarantee structural rather than heuristic.
"""
import re
from typing import Any, Dict, List, Optional

import llm_client

BEAT_TYPES = {
    "hook", "setup", "punchline", "confession", "turning_point",
    "lesson", "payoff", "cta", "tangent",
}
PAYOFF_BEAT_TYPES = {"punchline", "confession", "turning_point", "lesson", "payoff"}

MIN_CLIP_SEC = 12.0
MAX_CLIP_SEC = 75.0

# Above roughly this many words, window the transcript for the LLM provider's free-tier
# token caps (ENGINE-PLAN.md Phase 2: "Above ~8k input tokens, window into 60-sentence passes").
WINDOW_SENTENCE_COUNT = 60
WINDOW_OVERLAP = 10
WORD_COUNT_WINDOW_THRESHOLD = 6000

_SYSTEM_PROMPT = """You are analyzing a spoken video transcript to find its narrative beats — \
the structural moments that make a clip land: hooks, setups, punchlines, confessions, \
turning points, lessons, payoffs, calls-to-action, and tangents to skip.

For each beat you identify, output an object with these exact fields:
- beat_type: one of hook, setup, punchline, confession, turning_point, lesson, payoff, cta, tangent
- start_sentence_idx: integer, the [N] index of the first sentence of this beat
- end_sentence_idx: integer, the [N] index of the last sentence of this beat
- requires_setup_from_idx: integer or null — if this beat only makes sense with earlier \
context, the [N] index where that required context begins. null if self-contained.
- title: short human-readable label for this beat
- why_it_lands: one sentence explaining why this moment works
- emotional_arc: {"opening": str, "peak": str, "closing": str} — one or two words each
- self_contained: boolean — does this beat make sense without anything before it?
- quotable_line: the single most quotable sentence from this beat, copied verbatim

Respond with ONLY a JSON object of the form {"beats": [...]}. No prose, no markdown fences."""

_BEAT_SCHEMA = {
    "type": "array",
    "items": {
        "required": ["beat_type", "start_sentence_idx", "end_sentence_idx"],
    },
}


def _format_timestamp(seconds: float) -> str:
    seconds = int(seconds)
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02d}:{secs:02d}"


def _format_transcript_window(sentences: List[Dict[str, Any]]) -> str:
    lines = []
    for s in sentences:
        lines.append(f"[{s['sentence_idx']}] {_format_timestamp(s['start_sec'])}  {s['text']}")
    return "\n".join(lines)


def _validate_and_clean_beats(beats: List[Dict[str, Any]], sentences_by_idx: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Drop beats with hallucinated indices, invalid types, or invented quotable lines, before
    anything downstream trusts them. A model returning a bad index must not silently produce
    a bad cut.
    """
    valid_indices = set(sentences_by_idx.keys())
    cleaned = []
    for b in beats:
        if not isinstance(b, dict):
            continue
        beat_type = b.get("beat_type")
        start_idx = b.get("start_sentence_idx")
        end_idx = b.get("end_sentence_idx")

        if beat_type not in BEAT_TYPES:
            continue
        if not isinstance(start_idx, int) or not isinstance(end_idx, int):
            continue
        if start_idx not in valid_indices or end_idx not in valid_indices:
            continue
        if start_idx > end_idx:
            continue

        requires = b.get("requires_setup_from_idx")
        if requires is not None:
            if not isinstance(requires, int) or requires not in valid_indices or requires > start_idx:
                requires = None

        quotable = b.get("quotable_line", "") or ""
        if quotable:
            range_text = " ".join(
                sentences_by_idx[i]["text"] for i in range(start_idx, end_idx + 1) if i in sentences_by_idx
            ).lower()
            norm_quotable = re.sub(r"[^a-z0-9 ]", "", quotable.lower()).strip()
            norm_range = re.sub(r"[^a-z0-9 ]", "", range_text)
            if norm_quotable and norm_quotable not in norm_range:
                quotable = ""  # hallucinated — don't propagate a fabricated quote

        cleaned.append({
            "beat_type": beat_type,
            "start_sentence_idx": start_idx,
            "end_sentence_idx": end_idx,
            "requires_setup_from_idx": requires,
            "title": str(b.get("title", "") or "")[:120],
            "why_it_lands": str(b.get("why_it_lands", "") or "")[:400],
            "emotional_arc": b.get("emotional_arc") if isinstance(b.get("emotional_arc"), dict) else {},
            "self_contained": bool(b.get("self_contained", requires is None)),
            "quotable_line": quotable,
        })
    return cleaned


def extract_beats(sentences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    LLM-backed beat extraction. Raises llm_client.LLMUnavailable if no key is configured or
    the provider fails even after retry — callers should fall back to heuristic_beats().
    """
    if not sentences:
        return []

    sentences_by_idx = {s["sentence_idx"]: s for s in sentences}
    total_words = sum(len(s["text"].split()) for s in sentences)

    if total_words <= WORD_COUNT_WINDOW_THRESHOLD or len(sentences) <= WINDOW_SENTENCE_COUNT:
        windows = [sentences]
    else:
        windows = []
        step = WINDOW_SENTENCE_COUNT - WINDOW_OVERLAP
        for start in range(0, len(sentences), step):
            windows.append(sentences[start:start + WINDOW_SENTENCE_COUNT])
            if start + WINDOW_SENTENCE_COUNT >= len(sentences):
                break

    all_beats: List[Dict[str, Any]] = []
    for window in windows:
        transcript_text = _format_transcript_window(window)
        raw = llm_client.complete_json(_SYSTEM_PROMPT, transcript_text, _BEAT_SCHEMA)
        if isinstance(raw, dict):
            raw = raw.get("beats", [])
        all_beats.extend(raw if isinstance(raw, list) else [])

    cleaned = _validate_and_clean_beats(all_beats, sentences_by_idx)
    return _dedupe_beats(cleaned)


def _dedupe_beats(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Windowed extraction can produce the same beat twice (from overlapping windows) —
    collapse beats whose sentence ranges overlap and share a beat_type, keeping the first."""
    deduped: List[Dict[str, Any]] = []
    for b in sorted(beats, key=lambda x: x["start_sentence_idx"]):
        is_dup = False
        for existing in deduped:
            if existing["beat_type"] != b["beat_type"]:
                continue
            overlap = min(existing["end_sentence_idx"], b["end_sentence_idx"]) - \
                max(existing["start_sentence_idx"], b["start_sentence_idx"]) + 1
            if overlap > 0:
                is_dup = True
                break
        if not is_dup:
            deduped.append(b)
    return deduped


# --- Degraded (heuristic) mode ---------------------------------------------------------

_DISCOURSE_MARKERS = [
    "but then", "here's the thing", "what nobody tells you", "turns out",
    "and then", "the truth is", "what i realized", "looking back",
    "here's what happened", "little did i know", "the crazy part",
]

_QUESTION_WORDS = ("what", "why", "how", "when", "where", "who", "which")


def heuristic_beats(sentences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Degraded-mode beat extraction used when no LLM key is configured or the provider is
    unavailable (ENGINE-PLAN.md Phase 2.4). Weaker than LLM extraction but always available,
    mirroring the cross-encoder fallback pattern already in vector_store.py's search().

    Uses: question -> answer sentence pairing, discourse markers, and simple position
    heuristics (first sentence as hook, sentences following a discourse marker as payoff).
    """
    if not sentences:
        return []

    beats = []
    ordered = sorted(sentences, key=lambda s: s["sentence_idx"])

    # First sentence of the transcript: candidate hook.
    beats.append({
        "beat_type": "hook",
        "start_sentence_idx": ordered[0]["sentence_idx"],
        "end_sentence_idx": ordered[0]["sentence_idx"],
        "requires_setup_from_idx": None,
        "title": "Opening line",
        "why_it_lands": "First line of the transcript — candidate cold open.",
        "emotional_arc": {},
        "self_contained": True,
        "quotable_line": ordered[0]["text"],
    })

    for i, s in enumerate(ordered):
        text_lower = s["text"].lower()

        # Question -> answer pairing.
        stripped = text_lower.strip()
        if stripped.endswith("?") or any(stripped.startswith(q) for q in _QUESTION_WORDS):
            if i + 1 < len(ordered):
                answer = ordered[i + 1]
                beats.append({
                    "beat_type": "payoff",
                    "start_sentence_idx": s["sentence_idx"],
                    "end_sentence_idx": answer["sentence_idx"],
                    "requires_setup_from_idx": s["sentence_idx"],
                    "title": "Question and answer",
                    "why_it_lands": "A posed question immediately answered.",
                    "emotional_arc": {},
                    "self_contained": False,
                    "quotable_line": answer["text"],
                })

        # Discourse markers signal a turn — the sentence containing one, plus the one
        # before it as required setup context.
        for marker in _DISCOURSE_MARKERS:
            if marker in text_lower:
                setup_idx = ordered[i - 1]["sentence_idx"] if i > 0 else s["sentence_idx"]
                beats.append({
                    "beat_type": "turning_point",
                    "start_sentence_idx": s["sentence_idx"],
                    "end_sentence_idx": s["sentence_idx"],
                    "requires_setup_from_idx": setup_idx,
                    "title": "Turning point",
                    "why_it_lands": f"Discourse marker '{marker}' signals a narrative turn.",
                    "emotional_arc": {},
                    "self_contained": False,
                    "quotable_line": s["text"],
                })
                break

    return _dedupe_beats(beats)


# --- Beats -> clip candidates (the constraint solver) -----------------------------------

def _duration_sec(sentences_by_idx: Dict[int, Dict[str, Any]], start_idx: int, end_idx: int) -> float:
    return sentences_by_idx[end_idx]["end_sec"] - sentences_by_idx[start_idx]["start_sec"]


def _covering_beat(all_beats: List[Dict[str, Any]], idx: int) -> Optional[Dict[str, Any]]:
    for b in all_beats:
        if b["start_sentence_idx"] <= idx <= b["end_sentence_idx"]:
            return b
    return None


def _build_candidate_for_seed(
    seed: Dict[str, Any],
    all_beats: List[Dict[str, Any]],
    sentences_by_idx: Dict[int, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Expand `seed` (a payoff-class beat) backward to satisfy its dependency chain, forward to
    its own end, then enforce the duration bounds without ever relaxing a directly-required
    setup (ENGINE-PLAN.md Phase 2.3 — this is the guarantee the whole design rests on).
    """
    valid_indices = sentences_by_idx.keys()
    if seed["start_sentence_idx"] not in valid_indices or seed["end_sentence_idx"] not in valid_indices:
        return None

    # Depth-1 (direct) requirement: never relaxed under any circumstance.
    direct_start = seed["start_sentence_idx"]
    if seed.get("requires_setup_from_idx") is not None:
        direct_start = min(direct_start, seed["requires_setup_from_idx"])

    # Deeper (transitive) requirements: satisfied when they fit, dropped first if the clip
    # runs long. Chase the chain with a visited guard so a malformed cycle can't loop forever.
    transitive_start = direct_start
    hard_required_beats = [seed]
    frontier = [seed]
    visited_ids = {id(seed)}
    guard = 0
    while frontier and guard < len(all_beats) + 2:
        guard += 1
        current = frontier.pop()
        req = current.get("requires_setup_from_idx")
        if req is None:
            continue
        transitive_start = min(transitive_start, req)
        covering = _covering_beat(all_beats, req)
        if covering is not None and id(covering) not in visited_ids:
            visited_ids.add(id(covering))
            hard_required_beats.append(covering)
            frontier.append(covering)

    end_idx = seed["end_sentence_idx"]

    # Direct-only fallback keeps just the beat that covers the seed's own requirement (if
    # any) — the deeper (grandparent) chain is what gets dropped to save duration.
    direct_covering = None
    if seed.get("requires_setup_from_idx") is not None:
        direct_covering = _covering_beat(all_beats, seed["requires_setup_from_idx"])
    direct_required_beats = [seed] + ([direct_covering] if direct_covering is not None else [])

    for candidate_start, included_beats in (
        (transitive_start, hard_required_beats),
        (direct_start, direct_required_beats),
    ):
        if candidate_start not in valid_indices:
            continue
        duration = _duration_sec(sentences_by_idx, candidate_start, end_idx)
        if duration < MIN_CLIP_SEC:
            continue
        if duration <= MAX_CLIP_SEC:
            start_sec = sentences_by_idx[candidate_start]["start_sec"]
            end_sec = sentences_by_idx[end_idx]["end_sec"]
            return {
                "start_sentence_idx": candidate_start,
                "end_sentence_idx": end_idx,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "beats": included_beats,
                "seed_beat": seed,
                "title": seed.get("title") or "Untitled clip",
                "quotable_line": seed.get("quotable_line", ""),
            }

    # Neither the fully-satisfied nor the direct-only window fits within [MIN, MAX] — the
    # candidate cannot be safely trimmed further without violating its dependency chain, so
    # it must not be emitted. Fewer clips beats a broken one.
    return None


def _sentence_overlap_fraction(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    a_start, a_end = a["start_sentence_idx"], a["end_sentence_idx"]
    b_start, b_end = b["start_sentence_idx"], b["end_sentence_idx"]
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start) + 1)
    union = (a_end - a_start + 1) + (b_end - b_start + 1) - overlap
    return overlap / union if union > 0 else 0.0


def _merge_overlapping_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge candidates overlapping >60% by sentence count, keeping the richer one (more
    contained beats — a cheap proxy for quality before clip_scoring's real composite score
    exists, since scoring runs on the surviving candidate set afterward)."""
    kept: List[Dict[str, Any]] = []
    for cand in sorted(candidates, key=lambda c: c["start_sentence_idx"]):
        merged_into_existing = False
        for i, existing in enumerate(kept):
            if _sentence_overlap_fraction(existing, cand) > 0.6:
                if len(cand["beats"]) > len(existing["beats"]):
                    kept[i] = cand
                merged_into_existing = True
                break
        if not merged_into_existing:
            kept.append(cand)
    return kept


def beats_to_candidates(sentences: List[Dict[str, Any]], beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Turn beats into clip candidates. Seeds on payoff-class beats (punchline, confession,
    turning_point, lesson, payoff) since a clip without a payoff isn't a clip.
    """
    if not sentences or not beats:
        return []

    sentences_by_idx = {s["sentence_idx"]: s for s in sentences}
    seeds = [b for b in beats if b["beat_type"] in PAYOFF_BEAT_TYPES]

    candidates = []
    for seed in seeds:
        cand = _build_candidate_for_seed(seed, beats, sentences_by_idx)
        if cand is not None:
            candidates.append(cand)

    return _merge_overlapping_candidates(candidates)


def analyze_video(sentences: List[Dict[str, Any]], max_clips: int = 6) -> Dict[str, Any]:
    """
    Top-level orchestration: try LLM beat extraction, fall back to heuristic mode on any
    failure, then run the constraint solver. Returns beats/candidates/degraded — ranking
    and truncation to max_clips happens in clip_scoring.rank(), called by the API layer.
    """
    degraded = False
    beats: List[Dict[str, Any]] = []

    if llm_client.is_configured():
        try:
            beats = extract_beats(sentences)
        except llm_client.LLMUnavailable:
            degraded = True
    else:
        degraded = True

    if not beats:
        beats = heuristic_beats(sentences)
        degraded = True

    candidates = beats_to_candidates(sentences, beats)
    return {"beats": beats, "candidates": candidates, "degraded": degraded}
