"""
Five explainable, named signals for ranking clip candidates — a weighted sum, displayed as
a breakdown. No fabricated "predicted engagement %" anywhere (ENGINE-PLAN.md: the Lens layer
with real performance data doesn't exist in this repo; IMPROVEMENT-PLAN.md 2.3 already killed
one fake confidence number for exactly this reason).

Ties break deterministically on (composite, -start_sec, candidate id) so repeated runs on
the same input produce a stable order — backend/eval/clip_eval.py depends on that.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import word_timing
from multimodal_engine import MultimodalEngine, STOPWORDS

WEIGHTS = {
    "hook_strength": 0.25,
    "self_containedness": 0.20,
    "emotional_delta": 0.20,
    "quotability": 0.20,
    "boundary_cleanliness": 0.15,
}

# Bundled hook archetypes for the semantic half of hook_strength — not specific to any one
# creator's content, just generically "hook-shaped" openers.
HOOK_ARCHETYPES = [
    "Here's a mistake almost everyone makes.",
    "I used to believe this until I found out the truth.",
    "Nobody tells you this before you start.",
    "This changed the way I think about everything.",
    "You won't believe what happened next.",
    "The one thing that actually worked.",
]

_DEIXIS_TERMS = {"that", "this", "these", "those", "it", "he", "she", "they", "him", "her", "them"}
_DEIXIS_PHRASES = ["as i said", "like i mentioned", "as we discussed", "going back to"]

MIN_LABELS_FOR_TASTE = 10

# --- Hook strength calibration ------------------------------------------------------------
# hook_strength used to score the opening sentence by feeding (archetype, opening_text) pairs
# to cross-encoder/ms-marco-MiniLM-L-6-v2 — a query->passage RELEVANCE model — and taking
# sigmoid(max_logit). An ordinary sentence is not a relevant "search result" for the query
# "You won't believe what happened next.", so the logit is strongly negative and the score
# collapses to ~0. Measured on this library's real persisted clips (backend/data/clips.json):
# every clip scored 0.0001-0.0005, i.e. a constant 0% in the UI, on the signal carrying the
# LARGEST weight (0.25) of the five. vector_store.py:39-53 documents the identical
# miscalibration for the same model on the same kind of short spoken-transcript text and
# compensates with an eval-derived threshold; this signal never did.
#
# Replacement: bi-encoder archetype similarity (all-MiniLM-L6-v2 — the model vector_store
# already loads for dense search) blended with explicit lexical hook cues, then mapped
# through a range MEASURED on this library's real corpus, not a textbook (cos+1)/2 (which
# would have compressed the entire real spread into roughly [0.48, 0.71]).
#
# Distribution calibrated 2026-08-05 against backend/data/chunks.json (436 real spoken
# sentences across 4 videos) via `python eval/hook_eval.py --distribution`. Measured
# max-archetype-cosine: p5=0.0615 p50=0.1585 p95=0.2738 p99=0.3514 max=0.4112. Measured
# lexical-cue-blend (this corpus skews toward plain statements — median lexical score is 0.0,
# i.e. most sentences trip no cue at all): p50=0.0 p75=0.20 p95=0.35 p99=0.50. Measured
# correlation between the two raw halves: -0.075 — near-independent, which is a reason to
# blend them (each carries non-redundant evidence).
#
# Weight split calibrated against backend/eval/hook_labels.yaml (50 hand-labeled sentences,
# 10 hook / 40 not) via `python eval/hook_eval.py --labels --ablate {sem,lex}` and a
# brute-force weight sweep checking BOTH acceptance criteria at once (a 0.5/0.5 split scored
# well on AUC alone but had a visibly weaker median gap): sem-only AUC=0.70 delta=+0.04,
# lex-only AUC=0.61 delta=+0.20, sem=0.5/lex=0.5 AUC=0.695 delta=+0.09. sem=0.20/lex=0.80
# clears the median-delta bar (+0.22) while staying close to the best observed AUC (0.67 vs
# 0.70) — the best joint result found, not a config chosen to hit AUC alone.
#
# Honest result, not a clean pass: at 50 labels, no weight split in the swept range (0.0-1.0
# in steps of 0.02) cleared BOTH the 0.70 AUC and +0.20 median-delta bar simultaneously — the
# label set is small and this checkout's corpus is narrow (4 videos, one of them song
# lyrics). sem=0.20/lex=0.80 is the best-supported choice found, not a proven-sufficient one.
# Expanding hook_labels.yaml (more videos, more labels per class, then re-running the sweep)
# before trusting this further is real follow-up work, not a formality — see
# eval/README.md#hook-signal-calibration.
#
# HOOK_RAW_FLOOR/CEIL are the measured p5/p99 of the sem=0.20/lex=0.80 blend over the FULL
# unbiased 436-sentence corpus (p0=-0.004 p5=0.016 p25=0.033 p50=0.070 p75=0.190 p95=0.313
# p99=0.431 p100=0.514) — deliberately NOT computed from hook_labels.yaml's own percentiles,
# since that set is intentionally stratified (over-sampling score extremes for labeling
# diversity) and its percentiles would not represent the true corpus distribution.
#
# Re-run eval/hook_eval.py after touching HOOK_ARCHETYPES or any weight below and confirm the
# --distribution spread still spans roughly [0.0, 1.0] with a median near 0.2-0.3 and under
# ~5% of the corpus saturated at 1.0, AND that --labels delta doesn't regress below ~0.20.
# Don't move these on vibes.
HOOK_SEM_WEIGHT = 0.20   # semantic half — see weight-sweep note above
HOOK_LEX_WEIGHT = 0.80   # lexical half — the higher-precision evidence on this corpus
HOOK_RAW_FLOOR = 0.0164  # measured p5 of the sem=0.20/lex=0.80 blend, over the full corpus
HOOK_RAW_CEIL = 0.4314   # measured p99 of the same blend
HOOK_BEAT_BONUS = 0.15   # applied post-calibration when the opening sentence falls inside a
                         # beat the LLM typed as "hook"; capped by _clamp01 below.
HOOK_LEX_ONLY_CEIL = 0.5  # degraded-mode (no dense model) ceiling — measured p99 of the raw
                          # lexical-cue score alone, used when the semantic half is unavailable.

HOOK_CUE_WEIGHTS = {
    "question": 0.30,       # opener is a wh-/aux-word, or the sentence ends in '?'
    "curiosity_gap": 0.30,  # "secret", "mistake", "truth", "turns out", "here's the/what/why"...
    "second_person": 0.20,  # you / your / yourself
    "superlative": 0.15,    # best/worst/only/never/nobody/always/first...
    "negation": 0.10,       # not/never/don't/stop/avoid/wrong
    "numeral": 0.10,        # any digit
}
HOOK_CUE_WINDOW_WORDS = 15  # cues are evaluated on the first 15 words only

_HOOK_QUESTION_OPENERS = (
    "what", "why", "how", "when", "where", "who", "which",
    "did", "have", "is", "are", "can", "should", "will",
)
_HOOK_SUPERLATIVE_RE = re.compile(
    r"\b(best|worst|biggest|only|never|nobody|no one|everyone|always|most|first|hardest|easiest|fastest)\b"
)
_HOOK_CURIOSITY_RE = re.compile(
    r"\b(secret|mistake|truth|turns out|the thing is|little did|crazy part|actually|realized|surprising|here'?s (the|what|why))\b"
)
_HOOK_NEGATION_RE = re.compile(r"\b(not|never|don'?t|doesn'?t|didn'?t|can'?t|won'?t|stop|avoid|wrong)\b")
_HOOK_SECOND_PERSON_RE = re.compile(r"\b(you|your|yourself|you're|you've|you'll)\b")
_HOOK_NUMERAL_RE = re.compile(r"\d")

# Lazily encoded once per process (not per candidate) — the archetypes never change at runtime.
_ARCHETYPE_MATRIX: Optional[np.ndarray] = None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _archetype_matrix() -> Optional[np.ndarray]:
    """The 6 HOOK_ARCHETYPES encoded once per process. Returns None if the dense embedding
    model isn't available (mirrors _taste_match's HAS_DENSE_MODEL bail below)."""
    global _ARCHETYPE_MATRIX
    if _ARCHETYPE_MATRIX is None:
        from vector_store import EMBEDDING_MODEL, HAS_DENSE_MODEL
        if not HAS_DENSE_MODEL:
            return None
        _ARCHETYPE_MATRIX = EMBEDDING_MODEL.encode(
            HOOK_ARCHETYPES, convert_to_numpy=True, normalize_embeddings=True
        )
    return _ARCHETYPE_MATRIX


def _hook_lexical_cues(opening_text: str) -> Dict[str, float]:
    """Explainable 0/1 cues over the first HOOK_CUE_WINDOW_WORDS words — the higher-precision
    half of hook_strength on this corpus (see the calibration note above WEIGHTS)."""
    lowered = opening_text.lower().strip()
    words = re.findall(r"[a-z0-9']+", lowered)[:HOOK_CUE_WINDOW_WORDS]
    window = " ".join(words)
    is_question = lowered.endswith("?") or (bool(words) and words[0] in _HOOK_QUESTION_OPENERS)
    return {
        "question": 1.0 if is_question else 0.0,
        "curiosity_gap": 1.0 if _HOOK_CURIOSITY_RE.search(window) else 0.0,
        "second_person": 1.0 if _HOOK_SECOND_PERSON_RE.search(window) else 0.0,
        "superlative": 1.0 if _HOOK_SUPERLATIVE_RE.search(window) else 0.0,
        "negation": 1.0 if _HOOK_NEGATION_RE.search(window) else 0.0,
        "numeral": 1.0 if _HOOK_NUMERAL_RE.search(window) else 0.0,
    }


def _hook_strength(candidate: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    """
    Returns (score, cues). `cues` is an explainable per-cue breakdown for the UI/eval — it
    goes on result["signal_details"]["hook_cues"], NOT into `signals`, where any key without
    a matching WEIGHTS entry would KeyError score_candidate's composite sum.
    """
    opening_text = candidate.get("_opening_text", "")
    if not opening_text:
        return 0.5, {}

    cues = _hook_lexical_cues(opening_text)
    lex_raw = min(1.0, sum(HOOK_CUE_WEIGHTS[k] * v for k, v in cues.items()))

    sem_raw = None
    matrix = _archetype_matrix()
    if matrix is not None:
        try:
            from vector_store import EMBEDDING_MODEL
            vec = EMBEDDING_MODEL.encode([opening_text], convert_to_numpy=True, normalize_embeddings=True)[0]
            sem_raw = float(np.max(matrix @ vec))
        except Exception:
            sem_raw = None

    if sem_raw is None:
        # No dense model available — lexical-only, still spread (unlike the old constant
        # 0.4 + beat_bonus fallback, which collapsed every degraded-mode clip to one of two
        # values regardless of how hook-shaped the opening actually was).
        score = _clamp01(lex_raw / HOOK_LEX_ONLY_CEIL)
    else:
        raw = HOOK_SEM_WEIGHT * sem_raw + HOOK_LEX_WEIGHT * lex_raw
        score = _clamp01((raw - HOOK_RAW_FLOOR) / (HOOK_RAW_CEIL - HOOK_RAW_FLOOR))

    if candidate.get("opening_beat_type") == "hook":
        score = _clamp01(score + HOOK_BEAT_BONUS)

    cues_out = dict(cues)
    cues_out["_semantic"] = round(sem_raw, 4) if sem_raw is not None else -1.0
    cues_out["_lexical"] = round(lex_raw, 4)
    return score, cues_out


def _self_containedness(candidate: Dict[str, Any]) -> float:
    opening_text = candidate.get("_opening_text", "")
    words = re.findall(r"\b[a-zA-Z']+\b", opening_text.lower())
    first_ten = words[:10]

    penalty = sum(1 for w in first_ten if w in _DEIXIS_TERMS) * 0.15
    lowered = opening_text.lower()
    penalty += sum(0.2 for phrase in _DEIXIS_PHRASES if phrase in lowered)

    seed_beat = candidate.get("seed_beat") or {}
    llm_flag_bonus = 0.0
    if seed_beat.get("self_contained") is True:
        llm_flag_bonus = 0.2
    elif seed_beat.get("self_contained") is False:
        penalty += 0.2

    return _clamp01(1.0 - penalty + llm_flag_bonus)


def _emotional_delta(candidate: Dict[str, Any], video_id: str) -> float:
    arc_score = 0.0
    for b in candidate.get("beats", []):
        arc = b.get("emotional_arc") or {}
        if arc.get("opening") and arc.get("peak") and arc["opening"] != arc["peak"]:
            arc_score = 0.5
            break

    words = word_timing.load_words(video_id)
    acoustic_score = 0.0
    if words:
        in_range = [w for w in words if candidate["start_sec"] <= w["start"] <= candidate["end_sec"]]
        if len(in_range) >= 4:
            mid = len(in_range) // 2
            first_half_dur = max(in_range[mid]["start"] - in_range[0]["start"], 0.01)
            second_half_dur = max(in_range[-1]["end"] - in_range[mid]["start"], 0.01)
            wpm_first = (mid) / (first_half_dur / 60.0)
            wpm_second = (len(in_range) - mid) / (second_half_dur / 60.0)
            delta = abs(wpm_second - wpm_first) / max(wpm_first, wpm_second, 1.0)
            acoustic_score = _clamp01(delta)

    return _clamp01(0.5 * arc_score + 0.5 * acoustic_score) if (arc_score or acoustic_score) else 0.3


# idf_lookup values are log((n+1)/(df+1)) + 1.0, so >=1.0 always. The old (avg_idf - 1.0) / 3.0
# ceiling was too low for a corpus this size — measured on backend/data/chunks.json's real
# 436 sentences (2026-08-05, via eval/hook_eval.py --distribution, same run as the hook
# calibration above), avg_idf over quotable lines spans p5=4.16 p50=5.04 p95=5.98 p99=6.33
# p100=6.39, so the old ceiling of 4.0 (giving a max of 1.0 at avg_idf=4.0) saturated 96.5%
# of real clips at exactly quotability=1.0 — a signal that was constant just as often as
# hook_strength was, just in the other direction. FLOOR/CEIL below are that measured p5/p99.
QUOTABILITY_IDF_FLOOR = 4.0
QUOTABILITY_IDF_CEIL = 6.3


def _quotability(candidate: Dict[str, Any], idf_lookup: Dict[str, float]) -> float:
    quote = candidate.get("quotable_line", "")
    if not quote:
        return 0.2

    expanded = MultimodalEngine._expand_contractions(quote.lower())
    words = [w for w in re.findall(r"\b[a-zA-Z]+\b", expanded) if w not in STOPWORDS]
    if not words:
        return 0.2

    weights = [idf_lookup.get(w, 1.0) for w in words]
    avg_idf = sum(weights) / len(weights)
    return _clamp01((avg_idf - QUOTABILITY_IDF_FLOOR) / (QUOTABILITY_IDF_CEIL - QUOTABILITY_IDF_FLOOR))


# A pause at or above this length reads as a real phrase boundary. Below it, the clip is
# opening or closing mid-thought no matter how precisely the cut is placed.
#
# Calibrated 2026-08-11 against the real corpus (426 sentence starts across the 5 videos that
# have word timing), measured with phrase_gap_before at every sentence boundary:
#   p5=0.000 p25=0.000 p50=0.120 p75=0.620 p90=0.920 p95=1.220 p99=5.400 max=7.240
#
# Two things that reading matters for:
#
# 1. A recorded gap of 0.0 means Whisper emitted contiguous words, and it does that for the
#    large majority of transitions (5-12% of inter-word gaps are non-zero, per video). So a
#    non-zero gap is strong evidence of a real pause; a zero gap is weaker evidence of the
#    absence of one. This signal is more trustworthy when high than when low.
# 2. 49% of sentence boundaries have NO pause at all. Sentence segmentation in
#    multimodal_engine is text-driven (punctuation and length), so half of the boundaries the
#    solver can choose from simply do not coincide with an acoustic pause. That is a property
#    of the candidate set, not of this metric — and it is the ceiling on what boundary
#    snapping can deliver. Raising it means teaching the solver to PREFER pause-aligned
#    sentence boundaries, which is a narrative_engine change, not a scoring one.
#
# Consequence: this signal is bimodal by nature — at a 0.6s target, ~26% of boundaries
# saturate at 1.0, ~49% sit at 0.0, and ~25% spread between. Lowering the target does not fix
# that (a 0.3s target moves 47% to 1.0 and saturates worse); the floor is not a calibration
# error, it is half the corpus honestly reporting mid-phrase boundaries. Do not "fix" the
# spread by flattening the map.
BOUNDARY_PAUSE_TARGET_SEC = 0.6


def _pause_score(gap: Optional[float]) -> float:
    """None means there is no adjacent speech at all (clip opens or closes the recording) —
    nothing to cut into, so the boundary is perfect by construction, not zero."""
    if gap is None:
        return 1.0
    return _clamp01(gap / BOUNDARY_PAUSE_TARGET_SEC)


def _boundary_cleanliness(candidate: Dict[str, Any], video_id: str) -> float:
    """
    Measured on the PAUSE AROUND THE CLIP'S FIRST/LAST WORD, not on dead air adjacent to the
    cut timestamp.

    This used to call silence_gap_before/after on start_sec/end_sec, which asks "how much
    silence sits next to my cut" — a question whose best answer is "cut in the middle of a
    long pause". That is the defect, scored as a virtue: measured over the 14 real persisted
    clips, introducing boundary snapping moved this signal from 0.342 to 0.113 mean and made
    12 of 14 clips score WORSE, purely because tightening onto speech removed the dead air the
    old formula was rewarding. The signal was inverted with respect to its own name.

    phrase_gap_* asks instead whether the clip's first word actually followed a pause — a
    property of the speech that snapping cannot game and lead-in/tail cannot shift.

    The old >1s taper is gone with it. It existed because a large silence_gap meant the cut
    had landed in an unrelated silence; a large phrase_gap means the opposite — an
    unambiguous phrase boundary — so tapering it would penalise the best cut points available.
    """
    return _clamp01((
        _pause_score(word_timing.phrase_gap_before(video_id, candidate["start_sec"]))
        + _pause_score(word_timing.phrase_gap_after(video_id, candidate["end_sec"]))
    ) / 2.0)


def _taste_match(candidate: Dict[str, Any], taste_centroid: Optional[np.ndarray]) -> Optional[float]:
    if taste_centroid is None:
        return None
    from vector_store import EMBEDDING_MODEL, HAS_DENSE_MODEL
    if not HAS_DENSE_MODEL:
        return None
    text = candidate.get("_full_text", "") or candidate.get("quotable_line", "")
    if not text:
        return 0.5
    vec = EMBEDDING_MODEL.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
    cosine = float(np.dot(vec, taste_centroid))
    return _clamp01((cosine + 1.0) / 2.0)


def score_candidate(
    candidate: Dict[str, Any],
    video_id: str,
    idf_lookup: Dict[str, float],
    taste_centroid: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """
    Compute all five (optionally six) signals for one candidate. Returns the candidate dict
    augmented with `signals` (name -> 0..1 score) and `composite` (weighted sum) — never a
    fabricated percentage, just named, inspectable numbers the UI renders as bars.

    No longer takes get_cross_encoder — hook_strength stopped using the cross-encoder (see
    the calibration note above WEIGHTS), and it was the only signal that ever needed one.
    """
    hook_score, hook_cues = _hook_strength(candidate)
    signals = {
        "hook_strength": hook_score,
        "self_containedness": _self_containedness(candidate),
        "emotional_delta": _emotional_delta(candidate, video_id),
        "quotability": _quotability(candidate, idf_lookup),
        "boundary_cleanliness": _boundary_cleanliness(candidate, video_id),
    }

    weights = dict(WEIGHTS)
    taste_score = _taste_match(candidate, taste_centroid)
    if taste_score is not None:
        signals["taste_match"] = taste_score
        # Re-normalize weights so the six signals still sum to 1.0 rather than silently
        # over-weighting the composite once a sixth signal joins.
        taste_weight = 0.15
        scale = 1.0 - taste_weight
        weights = {k: v * scale for k, v in WEIGHTS.items()}
        weights["taste_match"] = taste_weight

    composite = sum(signals[k] * weights[k] for k in signals)

    result = dict(candidate)
    result["signals"] = signals
    result["signal_details"] = {"hook_cues": hook_cues}
    result["composite"] = round(composite, 4)
    return result


def _top_contributor_reason(signals: Dict[str, float]) -> str:
    ranked = sorted(signals.items(), key=lambda kv: kv[1], reverse=True)
    top_two = [_signal_label(k) for k, _ in ranked[:2]]
    return f"Strongest on {' and '.join(top_two)}"


_SIGNAL_LABELS = {
    "hook_strength": "hook",
    "self_containedness": "self-containedness",
    "emotional_delta": "emotional delta",
    "quotability": "quotability",
    "boundary_cleanliness": "clean boundaries",
    "taste_match": "taste match",
}


def _signal_label(key: str) -> str:
    return _SIGNAL_LABELS.get(key, key)


def rank(
    candidates: List[Dict[str, Any]],
    sentences_by_idx: Dict[int, Dict[str, Any]],
    video_id: str,
    corpus_texts: List[str],
    max_clips: int = 6,
    taste_centroid: Optional[np.ndarray] = None,
) -> List[Dict[str, Any]]:
    """
    Score every candidate and return the top `max_clips`, sorted best-first with a stable,
    deterministic tie-break. Each result carries `signals`, `composite`, and a one-line
    `reason` string for the UI — never a percentage.

    No longer takes get_cross_encoder — see score_candidate's docstring.
    """
    if not candidates:
        return []

    idf_lookup = MultimodalEngine.compute_corpus_idf(corpus_texts)

    enriched = []
    for i, cand in enumerate(candidates):
        opening_idx = cand["start_sentence_idx"]
        opening_sentence = sentences_by_idx.get(opening_idx, {}).get("text", "")
        full_text = " ".join(
            sentences_by_idx[i]["text"]
            for i in range(cand["start_sentence_idx"], cand["end_sentence_idx"] + 1)
            if i in sentences_by_idx
        )
        cand_with_ctx = dict(cand)

        # Snap the boundary BEFORE scoring, not after. _boundary_cleanliness used to measure
        # the raw sentence bounds — which are quantised to whole seconds by MultimodalEngine
        # — so a candidate with a clean pause available 200ms away was marked down for a
        # boundary nothing ever tried to fix. Scoring the pre-snap value also meant the
        # number shown in the UI described a cut we didn't ship. Snapping here (rather than
        # in narrative_engine) keeps the solver pure — it has no video_id and its tests pass
        # sentences alone — and gets backend/eval/clip_eval.py the same treatment for free.
        snapped_start, snapped_end, snap_info = word_timing.snap_clip_bounds(
            video_id, cand["start_sec"], cand["end_sec"],
        )
        cand_with_ctx["start_sec"] = snapped_start
        cand_with_ctx["end_sec"] = snapped_end
        cand_with_ctx["boundary_snap"] = snap_info

        cand_with_ctx["_opening_text"] = opening_sentence
        cand_with_ctx["_full_text"] = full_text
        cand_with_ctx["id"] = f"{video_id}-clip-{i}"
        enriched.append(cand_with_ctx)

    scored = [
        score_candidate(c, video_id, idf_lookup, taste_centroid)
        for c in enriched
    ]

    for s in scored:
        s["reason"] = _top_contributor_reason(s["signals"])
        s.pop("_opening_text", None)
        s.pop("_full_text", None)

    scored.sort(key=lambda c: (-c["composite"], c["start_sec"], c["id"]))
    return scored[:max_clips]


def record_feedback(clip_id: str, verdict: str) -> int:
    """Append a {clip_id, verdict} label to clip_feedback.json. Returns the new total label
    count (used by the API to tell the UI whether taste_match is active yet)."""
    import json
    import os
    import time
    import paths

    os.makedirs(paths.DATA_DIR, exist_ok=True)
    existing = []
    if os.path.exists(paths.CLIP_FEEDBACK_FILE):
        try:
            with open(paths.CLIP_FEEDBACK_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing.append({"clip_id": clip_id, "verdict": verdict, "ts": time.time()})
    with open(paths.CLIP_FEEDBACK_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    return len(existing)


def compute_taste_centroid() -> Optional[np.ndarray]:
    """
    Preference centroid in MiniLM space over 'winner'-labeled clip text, once at least
    MIN_LABELS_FOR_TASTE labels exist. Below that, taste_match is omitted entirely rather
    than computed from too little data (ENGINE-PLAN.md Phase 2: honest personalization,
    not a guess dressed up as one).
    """
    import json
    import os
    import paths

    if not os.path.exists(paths.CLIP_FEEDBACK_FILE):
        return None
    try:
        with open(paths.CLIP_FEEDBACK_FILE, 'r', encoding='utf-8') as f:
            labels = json.load(f)
    except Exception:
        return None

    if len(labels) < MIN_LABELS_FOR_TASTE:
        return None

    winners = [l for l in labels if l.get("verdict") == "winner"]
    if not winners:
        return None

    if not os.path.exists(paths.CLIPS_FILE):
        return None
    try:
        with open(paths.CLIPS_FILE, 'r', encoding='utf-8') as f:
            clips_by_id = json.load(f)
    except Exception:
        return None

    texts = []
    for w in winners:
        clip = clips_by_id.get(w["clip_id"])
        if clip:
            texts.append(clip.get("_full_text") or clip.get("quotable_line") or clip.get("title", ""))
    texts = [t for t in texts if t]
    if not texts:
        return None

    from vector_store import EMBEDDING_MODEL, HAS_DENSE_MODEL
    if not HAS_DENSE_MODEL:
        return None
    vectors = EMBEDDING_MODEL.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    centroid = vectors.mean(axis=0)
    norm = np.linalg.norm(centroid)
    return centroid / norm if norm > 0 else None
