#!/usr/bin/env python
"""
Eval harness for ENGINE's narrative clip generation (ENGINE-PLAN.md Phase 6), extending the
pattern already established by backend/eval/run_eval.py: "do not tune thresholds by eye."

Usage (from backend/):
    python eval/clip_eval.py
    python eval/clip_eval.py --queries eval/clip_queries.yaml --verbose
    python eval/clip_eval.py --compare-modes     # heuristic vs LLM-backed beat extraction

Metrics:
    mid_sentence_start_rate — fraction of ALL generated candidates whose start_sec does not
        land exactly on a sentence boundary. MUST be 0 — this is the regression guard on
        ENGINE's core claim ("cannot cut between a setup and its punchline by construction"
        implies, more basically, "cannot start mid-sentence at all"). A non-zero value here
        means the candidate-construction code has regressed, not that a threshold needs
        retuning.
    setup_containment_rate — for each hand-labeled example with a required_setup_idx, does
        the best-matching generated candidate's start_sentence_idx fall at or before it?
        This is the empirical version of the guarantee test_narrative_engine.py checks in
        isolation, now measured against realistic multi-beat transcripts.
    mean_boundary_error_sec — for examples where some candidate overlaps the hand-labeled
        window at all, how far off (start+end averaged) is the best-matching candidate.
    mean_iou — interval Intersection-over-Union between the best-matching candidate and the
        hand-labeled window, averaged over examples with a nonzero-overlap match.
    coverage_rate — fraction of hand-labeled examples for which ANY generated candidate
        overlapped the expected window at all (a candidate has to exist before its boundary
        can be judged).

There is no real hand-labeled creator library in this checkout (backend/data/ is empty and
gitignored) — see eval/clip_queries.yaml's header for why these are synthetic fixture
transcripts, and how to point this harness at a real library instead.
"""
import argparse
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import llm_client  # noqa: E402
import narrative_engine as ne  # noqa: E402


def _iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return inter / union if union > 0 else 0.0


def _generate_candidates(sentences, mode: str):
    """mode: 'heuristic' or 'llm'. Returns (candidates, actually_used_mode)."""
    if mode == "llm":
        if not llm_client.is_configured():
            return None, "llm_unavailable"
        try:
            beats = ne.extract_beats(sentences)
        except llm_client.LLMUnavailable:
            return None, "llm_unavailable"
    else:
        beats = ne.heuristic_beats(sentences)

    candidates = ne.beats_to_candidates(sentences, beats)
    return candidates, mode


def _mid_sentence_start_rate(all_candidates, sentence_starts: set) -> float:
    if not all_candidates:
        return 0.0
    bad = sum(1 for c in all_candidates if c["start_sec"] not in sentence_starts)
    return bad / len(all_candidates)


def run_eval(queries_path: str, mode: str = "heuristic", verbose: bool = False):
    with open(queries_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    videos = data.get("videos", [])
    all_candidates = []
    all_sentence_starts = set()

    example_rows = []
    skipped_no_candidates = 0

    for video in videos:
        sentences = video["sentences"]
        all_sentence_starts.update(s["start_sec"] for s in sentences)

        candidates, used_mode = _generate_candidates(sentences, mode)
        if candidates is None:
            skipped_no_candidates += len(video.get("examples", []))
            continue
        all_candidates.extend(candidates)

        for example in video.get("examples", []):
            best = None
            best_iou = 0.0
            for cand in candidates:
                iou = _iou(cand["start_sec"], cand["end_sec"], example["expected_start_sec"], example["expected_end_sec"])
                if iou > best_iou:
                    best_iou = iou
                    best = cand

            required_idx = example.get("required_setup_idx")
            if best is None:
                example_rows.append({
                    "label": example["label"], "video_id": video["video_id"],
                    "found": False, "iou": 0.0, "boundary_error": None, "setup_contained": None,
                })
                continue

            boundary_error = (
                abs(best["start_sec"] - example["expected_start_sec"]) +
                abs(best["end_sec"] - example["expected_end_sec"])
            ) / 2.0
            setup_contained = (
                best["start_sentence_idx"] <= required_idx if required_idx is not None else None
            )
            example_rows.append({
                "label": example["label"], "video_id": video["video_id"],
                "found": True, "iou": best_iou, "boundary_error": boundary_error,
                "setup_contained": setup_contained,
            })

    n_examples = len(example_rows)
    found_rows = [r for r in example_rows if r["found"]]
    contained_rows = [r for r in found_rows if r["setup_contained"] is not None]

    metrics = {
        "mode": mode,
        "n_examples": n_examples,
        "n_candidates_generated": len(all_candidates),
        "mid_sentence_start_rate": _mid_sentence_start_rate(all_candidates, all_sentence_starts),
        "coverage_rate": len(found_rows) / n_examples if n_examples else None,
        "mean_iou": sum(r["iou"] for r in found_rows) / len(found_rows) if found_rows else None,
        "mean_boundary_error_sec": sum(r["boundary_error"] for r in found_rows) / len(found_rows) if found_rows else None,
        "setup_containment_rate": (
            sum(1 for r in contained_rows if r["setup_contained"]) / len(contained_rows) if contained_rows else None
        ),
    }
    return metrics, example_rows


def _fmt(x):
    return "n/a" if x is None else f"{x:.3f}"


def _fmt_pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _print_report(label: str, metrics: dict, rows, verbose: bool):
    print(f"\n=== {label} ===")
    print(f"  Examples: {metrics['n_examples']}   Candidates generated: {metrics['n_candidates_generated']}")
    print(f"  mid_sentence_start_rate: {_fmt_pct(metrics['mid_sentence_start_rate'])}  (must be 0.0%)")
    print(f"  coverage_rate: {_fmt_pct(metrics['coverage_rate'])}")
    print(f"  mean_iou: {_fmt(metrics['mean_iou'])}")
    print(f"  mean_boundary_error_sec: {_fmt(metrics['mean_boundary_error_sec'])}")
    print(f"  setup_containment_rate: {_fmt_pct(metrics['setup_containment_rate'])}  (must be 100% — hard constraint)")
    if verbose:
        print("\n  Per-example:")
        for r in rows:
            status = "NOT FOUND" if not r["found"] else f"iou={r['iou']:.2f} err={r['boundary_error']:.1f}s contained={r['setup_contained']}"
            print(f"    [{r['video_id']}] {r['label']}: {status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", default=os.path.join(os.path.dirname(__file__), "clip_queries.yaml"))
    parser.add_argument("--mode", default="heuristic", choices=["heuristic", "llm"])
    parser.add_argument("--compare-modes", action="store_true", help="Run heuristic vs LLM side by side")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.compare_modes:
        metrics_h, rows_h = run_eval(args.queries, "heuristic", args.verbose)
        _print_report("heuristic (degraded mode)", metrics_h, rows_h, args.verbose)

        if llm_client.is_configured():
            metrics_l, rows_l = run_eval(args.queries, "llm", args.verbose)
            _print_report("LLM-backed", metrics_l, rows_l, args.verbose)
            print("\n=== Delta (LLM - heuristic) ===")
            for key in ("mean_iou", "setup_containment_rate", "coverage_rate"):
                a, b = metrics_l.get(key), metrics_h.get(key)
                if a is not None and b is not None:
                    print(f"  {key}: {a - b:+.3f}")
        else:
            print("\n(VAULT_LLM_API_KEY not set — skipping LLM-backed comparison. "
                  "Set it in .env to quantify what the key buys over heuristic mode.)")
    else:
        metrics, rows = run_eval(args.queries, args.mode, args.verbose)
        _print_report(f"ENGINE clip eval ({args.mode})", metrics, rows, args.verbose)

        if metrics["mid_sentence_start_rate"] and metrics["mid_sentence_start_rate"] > 0:
            print("\nREGRESSION: mid_sentence_start_rate must be 0. Candidate construction is broken.")
            sys.exit(1)


if __name__ == "__main__":
    main()
