#!/usr/bin/env python
"""
Calibration harness for clip_scoring.py's hook_strength signal (ENGINE-PLAN.md Phase 2),
extending the pattern already established by backend/eval/run_eval.py and clip_eval.py:
"do not tune thresholds by eye."

hook_strength used to feed (archetype, opening_text) pairs to a query->passage relevance
cross-encoder and take sigmoid(max_logit) — every real clip opening scored ~0.0001-0.0005,
i.e. a constant 0% in the UI. The replacement blends bi-encoder archetype similarity with
explicit lexical cues, mapped through a range measured on this library's real transcript
sentences rather than assumed. This script is how those constants get set and re-checked —
see the calibration note above clip_scoring.WEIGHTS for the numbers currently baked in.

Usage (from backend/):
    python eval/hook_eval.py --distribution              # corpus percentiles + top/bottom 20
    python eval/hook_eval.py --labels eval/hook_labels.yaml   # AUC / class separation
    python eval/hook_eval.py --clips                     # re-score openings in data/clips.json
    python eval/hook_eval.py --suggest                    # recommended FLOOR/CEIL from labels
    python eval/hook_eval.py --ablate sem                 # AUC with the semantic half zeroed
    python eval/hook_eval.py --ablate lex                 # AUC with the lexical half zeroed

Acceptance bar for a labeled set (see --labels): ROC-AUC >= 0.70 and hook-class median score
at least 0.20 above non-hook-class median. If a proposed weight/constant change drops either,
revert it — same discipline vector_store.py's RERANK_RELEVANCE_THRESHOLD comment documents.
"""
import argparse
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paths  # noqa: E402
import clip_scoring as cs  # noqa: E402


def _load_chunks():
    if not os.path.exists(paths.CHUNKS_FILE):
        print(f"No chunks file at {paths.CHUNKS_FILE} — ingest a video first.")
        sys.exit(1)
    with open(paths.CHUNKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _score(text: str, ablate: str = None):
    """Runs the real hook_strength scoring path for a bare opening string, with an optional
    ablation ('sem' zeroes the semantic half, 'lex' zeroes the lexical half) so the weight
    split in clip_scoring.py can be defended by measurement instead of asserted."""
    cand = {"_opening_text": text}
    if ablate == "sem":
        matrix = cs._archetype_matrix
        cs._archetype_matrix = lambda: None
        try:
            score, cues = cs._hook_strength(cand)
        finally:
            cs._archetype_matrix = matrix
        return score, cues
    if ablate == "lex":
        original_weights = dict(cs.HOOK_CUE_WEIGHTS)
        for k in cs.HOOK_CUE_WEIGHTS:
            cs.HOOK_CUE_WEIGHTS[k] = 0.0
        try:
            score, cues = cs._hook_strength(cand)
        finally:
            cs.HOOK_CUE_WEIGHTS.clear()
            cs.HOOK_CUE_WEIGHTS.update(original_weights)
        return score, cues
    return cs._hook_strength(cand)


def _safe(text: str) -> str:
    """Console-safe repr — some transcript sentences contain characters (e.g. lyric notes)
    outside the terminal's codepage; never let a print() crash the run over one sentence."""
    return text.encode("ascii", "replace").decode()


def _percentiles(values, pcts=(0, 5, 25, 50, 75, 95, 99, 100)):
    if not values:
        return {p: None for p in pcts}
    ordered = sorted(values)
    n = len(ordered)
    out = {}
    for p in pcts:
        idx = min(n - 1, max(0, round((p / 100.0) * (n - 1))))
        out[p] = ordered[idx]
    return out


def cmd_distribution(args):
    chunks = _load_chunks()
    texts = [c["text"] for c in chunks if c.get("text")]
    if not texts:
        print("No sentence text found in chunks.json.")
        return

    scored = [(_score(t)[0], t) for t in texts]
    scores = [s for s, _ in scored]

    print(f"Scored {len(scores)} real sentences from {paths.CHUNKS_FILE}")
    print("\nCalibrated hook_strength percentiles:")
    for p, v in _percentiles(scores).items():
        print(f"  p{p}: {v:.4f}" if v is not None else f"  p{p}: n/a")

    saturated = sum(1 for s in scores if s >= 0.999)
    print(f"\nFraction saturated at 1.0: {saturated / len(scores):.3f}  (want < ~5%)")

    ranked = sorted(scored, key=lambda x: -x[0])
    print("\nTop 20:")
    for s, t in ranked[:20]:
        print(f"  {s:.3f}  {_safe(t[:90])!r}")
    print("\nBottom 20:")
    for s, t in ranked[-20:]:
        print(f"  {s:.3f}  {_safe(t[:90])!r}")

    # Quotability sanity check while we're here — the other signal this eval run also caught
    # saturated in the audit (see clip_scoring.QUOTABILITY_IDF_FLOOR/CEIL's comment).
    from multimodal_engine import MultimodalEngine, STOPWORDS
    import re as _re
    idf = MultimodalEngine.compute_corpus_idf(texts)
    avg_idfs = []
    for t in texts:
        expanded = MultimodalEngine._expand_contractions(t.lower())
        words = [w for w in _re.findall(r"\b[a-zA-Z]+\b", expanded) if w not in STOPWORDS]
        if words:
            avg_idfs.append(sum(idf.get(w, 1.0) for w in words) / len(words))
    if avg_idfs:
        print("\nQuotability avg_idf percentiles (for QUOTABILITY_IDF_FLOOR/CEIL calibration):")
        for p, v in _percentiles(avg_idfs).items():
            print(f"  p{p}: {v:.4f}" if v is not None else f"  p{p}: n/a")


def _text_for(chunks_by_key, video_id, sentence_idx):
    return chunks_by_key.get((video_id, sentence_idx))


def cmd_labels(args):
    chunks = _load_chunks()
    chunks_by_key = {(c["video_id"], c["sentence_idx"]): c["text"] for c in chunks}

    with open(args.labels, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rows = data.get("labels", [])

    hook_scores, nonhook_scores = [], []
    skipped = 0
    for row in rows:
        text = _text_for(chunks_by_key, row["video_id"], row["sentence_idx"])
        if text is None:
            print(f"  WARNING: {row['video_id']}#{row['sentence_idx']} not found in "
                  f"chunks.json — skipping (library may have been re-ingested).")
            skipped += 1
            continue
        score, _cues = _score(text, ablate=args.ablate)
        (hook_scores if row["is_hook"] else nonhook_scores).append(score)

    n = len(hook_scores) + len(nonhook_scores)
    print(f"Labeled rows: {n} ({len(hook_scores)} hook, {len(nonhook_scores)} not-hook), "
          f"{skipped} skipped")
    if not hook_scores or not nonhook_scores:
        print("Need at least one labeled example in each class to compute separation.")
        return

    def _median(vals):
        s = sorted(vals)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0

    hook_median = _median(hook_scores)
    nonhook_median = _median(nonhook_scores)
    print(f"Hook-class median: {hook_median:.4f}   Non-hook-class median: {nonhook_median:.4f}"
          f"   Delta: {hook_median - nonhook_median:+.4f}  (want >= +0.20)")

    # ROC-AUC via the Mann-Whitney U statistic (rank-sum, ties averaged) — no sklearn
    # dependency needed for one number.
    from collections import deque

    combined = sorted(hook_scores + nonhook_scores)
    n = len(combined)
    ranks = [0.0] * n  # 1-indexed rank per position in `combined`
    i = 0
    while i < n:
        j = i
        while j < n and combined[j] == combined[i]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j

    value_positions = {}
    for idx, v in enumerate(combined):
        value_positions.setdefault(v, deque()).append(idx)

    rank_sum_hook = 0.0
    for v in hook_scores:
        idx = value_positions[v].popleft()
        rank_sum_hook += ranks[idx]

    n1, n2 = len(hook_scores), len(nonhook_scores)
    auc = (rank_sum_hook - n1 * (n1 + 1) / 2.0) / (n1 * n2)
    print(f"ROC-AUC: {auc:.4f}  (want >= 0.70)")

    verdict = "PASS" if auc >= 0.70 and (hook_median - nonhook_median) >= 0.20 else "BELOW BAR"
    print(f"\nAcceptance bar (AUC >= 0.70, median delta >= 0.20): {verdict}")


def cmd_suggest(args):
    chunks = _load_chunks()
    chunks_by_key = {(c["video_id"], c["sentence_idx"]): c["text"] for c in chunks}
    with open(args.labels, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rows = data.get("labels", [])

    # Suggest FLOOR/CEIL from the RAW blend (pre-calibration), not the already-calibrated
    # score, since that's what HOOK_RAW_FLOOR/CEIL actually gate.
    hook_raw, nonhook_raw = [], []
    for row in rows:
        text = _text_for(chunks_by_key, row["video_id"], row["sentence_idx"])
        if text is None:
            continue
        cand = {"_opening_text": text}
        cues = cs._hook_lexical_cues(text)
        lex_raw = min(1.0, sum(cs.HOOK_CUE_WEIGHTS[k] * v for k, v in cues.items()))
        matrix = cs._archetype_matrix()
        sem_raw = None
        if matrix is not None:
            import numpy as np
            from vector_store import EMBEDDING_MODEL
            vec = EMBEDDING_MODEL.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
            sem_raw = float(np.max(matrix @ vec))
        raw = cs.HOOK_SEM_WEIGHT * (sem_raw or 0.0) + cs.HOOK_LEX_WEIGHT * lex_raw
        (hook_raw if row["is_hook"] else nonhook_raw).append(raw)

    if not nonhook_raw or not hook_raw:
        print("Need labels in both classes to suggest constants.")
        return

    suggested_floor = _percentiles(nonhook_raw)[5]
    suggested_ceil = _percentiles(hook_raw)[95]
    print(f"Suggested HOOK_RAW_FLOOR = p5(non-hook raw)  = {suggested_floor:.4f}")
    print(f"Suggested HOOK_RAW_CEIL  = p95(hook raw)     = {suggested_ceil:.4f}")
    print(f"\nCurrently baked in: HOOK_RAW_FLOOR={cs.HOOK_RAW_FLOOR}  HOOK_RAW_CEIL={cs.HOOK_RAW_CEIL}")
    print("(These are corpus-percentile-derived, not label-derived — the labeled set "
          "supersedes them once it's large enough to trust p5/p95 on. Update the comment "
          "block above clip_scoring.WEIGHTS with the new numbers and today's date if you "
          "apply this suggestion.)")


def cmd_clips(args):
    if not os.path.exists(paths.CLIPS_FILE):
        print(f"No clips file at {paths.CLIPS_FILE} — run Analyze on a video first.")
        return
    with open(paths.CLIPS_FILE, "r", encoding="utf-8") as f:
        clips = json.load(f)
    if not clips:
        print("clips.json is empty.")
        return
    print(f"{len(clips)} persisted clip(s):")
    for clip_id, clip in clips.items():
        signals = clip.get("signals", {})
        print(f"  {clip_id}: hook_strength={signals.get('hook_strength', 'n/a')}  "
              f"composite={clip.get('composite', 'n/a')}  "
              f"mode={clip.get('analysis_mode', 'n/a')}  title={clip.get('title', '')[:60]!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--distribution", action="store_true", help="Percentiles + top/bottom 20 over the real corpus")
    parser.add_argument("--labels", nargs="?", const=os.path.join(os.path.dirname(__file__), "hook_labels.yaml"),
                         help="Path to a hand-labeled yaml (default eval/hook_labels.yaml) — AUC / separation report")
    parser.add_argument("--suggest", action="store_true", help="Suggest FLOOR/CEIL from --labels' hand-labeled set")
    parser.add_argument("--clips", action="store_true", help="Re-score/print the openings in data/clips.json")
    parser.add_argument("--ablate", choices=["sem", "lex"], default=None,
                         help="Zero one half of the blend before scoring (used with --labels)")
    args = parser.parse_args()

    default_labels_path = os.path.join(os.path.dirname(__file__), "hook_labels.yaml")
    ran_anything = False

    if args.distribution:
        cmd_distribution(args)
        ran_anything = True
    if args.labels is not None:
        cmd_labels(args)
        ran_anything = True
    if args.suggest:
        if not args.labels:
            args.labels = default_labels_path
        cmd_suggest(args)
        ran_anything = True
    if args.clips:
        cmd_clips(args)
        ran_anything = True

    if not ran_anything:
        parser.print_help()


if __name__ == "__main__":
    main()
