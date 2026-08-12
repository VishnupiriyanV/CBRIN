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
from typing import Any, Callable, Dict, List, Optional

import llm_client
import reference_resolver
import topic_segmenter

# (start_sec, end_sec) -> [0, 1] rating of how cleanly a window's edges land on real pauses.
# Injected rather than imported so this module stays free of video_id and the filesystem —
# build one with clip_scoring.make_boundary_scorer(video_id).
BoundaryScorer = Callable[[float, float], float]

# sentences -> topic-coherent runs of sentences. Injected rather than imported so this module
# keeps no dependency on the embedding model or the filesystem — build one with
# topic_segmenter.make_segmenter().
Segmenter = Callable[[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]

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

# 60 sentences can plausibly carry ~15 beats at ~120 tokens of JSON each, plus headroom —
# without this, a long window's response could get silently truncated mid-JSON, which
# surfaces as a JSONDecodeError indistinguishable from a real provider failure.
BEAT_MAX_TOKENS = 4000
BEAT_TEMPERATURE = 0.2

_SYSTEM_PROMPT = """You are analyzing a spoken video transcript to find its narrative beats — \
the structural moments that make a clip land: hooks, setups, punchlines, confessions, \
turning points, lessons, payoffs, calls-to-action, and tangents to skip.

For each beat you identify, output an object with these exact fields:
- beat_type: one of hook, setup, punchline, confession, turning_point, lesson, payoff, cta, tangent
- start_sentence_idx: integer, the [N] index of the first sentence of this beat
- end_sentence_idx: integer, the [N] index of the last sentence of this beat
- requires_setup_from_idx: integer or null — if this beat only makes sense with earlier \
context, the [N] index where that required context begins. null if self-contained. This may \
point at a line in an EARLIER IN THIS TRANSCRIPT section if one is shown, not only at the \
current section — a callback to something set up much earlier is exactly what this field is \
for.
- title: short human-readable label for this beat
- why_it_lands: one sentence explaining why this moment works
- emotional_arc: {"opening": str, "peak": str, "closing": str} — one or two words each
- self_contained: boolean — does this beat make sense without anything before it?
- quotable_line: the single most quotable sentence from this beat, copied verbatim

Respond with ONLY a JSON object of the form {"beats": [...]}. No prose, no markdown fences."""

# Matches what _SYSTEM_PROMPT actually asks for — an object with a "beats" array. This used to
# be {"type": "array", ...}, which only worked because llm_client.complete_json's object->array
# unwrap heuristic happened to fall through to "pick the longest list value" and guess right.
# Declaring the real shape means validation failure is diagnosable instead of a guess away from
# silently misparsing.
_BEAT_SCHEMA = {
    "type": "object",
    "required": ["beats"],
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


def _sliding_windows(sentences: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Fixed-size windows with overlap — the original scheme, now the degraded-mode path used
    when no segmenter is available or segmentation returns nothing usable."""
    windows = []
    step = max(WINDOW_SENTENCE_COUNT - WINDOW_OVERLAP, 1)
    for start in range(0, len(sentences), step):
        windows.append(sentences[start:start + WINDOW_SENTENCE_COUNT])
        if start + WINDOW_SENTENCE_COUNT >= len(sentences):
            break
    return windows


def _pack_segments(segments: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
    """
    Fill windows with whole topic segments, up to WINDOW_SENTENCE_COUNT.

    No overlap, unlike the sliding scheme. Overlap existed to stop a beat being lost across an
    ARBITRARY cut; these cuts are chosen to fall where the transcript changes subject, so a
    beat spanning one is what the segmentation says shouldn't happen. The cross-segment
    context header is the better safety net anyway — it lets the model see and point at
    earlier material instead of only re-reading the last ten sentences of it.

    A single segment larger than a window is split by the sliding scheme; segmentation cannot
    be allowed to produce a window the provider will reject.
    """
    windows: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []

    for segment in segments:
        if len(segment) > WINDOW_SENTENCE_COUNT:
            if current:
                windows.append(current)
                current = []
            windows.extend(_sliding_windows(segment))
            continue
        if current and len(current) + len(segment) > WINDOW_SENTENCE_COUNT:
            windows.append(current)
            current = []
        current.extend(segment)

    if current:
        windows.append(current)
    return windows


def _plan_windows(
    sentences: List[Dict[str, Any]], segmenter: Optional[Segmenter] = None
) -> "tuple[List[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]":
    """
    Returns (windows, segments).

    `segments` is the topic structure the windows were built from, or [] when the transcript
    was small enough to pass whole or segmentation was unavailable. Callers use it to build
    the cross-segment context header.
    """
    total_words = sum(len(s["text"].split()) for s in sentences)
    if total_words <= WORD_COUNT_WINDOW_THRESHOLD or len(sentences) <= WINDOW_SENTENCE_COUNT:
        return [sentences], []

    if segmenter is not None:
        try:
            segments = segmenter(sentences)
        except Exception as e:
            print(f"[NarrativeEngine] Topic segmentation failed ({e}); falling back to fixed windows.")
            segments = None
        if segments and len(segments) > 1:
            return _pack_segments(segments), segments

    return _sliding_windows(sentences), []


def _windows_for(
    sentences: List[Dict[str, Any]], segmenter: Optional[Segmenter] = None
) -> List[List[Dict[str, Any]]]:
    return _plan_windows(sentences, segmenter)[0]


_CONTEXT_HEADER_INTRO = (
    "EARLIER IN THIS TRANSCRIPT — for reference only. Do NOT create beats from these lines. "
    "They exist so that if a beat in the current section only makes sense with one of them, "
    "you can point requires_setup_from_idx at the [N] index where that context begins.\n"
)


def _context_header(
    segments: List[List[Dict[str, Any]]], first_idx: int, max_lines: int = 40
) -> str:
    """
    A compact digest of every topic segment that ended before `first_idx`.

    This is what makes a long-range dependency expressible at all. With fixed 60-sentence
    windows, a payoff at sentence 340 whose setup sits at sentence 12 was structurally
    invisible: no window held both, so no call could emit that requires_setup_from_idx, and
    the solver's guarantee silently reduced to "within any 60 consecutive sentences".

    Costs one short line per prior segment rather than re-sending the transcript. Capped at
    `max_lines` (keeping the MOST RECENT, which are the likeliest referents) so the header
    cannot grow without bound on a feature-length transcript.
    """
    lines = []
    for segment in segments:
        if not segment or segment[-1]["sentence_idx"] >= first_idx:
            continue
        gist = topic_segmenter.summarise_segment(segment)
        if gist:
            lines.append(f"[{segment[0]['sentence_idx']}-{segment[-1]['sentence_idx']}] {gist}")

    if not lines:
        return ""
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return _CONTEXT_HEADER_INTRO + "\n".join(lines) + "\n\nCURRENT SECTION:\n"


def _extract_beats_for_window(
    window: List[Dict[str, Any]], allow_split: bool = True, context_header: str = ""
) -> "tuple[List[Dict[str, Any]], Dict[str, Any]]":
    """Runs one window through the LLM. On a context-length failure — the one failure mode
    that's deterministic rather than transient, so a plain retry on the same window would
    fail identically — splits the window in half once and merges the two halves' beats and
    usage. `allow_split=False` on the recursive calls caps this at a single split.

    `context_header` digests the topic segments preceding this window so a beat can declare a
    dependency on material outside it (see _context_header)."""
    transcript_text = context_header + _format_transcript_window(window)
    try:
        parsed, usage = llm_client.complete_json_with_usage(
            _SYSTEM_PROMPT, transcript_text, _BEAT_SCHEMA,
            max_tokens=BEAT_MAX_TOKENS, temperature=BEAT_TEMPERATURE,
        )
    except llm_client.LLMUnavailable as e:
        if allow_split and llm_client.is_context_length_error(str(e)) and len(window) > 1:
            mid = len(window) // 2
            # Drop the context header on the retry: it is the one part of the payload that is
            # optional, and this failure means the payload was already too large.
            beats_a, usage_a = _extract_beats_for_window(window[:mid], allow_split=False)
            beats_b, usage_b = _extract_beats_for_window(window[mid:], allow_split=False)
            merged_usage = {
                "prompt_tokens": usage_a.get("prompt_tokens", 0) + usage_b.get("prompt_tokens", 0),
                "completion_tokens": usage_a.get("completion_tokens", 0) + usage_b.get("completion_tokens", 0),
                "model": usage_b.get("model") or usage_a.get("model"),
            }
            return beats_a + beats_b, merged_usage
        raise
    beats = parsed.get("beats") if isinstance(parsed, dict) else parsed
    return (beats if isinstance(beats, list) else []), usage


def extract_beats_with_report(
    sentences: List[Dict[str, Any]], segmenter: Optional[Segmenter] = None
) -> "tuple[List[Dict[str, Any]], Dict[str, Any]]":
    """
    Windowed LLM beat extraction that tolerates per-window failure.

    A single LLMUnavailable from one window used to discard every beat successfully
    extracted from every OTHER window (6 good windows + 1 rate-limited window == full
    heuristic fallback for the whole video) — each window is now wrapped individually, and
    LLMUnavailable is raised only if EVERY window failed.

    Returns (beats, report) where report carries windows_total/windows_ok/windows_failed/
    errors/model/prompt_tokens/completion_tokens — the honest record analyze_video's
    degraded/degraded_reason/mode fields are derived from, instead of the old approach of
    inferring "did the LLM run" from key presence alone.
    """
    empty_report = {
        "windows_total": 0, "windows_ok": 0, "windows_failed": 0, "errors": [],
        "model": llm_client.get_model(), "prompt_tokens": 0, "completion_tokens": 0,
    }
    if not sentences:
        return [], empty_report

    sentences_by_idx = {s["sentence_idx"]: s for s in sentences}
    windows, segments = _plan_windows(sentences, segmenter)

    all_beats: List[Dict[str, Any]] = []
    errors: List[str] = []
    windows_ok = 0
    report_model = llm_client.get_model()
    prompt_tokens = 0
    completion_tokens = 0

    for window in windows:
        try:
            header = _context_header(segments, window[0]["sentence_idx"]) if window else ""
            beats_for_window, usage = _extract_beats_for_window(window, context_header=header)
            all_beats.extend(beats_for_window)
            windows_ok += 1
            report_model = usage.get("model") or report_model
            prompt_tokens += usage.get("prompt_tokens", 0) or 0
            completion_tokens += usage.get("completion_tokens", 0) or 0
        except llm_client.LLMUnavailable as e:
            errors.append(str(e))

    report = {
        "windows_total": len(windows),
        "windows_ok": windows_ok,
        "windows_failed": len(windows) - windows_ok,
        "errors": errors,
        "segments": len(segments),
        "segmented": bool(segments),
        "model": report_model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }

    if windows_ok == 0:
        raise llm_client.LLMUnavailable(
            f"LLM beat extraction failed for all {len(windows)} transcript window(s): "
            + "; ".join(errors[:3])
        )

    cleaned = _validate_and_clean_beats(all_beats, sentences_by_idx)
    return _dedupe_beats(cleaned), report


def extract_beats(
    sentences: List[Dict[str, Any]], segmenter: Optional[Segmenter] = None
) -> List[Dict[str, Any]]:
    """
    LLM-backed beat extraction. Raises llm_client.LLMUnavailable if every transcript window
    fails — callers should fall back to heuristic_beats(). Thin wrapper around
    extract_beats_with_report() for callers (e.g. backend/eval/clip_eval.py) that only need
    the beats, not the extraction report.
    """
    beats, _report = extract_beats_with_report(sentences, segmenter)
    return beats


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


HOOK_PREFERRED_TYPES = ("hook", "confession", "turning_point")


def _covering_beat_type(all_beats: List[Dict[str, Any]], idx: int) -> Optional[str]:
    """Beat type covering `idx`, preferring 'hook' (then confession/turning_point) when
    several beats overlap it — a clip's opening sentence is frequently inside both a setup
    beat and a hook beat, and _covering_beat returns whichever comes first in list order
    (usually the setup), which is the wrong one for clip_scoring's beat_bonus."""
    covering_types = [
        b["beat_type"] for b in all_beats
        if b["start_sentence_idx"] <= idx <= b["end_sentence_idx"]
    ]
    if not covering_types:
        return None
    for t in HOOK_PREFERRED_TYPES:
        if t in covering_types:
            return t
    return covering_types[0]


def _build_candidate_for_seed(
    seed: Dict[str, Any],
    all_beats: List[Dict[str, Any]],
    sentences_by_idx: Dict[int, Dict[str, Any]],
    boundary_scorer: Optional[BoundaryScorer] = None,
    referential_deps: Optional[Dict[int, int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Expand `seed` (a payoff-class beat) backward to satisfy its dependency chain, forward to
    its own end, then enforce the duration bounds without ever relaxing a directly-required
    setup (ENGINE-PLAN.md Phase 2.3 — this is the guarantee the whole design rests on).

    Expansion happens in three passes, in this order for a reason:
      1. narrative dependencies  — hard, never relaxed
      2. referential dependencies — soft, relaxed only against MAX_CLIP_SEC
      3. pause alignment          — a preference, taken only when it changes nothing above
    Correctness first, then comprehensibility, then polish. Running 3 before 2 would let a
    cosmetic boundary preference decide whether a pronoun resolves.
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
        referential_start = _extend_for_references(
            sentences_by_idx, candidate_start, end_idx, referential_deps,
        )
        selected = _select_bounds(sentences_by_idx, referential_start, end_idx, boundary_scorer)
        if selected is not None:
            chosen_start, chosen_end, boundary_info = selected
            # None, not [], when references were never resolved. An empty list is a claim —
            # "we checked and nothing escapes this clip" — and reporting it for a run that
            # never looked would be the same unverified assertion this feature exists to
            # remove, just with our name on it instead of the LLM's.
            dangling = (
                reference_resolver.dangling_indices(referential_deps, chosen_start, chosen_end)
                if referential_deps is not None else None
            )
            start_sec = sentences_by_idx[chosen_start]["start_sec"]
            end_sec = sentences_by_idx[chosen_end]["end_sec"]
            return {
                "start_sentence_idx": chosen_start,
                "end_sentence_idx": chosen_end,
                "boundary_selection": boundary_info,
                # The literal sentences that still point outside the clip. Empty is the claim
                # worth making out loud: nothing in this clip refers to unseen material.
                "dangling_reference_indices": dangling,
                "references_expanded_by": candidate_start - referential_start,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "beats": included_beats,
                "seed_beat": seed,
                "title": seed.get("title") or "Untitled clip",
                "quotable_line": seed.get("quotable_line", ""),
                # Computed against chosen_start — the exact sentence clip_scoring.rank()
                # scores as the opening (clip_scoring.py's opening_idx = start_sentence_idx)
                # — so clip_scoring's hook beat_bonus and the text it actually scores now
                # refer to the same sentence. Before this existed, the bonus looked for a
                # "hook"-typed beat inside `beats` (included_beats above), but that list can
                # structurally never contain one: beats_to_candidates seeds candidates only
                # on PAYOFF_BEAT_TYPES, and this function only ever adds the seed plus its
                # own setup chain — so the bonus could essentially never fire.
                #
                # Must be chosen_start, not candidate_start: pause alignment can move the
                # in-point earlier, and reading the beat type off the pre-alignment index
                # would reintroduce exactly the mismatch this field was added to remove.
                "opening_beat_type": _covering_beat_type(all_beats, chosen_start),
            }

    # Neither the fully-satisfied nor the direct-only window fits within [MIN, MAX] — the
    # candidate cannot be safely trimmed further without violating its dependency chain, so
    # it must not be emitted. Fewer clips beats a broken one.
    return None


# --- Pause-aligned boundary selection ----------------------------------------------------
#
# Sentence boundaries are text-driven (multimodal_engine splits on punctuation and length), so
# they are NOT acoustic boundaries. Measured over the real corpus, 49% of sentence starts have
# no recorded pause before them at all (percentile table in clip_scoring above
# BOUNDARY_PAUSE_TARGET_SEC). Snapping the cut inside a boundary — word_timing.snap_clip_bounds
# — fixes placement, but it cannot turn a mid-phrase boundary into a phrase boundary. Only the
# solver can do that, by preferring a DIFFERENT sentence boundary when it has the slack.
#
# The search is expansion-only and therefore dependency-safe by construction: the in-point may
# move earlier (which adds context and can never drop a required setup) and the out-point may
# move later (the payoff stays in). Neither direction can violate the guarantee this module
# exists to make, so pause alignment is not traded off against it at any point.
#
# Asymmetric limits: leading context is usually harmless and often helpful, whereas material
# after the payoff is more likely to be dead weight, so the out-point gets less rope.
PAUSE_SEARCH_START_SENTENCES = 3
PAUSE_SEARCH_END_SENTENCES = 2

# A wider clip has a real cost, so only take one for a materially better boundary. Against the
# 0.6s pause target this is roughly 0.18s of additional pause on one edge — comfortably above
# the noise in Whisper's word timings, which are quantised to hundredths.
MIN_BOUNDARY_GAIN = 0.15


# A referential dependency can itself land on a sentence that opens with an anaphor, so
# expansion iterates. Bounded so a transcript where every sentence starts with a pronoun walks
# back a fixed distance rather than to sentence zero. In practice the duration bound below
# stops it first.
MAX_REFERENCE_EXPANSION_STEPS = 8


def _extend_for_references(
    sentences_by_idx: Dict[int, Dict[str, Any]],
    start_idx: int,
    end_idx: int,
    referential_deps: Optional[Dict[int, int]],
) -> int:
    """
    Pull the in-point back until no sentence in range refers to something outside it.

    Soft, unlike `requires_setup_from_idx`. A narrative dependency is never relaxed — a clip
    that cuts a punchline from its setup is simply wrong. A referential one is relaxed when
    satisfying it would breach MAX_CLIP_SEC, because almost every spoken sentence carries some
    anaphor and hard-failing on them would reject nearly every candidate. What survives the
    relaxation is reported honestly: clip_scoring reads the residual dangling count off
    `dangling_reference_indices` instead of guessing.
    """
    if not referential_deps:
        return start_idx

    current = start_idx
    for _ in range(MAX_REFERENCE_EXPANSION_STEPS):
        needed = current
        for idx in range(current, end_idx + 1):
            dep = referential_deps.get(idx)
            if dep is not None and dep < needed:
                needed = dep
        if needed >= current:
            return current
        if needed not in sentences_by_idx:
            return current
        if _duration_sec(sentences_by_idx, needed, end_idx) > MAX_CLIP_SEC:
            # Cannot reach the antecedent without breaking the duration bound. Stop here and
            # let the residual be counted rather than silently pretending it resolved.
            return current
        current = needed
    return current


def _select_bounds(
    sentences_by_idx: Dict[int, Dict[str, Any]],
    required_start: int,
    required_end: int,
    boundary_scorer: Optional[BoundaryScorer],
) -> "Optional[tuple[int, int, Dict[str, Any]]]":
    """
    Pick the (start_idx, end_idx) that satisfies the duration bounds and lands on the cleanest
    available pause. Returns (start, end, info) or None if the required window doesn't fit.

    The tight window (required_start, required_end) must clear [MIN, MAX] on its own — exactly
    as before this function existed. Expansion is for boundary QUALITY only, never to reach
    MIN_CLIP_SEC: padding a short candidate with filler sentences to make the minimum would
    contradict "fewer clips beats a broken one" below, and would quietly turn a rejected clip
    into a bad one.

    With boundary_scorer=None this is byte-for-byte the old behaviour — the tight window, or
    nothing.
    """
    duration = _duration_sec(sentences_by_idx, required_start, required_end)
    if duration < MIN_CLIP_SEC or duration > MAX_CLIP_SEC:
        return None

    no_change = {"pause_aligned": False, "boundary_gain": 0.0, "sentences_added": 0}
    if boundary_scorer is None:
        return required_start, required_end, no_change

    def score(s: int, e: int) -> float:
        return boundary_scorer(sentences_by_idx[s]["start_sec"], sentences_by_idx[e]["end_sec"])

    base_score = score(required_start, required_end)
    best_score, best_expansion = base_score, 0
    best_start, best_end = required_start, required_end

    valid = sentences_by_idx.keys()
    starts = [required_start - k for k in range(PAUSE_SEARCH_START_SENTENCES + 1) if required_start - k in valid]
    ends = [required_end + k for k in range(PAUSE_SEARCH_END_SENTENCES + 1) if required_end + k in valid]

    for s in starts:
        for e in ends:
            if s == required_start and e == required_end:
                continue
            d = _duration_sec(sentences_by_idx, s, e)
            if d < MIN_CLIP_SEC or d > MAX_CLIP_SEC:
                continue
            candidate_score = score(s, e)
            if candidate_score < base_score + MIN_BOUNDARY_GAIN:
                continue
            expansion = (required_start - s) + (e - required_end)
            # Best boundary wins; the tightest clip breaks ties, so we never widen further
            # than the improvement actually requires.
            if (candidate_score, -expansion) > (best_score, -best_expansion):
                best_score, best_expansion = candidate_score, expansion
                best_start, best_end = s, e

    if best_expansion == 0:
        return required_start, required_end, no_change
    return best_start, best_end, {
        "pause_aligned": True,
        "boundary_gain": round(best_score - base_score, 4),
        "sentences_added": best_expansion,
    }


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


def beats_to_candidates(
    sentences: List[Dict[str, Any]],
    beats: List[Dict[str, Any]],
    boundary_scorer: Optional[BoundaryScorer] = None,
    resolve_references: bool = True,
) -> List[Dict[str, Any]]:
    """
    Turn beats into clip candidates. Seeds on payoff-class beats (punchline, confession,
    turning_point, lesson, payoff) since a clip without a payoff isn't a clip.

    `resolve_references` computes referential dependencies (reference_resolver) from the same
    sentence list and satisfies them by backward expansion, so a candidate does not open on a
    pronoun whose antecedent it excluded. Unlike `boundary_scorer` this needs no external data
    — the text is already here — so it defaults on. Pass False to isolate the narrative
    constraint in a test.

    `boundary_scorer` is an optional callable (start_sec, end_sec) -> float in [0, 1] rating
    how cleanly a window's edges land on real pauses — build one with
    clip_scoring.make_boundary_scorer(video_id). It is injected rather than imported so this
    module stays pure: no video_id, no filesystem, and its tests keep passing sentence dicts
    alone. Omit it and boundary selection is exactly the old first-fit behaviour.
    """
    if not sentences or not beats:
        return []

    sentences_by_idx = {s["sentence_idx"]: s for s in sentences}
    seeds = [b for b in beats if b["beat_type"] in PAYOFF_BEAT_TYPES]

    referential_deps = (
        reference_resolver.referential_dependencies(sentences) if resolve_references else None
    )

    candidates = []
    for seed in seeds:
        cand = _build_candidate_for_seed(
            seed, beats, sentences_by_idx, boundary_scorer, referential_deps,
        )
        if cand is not None:
            candidates.append(cand)

    return _merge_overlapping_candidates(candidates)


def analyze_video(
    sentences: List[Dict[str, Any]],
    max_clips: int = 6,
    boundary_scorer: Optional[BoundaryScorer] = None,
    segmenter: Optional[Segmenter] = None,
) -> Dict[str, Any]:
    """
    Top-level orchestration: try LLM beat extraction, fall back to heuristic mode on any
    failure, then run the constraint solver.

    Returns {beats, candidates, degraded, mode, degraded_reason, extraction}:
      mode: "llm" (every window succeeded) | "llm_partial" (some windows failed, but at
            least one succeeded — real LLM beats plus a documented gap) | "heuristic"
            (no key configured, or every window failed).
      degraded: True unless mode == "llm" — computed from what ACTUALLY happened during
                extraction, never from key presence alone. The old version set this once
                from is_configured() before extraction even ran and never updated it when
                extract_beats threw (the exception was just print()'d) — so heuristic beats
                could be persisted with degraded=False and the UI never warned. Proof this
                happened for real: backend/data/clips.json had 8 clips, all degraded=false,
                yet 6 carried titles ("Question and answer", "Turning point") that only
                heuristic_beats() ever produces.
      degraded_reason: one honest sentence for the UI, or None when mode == "llm".
      extraction: the report dict from extract_beats_with_report(), or None if the LLM was
                  never attempted (no key configured).
    """
    beats: List[Dict[str, Any]] = []
    mode = "heuristic"
    degraded_reason = None
    extraction = None

    if llm_client.is_configured():
        try:
            beats, extraction = extract_beats_with_report(sentences, segmenter)
            if extraction["windows_failed"] == 0:
                mode = "llm"
            else:
                mode = "llm_partial"
                degraded_reason = (
                    f"LLM analyzed {extraction['windows_ok']} of {extraction['windows_total']} "
                    f"transcript window(s); {extraction['windows_failed']} failed. Beats from "
                    f"part of the transcript may be missing."
                )
        except llm_client.LLMUnavailable as e:
            print(f"[NarrativeEngine] LLM beat extraction failed for every window: {e}")
            degraded_reason = (
                f"LLM beat extraction failed for every transcript window ({e}) — "
                f"beats came from heuristic detection instead."
            )
    else:
        degraded_reason = (
            "No LLM key configured (VAULT_LLM_API_KEY) — beats came from heuristic detection."
        )

    if not beats:
        beats = heuristic_beats(sentences)
        mode = "heuristic"
        if degraded_reason is None:
            degraded_reason = "LLM returned no usable beats — beats came from heuristic detection."

    print(f"[NarrativeEngine] beats mode={mode} "
          f"windows={(extraction or {}).get('windows_ok', '-')}/{(extraction or {}).get('windows_total', '-')} "
          f"model={(extraction or {}).get('model', llm_client.get_model())}")

    candidates = beats_to_candidates(sentences, beats, boundary_scorer)
    return {
        "beats": beats,
        "candidates": candidates,
        "degraded": mode != "llm",
        "mode": mode,
        "degraded_reason": degraded_reason,
        "extraction": extraction,
    }
