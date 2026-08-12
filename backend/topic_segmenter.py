"""
Topic-coherent segmentation of a transcript, by divisive clustering over sentence embeddings.

Why this exists: narrative_engine used to window the transcript at a fixed 60 sentences with
10 of overlap. That bound what the solver could ever prove. A payoff at sentence 340 whose
setup lives at sentence 12 is structurally invisible — no window contains both, so no LLM call
can emit that `requires_setup_from_idx`, and "cannot cut a setup from its punchline" quietly
became "cannot, within any 60 consecutive sentences".

Approach follows TreeSeg (Hierarchical Topic Segmentation of Large Transcripts, ICSI/AMI/
TinyRec): off-the-shelf embeddings plus divisive clustering, built for ASR noise and for the
case where the true number of segments is unknown. Deliberately NOT an LLM job — the linear
text segmentation survey (Findings of EMNLP 2024) measures zero-shot ChatGPT at 31.8 Pk
against TextTiling+BERT's 33.6 and supervised TextSeg's 19.9, so prompting for segmentation is
barely better than a 1997 algorithm and would spend the LLM budget beat extraction needs.


THE OBJECTIVE, AND WHY IT IS CHEAP
----------------------------------
For unit-normalised sentence vectors v[i..j], let T(i,j) = sum of those vectors. Then the
centroid is T/|T|, and the mean cosine of each sentence to that centroid is exactly

    cohesion(i, j) = |T(i, j)| / (j - i + 1)

so the *total* cohesion of a span is just |T(i,j)|. Splitting [i,j) at k scores

    gain(k) = |T(i,k)| + |T(k,j)| - |T(i,j)|

which is >= 0 by the triangle inequality, with equality exactly when the two halves point the
same way — i.e. when they are about the same thing. Maximising it finds the point where the
transcript most changes subject.

Every term is a vector-norm of a prefix-sum difference, so each candidate split is O(d) rather
than O(n^2) pairwise similarity. A 3,000-sentence transcript segments in well under a second,
which is what makes this affordable to run before the LLM stage rather than instead of it.
"""
from typing import Callable, List, Optional, Sequence

import numpy as np

# Minimum sentences in a segment. Below roughly this, "topic" stops being meaningful for
# spoken content — a single aside is not a section — and the splitter starts chasing noise.
MIN_SEGMENT_SENTENCES = 8

# Relative gain below which a span is left whole. Normalising by span length keeps the
# threshold comparable across a 20-sentence span and a 500-sentence one. Calibrated against
# the real corpus; see the measured segment counts in RESEARCH.md Gap 5.
MIN_RELATIVE_GAIN = 0.012

# Hard ceiling on recursion depth. A pathological transcript cannot spend unbounded time here,
# and 2^12 segments is far past anything a real video produces.
MAX_SPLIT_DEPTH = 12

EmbedFn = Callable[[List[str]], np.ndarray]


def _prefix_sums(vectors: np.ndarray) -> np.ndarray:
    """P[k] = sum of vectors[0:k], so T(i, j) = P[j] - P[i] for a half-open span."""
    return np.vstack([np.zeros((1, vectors.shape[1]), dtype=vectors.dtype), np.cumsum(vectors, axis=0)])


def _best_split(
    prefix: np.ndarray, start: int, end: int, min_segment: int
) -> "tuple[Optional[int], float]":
    """
    Best split point for the half-open span [start, end), and its relative gain.

    Returns (None, 0.0) when the span cannot host two segments of `min_segment`.
    """
    length = end - start
    if length < 2 * min_segment:
        return None, 0.0

    lo = start + min_segment
    hi = end - min_segment  # inclusive
    if hi < lo:
        return None, 0.0

    total = np.linalg.norm(prefix[end] - prefix[start])

    ks = np.arange(lo, hi + 1)
    left = np.linalg.norm(prefix[ks] - prefix[start], axis=1)
    right = np.linalg.norm(prefix[end] - prefix[ks], axis=1)
    gains = left + right - total

    best_i = int(np.argmax(gains))
    return int(ks[best_i]), float(gains[best_i]) / length


def split_points(
    vectors: np.ndarray,
    min_relative_gain: float = MIN_RELATIVE_GAIN,
    min_segment: int = MIN_SEGMENT_SENTENCES,
) -> List[int]:
    """
    Divisive clustering over `vectors` (unit-normalised, one row per sentence).

    Returns sorted split points — the index at which each segment after the first begins — so
    segment boundaries are `[0] + split_points + [n]`.

    Recursion stops on three conditions, any of which alone is enough: the span cannot hold
    two segments of `min_segment`, the best available split does not clear
    `min_relative_gain`, or MAX_SPLIT_DEPTH is reached. The gain threshold is what handles
    "the true number of segments is unknown" — a transcript that never changes subject
    produces no splits at all rather than being forced into a preset count.
    """
    n = vectors.shape[0]
    if n < 2 * min_segment:
        return []

    prefix = _prefix_sums(vectors)
    found: List[int] = []
    # Explicit stack rather than recursion — depth is bounded, but deep stack frames on a very
    # long transcript are not worth the risk.
    pending = [(0, n, 0)]
    while pending:
        start, end, depth = pending.pop()
        if depth >= MAX_SPLIT_DEPTH:
            continue
        k, gain = _best_split(prefix, start, end, min_segment)
        if k is None or gain < min_relative_gain:
            continue
        found.append(k)
        pending.append((start, k, depth + 1))
        pending.append((k, end, depth + 1))
    return sorted(found)


def segment_sentences(
    sentences: List[dict],
    embed_fn: EmbedFn,
    min_relative_gain: float = MIN_RELATIVE_GAIN,
    min_segment: int = MIN_SEGMENT_SENTENCES,
) -> List[List[dict]]:
    """
    Group `sentences` (in transcript order) into topic-coherent runs.

    Returns a single run when the transcript is too short to split or never changes subject —
    callers should treat one segment as a legitimate answer, not a failure.
    """
    if not sentences:
        return []
    ordered = sorted(sentences, key=lambda s: s["sentence_idx"])
    if len(ordered) < 2 * min_segment:
        return [ordered]

    vectors = embed_fn([s.get("text", "") for s in ordered])
    if vectors is None or len(vectors) != len(ordered):
        return [ordered]
    vectors = np.asarray(vectors, dtype=np.float32)

    cuts = split_points(vectors, min_relative_gain=min_relative_gain, min_segment=min_segment)
    bounds = [0] + cuts + [len(ordered)]
    return [ordered[a:b] for a, b in zip(bounds, bounds[1:]) if b > a]


def default_embed_fn() -> Optional[EmbedFn]:
    """
    Sentence embeddings from the model vector_store already loads for dense search, or None
    when it is unavailable.

    Imported lazily and behind HAS_DENSE_MODEL for the same reason clip_scoring._taste_match
    does it: this must degrade to the old fixed windowing rather than fail an analysis.
    """
    from vector_store import EMBEDDING_MODEL, HAS_DENSE_MODEL
    if not HAS_DENSE_MODEL:
        return None

    def embed(texts: List[str]) -> np.ndarray:
        return EMBEDDING_MODEL.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

    return embed


def make_segmenter() -> Optional[Callable[[List[dict]], List[List[dict]]]]:
    """A ready-to-inject segmenter for narrative_engine, or None in degraded mode."""
    embed_fn = default_embed_fn()
    if embed_fn is None:
        return None
    return lambda sentences: segment_sentences(sentences, embed_fn)


def summarise_segment(segment: Sequence[dict], max_chars: int = 140) -> str:
    """
    A one-line gist of a segment, for the cross-segment context header narrative_engine puts
    in front of each window.

    The first sentence, not a generated summary: it needs no LLM call, it is verbatim so it
    cannot hallucinate, and the opening line of a topic-coherent run is usually what
    introduces it. Good enough to let the model recognise "the bit about the first hire" and
    point a dependency at it.
    """
    if not segment:
        return ""
    text = " ".join((s.get("text", "") or "").strip() for s in segment[:2]).strip()
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
