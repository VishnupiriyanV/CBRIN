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

import prosody
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


# Each sentence still pointing outside the clip after the solver has expanded as far as
# MAX_CLIP_SEC allows. One is a real defect; the scale is steep on purpose.
DANGLING_REFERENCE_PENALTY = 0.35


def _self_containedness(candidate: Dict[str, Any]) -> float:
    """
    Driven by the solver's COMPUTED referential dependencies, not by the LLM's opinion of
    itself.

    This used to count deixis terms in the first ten words and then apply +/-0.2 from
    `seed_beat["self_contained"]` — a heuristic wrapped around an unverified model claim, in a
    module whose entire point is that dependencies are structural rather than asserted. The
    LLM flag is now ignored completely: it was the only input here that nothing could check,
    and narrative_engine already expands the clip to satisfy what it can, so a residual
    dangling reference is a measured fact rather than a guess.

    The deixis scan is kept, at reduced weight, for two cases the resolver deliberately does
    not cover: a back-reference that is not sentence-initial, and degraded mode, where
    `dangling_reference_indices` is absent because references were never resolved.
    """
    opening_text = candidate.get("_opening_text", "")
    lowered = opening_text.lower()
    words = re.findall(r"\b[a-zA-Z']+\b", lowered)

    # Split contractions before the membership test: the pattern keeps the apostrophe inside a
    # token, so "it's"/"that's"/"they're" would never match the bare words in _DEIXIS_TERMS.
    # Same defect reference_resolver._head fixes on the primary path; this is the degraded-mode
    # fallback, so it needs the same treatment to be worth anything.
    penalty = sum(1 for w in words[:10] if w.split("'", 1)[0] in _DEIXIS_TERMS) * 0.08
    penalty += sum(0.15 for phrase in _DEIXIS_PHRASES if phrase in lowered)

    dangling = candidate.get("dangling_reference_indices")
    if dangling is not None:
        penalty += len(dangling) * DANGLING_REFERENCE_PENALTY

    return _clamp01(1.0 - penalty)


# --- Acoustic prosody calibration ---------------------------------------------------------
# Floors/ceilings are the measured p5/p95 of each feature over the FULL 439-sentence corpus
# (2026-08-11, via the prosody extraction over all 5 indexed videos). Per-sentence rather than
# per-clip percentiles on purpose: n=439 against n=14, and the two distributions agree closely
# where they overlap (clip-level pitch_range p50=9.29 vs sentence-level 10.97).
#
#   pitch_range_st   p5= 5.26  p25= 7.20  p50=10.97  p75=16.24  p95=23.25  p99=26.18
#   pitch_delta_st   p5= 0.12  p25= 0.62  p50= 1.75  p75= 3.54  p95= 8.84  p99=13.69  (abs)
#   energy_delta     p5= 0.01  p25= 0.06  p50= 0.13  p75= 0.22  p95= 0.39  p99= 0.64
#
# Re-measure and re-set these if the pitch tracker in prosody.py changes. They were already
# invalidated once mid-implementation: before prosody's local-maximum peak check existed,
# pitch_range_st had a median of 17.0 semitones and a p99 of 32.8 (2.7 octaves) because
# aperiodic frames were pinning to the F0_MIN_HZ/F0_MAX_HZ search bounds. Calibrating against
# that distribution would have baked the artifact into the weights.
PITCH_RANGE_FLOOR_ST = 5.26
PITCH_RANGE_CEIL_ST = 23.25
PITCH_DELTA_FLOOR_ST = 0.12
PITCH_DELTA_CEIL_ST = 8.84
ENERGY_DELTA_FLOOR = 0.01
ENERGY_DELTA_CEIL = 0.39

# Within the acoustic half. Pitch spread and loudness change carry the most direct external
# support (the VQualA audio ablation), speaking rate the least — it was the whole signal
# before and is now one term of four.
ACOUSTIC_WEIGHTS = {
    "pitch_range": 0.40,
    "energy_delta": 0.30,
    "pitch_delta": 0.15,
    "rate_delta": 0.15,
}

# The LLM's emotional_arc claim against the measured contour. Weighted toward the measurement:
# the arc is an unverifiable model assertion of the same kind that _self_containedness stopped
# trusting, whereas the acoustic half is computed from the audio.
ARC_WEIGHT = 0.35
ACOUSTIC_WEIGHT = 0.65


def _normalise(value: float, floor: float, ceil: float) -> float:
    if ceil <= floor:
        return 0.0
    return _clamp01((value - floor) / (ceil - floor))


def _speech_rate_delta(candidate: Dict[str, Any], video_id: str) -> Optional[float]:
    """Words-per-minute change between clip halves — the original acoustic proxy, kept as one
    term of four and as the sole degraded-mode signal when prosody is unavailable."""
    words = word_timing.load_words(video_id)
    if not words:
        return None
    in_range = [w for w in words if candidate["start_sec"] <= w["start"] <= candidate["end_sec"]]
    if len(in_range) < 4:
        return None
    mid = len(in_range) // 2
    first_dur = max(in_range[mid]["start"] - in_range[0]["start"], 0.01)
    second_dur = max(in_range[-1]["end"] - in_range[mid]["start"], 0.01)
    wpm_first = mid / (first_dur / 60.0)
    wpm_second = (len(in_range) - mid) / (second_dur / 60.0)
    return _clamp01(abs(wpm_second - wpm_first) / max(wpm_first, wpm_second, 1.0))


def _acoustic_delta(candidate: Dict[str, Any], video_id: str) -> Optional[float]:
    """
    Measured delivery dynamics in [0, 1], or None when nothing could be measured.

    Terms are dropped rather than zero-filled when unavailable, and the remaining weights are
    renormalised — a clip whose pitch could not be measured should be scored on what WAS
    measured, not penalised for the gap. Same principle as BOUNDARY_UNKNOWN_SCORE.
    """
    features = prosody.window_features(video_id, candidate["start_sec"], candidate["end_sec"])
    rate_delta = _speech_rate_delta(candidate, video_id)

    terms: Dict[str, float] = {}
    if rate_delta is not None:
        terms["rate_delta"] = rate_delta
    if features is not None:
        terms["energy_delta"] = _normalise(
            features["energy_delta"], ENERGY_DELTA_FLOOR, ENERGY_DELTA_CEIL)
        if features["pitch_reliable"]:
            terms["pitch_range"] = _normalise(
                features["pitch_range_st"], PITCH_RANGE_FLOOR_ST, PITCH_RANGE_CEIL_ST)
            terms["pitch_delta"] = _normalise(
                abs(features["pitch_delta_st"]), PITCH_DELTA_FLOOR_ST, PITCH_DELTA_CEIL_ST)

    if not terms:
        return None
    total = sum(ACOUSTIC_WEIGHTS[k] for k in terms)
    return _clamp01(sum(terms[k] * ACOUSTIC_WEIGHTS[k] for k in terms) / total)


def _emotional_delta(candidate: Dict[str, Any], video_id: str) -> float:
    """
    How much the delivery moves across the clip — measured from the audio, not inferred from
    the word count.

    This used to be a words-per-minute delta between halves: one prosodic dimension of three,
    and the weakest. A speaker who drops to a whisper and builds to a shout at a constant rate
    registered as flat. Pitch spread, pitch direction and loudness change now carry most of
    the weight (prosody.window_features), with speaking rate demoted to one term of four.

    The evidence for adding audio at all is the ICCV VQualA 2025 engagement challenge: on
    90,000 short videos with real engagement labels, VideoLLaMA2-7B *with* audio (0.695) beat
    the newer vision-language-only Qwen2.5-VL-7B (0.664).
    """
    arc_score = 0.0
    for b in candidate.get("beats", []):
        arc = b.get("emotional_arc") or {}
        if arc.get("opening") and arc.get("peak") and arc["opening"] != arc["peak"]:
            arc_score = 1.0
            break

    acoustic_score = _acoustic_delta(candidate, video_id)

    if acoustic_score is None:
        # No audio and no word timing. 0.3 is the long-standing neutral default here; keep it
        # rather than inventing a number from the LLM's arc claim alone.
        return _clamp01(ARC_WEIGHT * arc_score) if arc_score else 0.3

    return _clamp01(ARC_WEIGHT * arc_score + ACOUSTIC_WEIGHT * acoustic_score)


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
    return _boundary_score_for(video_id, candidate["start_sec"], candidate["end_sec"])


# Returned when there is no word timing for the video at all. phrase_gap_* answers None for
# two very different reasons — "the clip opens the recording, nothing to cut into" (a perfect
# boundary) and "there is no timing data" (unknown) — and scoring the second as perfect would
# rank an un-timed video's clips ABOVE properly measured ones. The old formula had the
# opposite bug: silence_gap_* returned 0.0 with no data, so missing timing scored as the worst
# possible boundary. Neither is honest; 0.5 says "unknown" and matches how _taste_match and
# _emotional_delta already report absent evidence.
BOUNDARY_UNKNOWN_SCORE = 0.5


def _boundary_score_for(video_id: str, start_sec: float, end_sec: float) -> float:
    if word_timing.load_words(video_id) is None:
        return BOUNDARY_UNKNOWN_SCORE
    return _clamp01((
        _pause_score(word_timing.phrase_gap_before(video_id, start_sec))
        + _pause_score(word_timing.phrase_gap_after(video_id, end_sec))
    ) / 2.0)


def make_boundary_scorer(video_id: str):
    """
    A (start_sec, end_sec) -> [0, 1] callable for narrative_engine.beats_to_candidates, so the
    solver can PREFER sentence boundaries that land on real pauses instead of only being
    marked on whichever one it happened to pick first.

    Deliberately the same function _boundary_cleanliness reports. If the solver optimised
    against one definition of a clean boundary and the ranker scored a different one, the two
    would drift and the score would stop describing the choice — which is the failure this
    signal has already had once, in the opposite direction (see _boundary_cleanliness).
    """
    return lambda start_sec, end_sec: _boundary_score_for(video_id, start_sec, end_sec)


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


# --- Diversity-aware selection --------------------------------------------------------------
# narrative_engine._merge_overlapping_candidates collapses candidates overlapping >60% by
# SENTENCE COUNT — temporal overlap only. Two clips fifteen minutes apart that make the same
# point are not overlapping by that test, so both survive and both can rank top-5. Picking the
# top N by composite alone is exposed to what the frame-selection literature calls redundancy
# collapse: every pick clustered on one strong stretch of the video.
#
# MMR (Carbonell & Goldstein) is the standard fix — trade relevance against novelty. Gygli et
# al. established the same shape for video summarization as a submodular objective with greedy
# selection. Here: score everything, then select greedily on
#
#     lambda * composite - (1 - lambda) * max_cosine_to_already_selected
#
# LAMBDA IS NOT A FREE PARAMETER — it depends on the relative SPREAD of the two terms, which
# are on different scales. Measured on this library (2026-08-11, 14 persisted clips):
#
#   composite:          min=0.402  p50=0.481  max=0.617  stdev=0.060
#   adjacent gap within one video:  p50=0.0367  p90=0.0541  max=0.0652
#   pairwise cosine within one video: p50=0.216  p90=0.459  max=0.588  (none above 0.7)
#
# So a typical quality difference between neighbouring candidates is ~0.037, while similarity
# ranges over ~0.65. At lambda=0.7 the novelty term spans 0.3*0.65 = 0.194 against a typical
# lambda-weighted quality gap of 0.7*0.037 = 0.026 — novelty with roughly 7x the authority of
# quality, which is the opposite of the intent. The same failure clip_scoring already has on
# record for hook_strength: a nominal weight that doesn't match effective influence.
#
# 0.85 sizes the penalty so a near-duplicate can lose to a modestly worse but novel clip
# (0.15*0.65 = 0.098, about two adjacent quality steps) without a weak clip being promoted for
# being unusual. Re-derive it if the composite distribution shifts — a signal change that
# widens or narrows composite spread silently changes what this lambda means.
#
# Note the honest consequence on THIS corpus: max pairwise similarity is 0.588 and only 2 of
# 31 pairs exceed 0.5, so at 0.85 selection is unchanged for every video in the library. That
# is the correct result for a corpus with no real redundancy, not evidence the guard works —
# TestDiversitySelection covers the firing case synthetically.
MMR_LAMBDA = 0.85


def _encode_candidates(candidates: List[Dict[str, Any]]) -> Optional[np.ndarray]:
    """Unit-normalised embeddings for every candidate, in ONE batch call. Returns None when
    the dense model is unavailable — the same degraded-mode bail as _taste_match."""
    from vector_store import EMBEDDING_MODEL, HAS_DENSE_MODEL
    if not HAS_DENSE_MODEL:
        return None
    texts = [
        (c.get("_full_text") or c.get("quotable_line") or "").strip() for c in candidates
    ]
    if not any(texts):
        return None
    return EMBEDDING_MODEL.encode(texts, convert_to_numpy=True, normalize_embeddings=True)


def _select_diverse(
    ordered: List[Dict[str, Any]], max_clips: int, lambda_: float = MMR_LAMBDA
) -> List[Dict[str, Any]]:
    """
    Greedy MMR over `ordered` (already sorted best-first, deterministically).

    Annotates every selected clip with `diversity.max_similarity` — how close it is to the
    nearest already-selected clip — so a near-duplicate that survived is visible rather than
    silently present. The top-scoring clip is always selected first and reports 0.0.

    Determinism holds: `ordered` is deterministic, the scan runs in that order, and ties use
    strict `>`, so an exact MMR tie resolves to the higher-composite candidate.
    """
    if max_clips <= 0:
        return []

    vectors = _encode_candidates(ordered)
    if vectors is None or len(ordered) <= 1:
        # Degraded: no dense model, so novelty cannot be measured. Fall back to top-k by
        # composite and say so, rather than reporting a diversity figure nothing computed.
        for c in ordered[:max_clips]:
            c["diversity"] = {"max_similarity": None, "measured": False}
        return list(ordered[:max_clips])

    selected: List[int] = [0]
    ordered[0]["diversity"] = {"max_similarity": 0.0, "measured": True}

    while len(selected) < min(max_clips, len(ordered)):
        best_i: Optional[int] = None
        best_mmr = 0.0
        best_sim = 0.0
        for i in range(len(ordered)):
            if i in selected:
                continue
            similarity = max(float(np.dot(vectors[i], vectors[j])) for j in selected)
            mmr = lambda_ * ordered[i]["composite"] - (1.0 - lambda_) * similarity
            if best_i is None or mmr > best_mmr:
                best_i, best_mmr, best_sim = i, mmr, similarity
        if best_i is None:
            break
        ordered[best_i]["diversity"] = {
            "max_similarity": round(best_sim, 4), "measured": True,
        }
        selected.append(best_i)

    return [ordered[i] for i in selected]


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

    # Deterministic best-first order, then diversity-aware selection from it. _full_text must
    # still be present here — _select_diverse embeds it — so the scratch keys are stripped
    # after selection rather than before.
    scored.sort(key=lambda c: (-c["composite"], c["start_sec"], c["id"]))
    selected = _select_diverse(scored, max_clips)

    for s in selected:
        s["reason"] = _top_contributor_reason(s["signals"])
        s.pop("_opening_text", None)
        s.pop("_full_text", None)

    # Re-sort for display. MMR decides WHICH clips are shown; the user still expects them
    # best-first, and clip_eval.py depends on this ordering being stable.
    selected.sort(key=lambda c: (-c["composite"], c["start_sec"], c["id"]))
    return selected


def record_feedback(clip_id: str, verdict: str) -> int:
    """Append a {clip_id, verdict} label to clip_feedback.json. Returns the new total label
    count (used by the API to tell the UI whether taste_match is active yet)."""
    import json
    import os
    import time
    import atomic_io
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
    # Atomic: this is read-append-write over the creator's accumulated taste labels, which are
    # user-generated and unrecoverable — nothing can regenerate them. A truncated write is read
    # back as [] by the guard above, so the very next verdict persists a one-element list and
    # every prior label is gone with no error surfaced. MIN_LABELS_FOR_TASTE gates a whole
    # signal on this file.
    atomic_io.write_json(paths.CLIP_FEEDBACK_FILE, existing)

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
