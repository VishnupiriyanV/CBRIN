"""
Five explainable, named signals for ranking clip candidates — a weighted sum, displayed as
a breakdown. No fabricated "predicted engagement %" anywhere (ENGINE-PLAN.md: the Lens layer
with real performance data doesn't exist in this repo; IMPROVEMENT-PLAN.md 2.3 already killed
one fake confidence number for exactly this reason).

Ties break deterministically on (composite, -start_sec, candidate id) so repeated runs on
the same input produce a stable order — backend/eval/clip_eval.py depends on that.
"""
import re
from typing import Any, Callable, Dict, List, Optional

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

# Bundled hook archetypes for cross-encoder scoring in both LLM and degraded mode — not
# specific to any one creator's content, just generically "hook-shaped" openers.
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


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _hook_strength(candidate: Dict[str, Any], get_cross_encoder: Callable) -> float:
    opening_text = candidate.get("_opening_text", "")
    if not opening_text:
        return 0.5

    beat_bonus = 0.0
    for b in candidate.get("beats", []):
        if b.get("beat_type") == "hook":
            beat_bonus = 0.3
            break

    reranker = get_cross_encoder()
    if reranker is None:
        return _clamp01(0.4 + beat_bonus)

    try:
        pairs = [(archetype, opening_text) for archetype in HOOK_ARCHETYPES]
        scores = reranker.predict(pairs)
        best = float(max(scores))
        # sigmoid to map an unbounded cross-encoder logit into [0,1]
        sigmoid = 1.0 / (1.0 + np.exp(-best))
        return _clamp01(sigmoid + beat_bonus)
    except Exception:
        return _clamp01(0.4 + beat_bonus)


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
    # idf_lookup values are log((n+1)/(df+1)) + 1.0, so >=1.0 always; normalize against a
    # generous ceiling rather than an unbounded raw value.
    return _clamp01((avg_idf - 1.0) / 3.0)


def _boundary_cleanliness(candidate: Dict[str, Any], video_id: str) -> float:
    gap_before = word_timing.silence_gap_before(video_id, candidate["start_sec"])
    gap_after = word_timing.silence_gap_after(video_id, candidate["end_sec"])
    # Reward a modest breathing gap (~0.2-0.6s); reward tapers off past ~1s since a very
    # long gap usually means the boundary landed in an unrelated silence, not a clean pause.
    score_before = _clamp01(gap_before / 0.6) if gap_before <= 1.0 else _clamp01(1.5 - gap_before)
    score_after = _clamp01(gap_after / 0.6) if gap_after <= 1.0 else _clamp01(1.5 - gap_after)
    return _clamp01((score_before + score_after) / 2.0)


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
    get_cross_encoder: Callable,
    taste_centroid: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """
    Compute all five (optionally six) signals for one candidate. Returns the candidate dict
    augmented with `signals` (name -> 0..1 score) and `composite` (weighted sum) — never a
    fabricated percentage, just named, inspectable numbers the UI renders as bars.
    """
    signals = {
        "hook_strength": _hook_strength(candidate, get_cross_encoder),
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
    get_cross_encoder: Callable,
    max_clips: int = 6,
    taste_centroid: Optional[np.ndarray] = None,
) -> List[Dict[str, Any]]:
    """
    Score every candidate and return the top `max_clips`, sorted best-first with a stable,
    deterministic tie-break. Each result carries `signals`, `composite`, and a one-line
    `reason` string for the UI — never a percentage.
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
        cand_with_ctx["_opening_text"] = opening_sentence
        cand_with_ctx["_full_text"] = full_text
        cand_with_ctx["id"] = f"{video_id}-clip-{i}"
        enriched.append(cand_with_ctx)

    scored = [
        score_candidate(c, video_id, idf_lookup, get_cross_encoder, taste_centroid)
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
