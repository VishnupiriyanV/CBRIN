#!/usr/bin/env python
"""
Eval harness for Vault's search pipeline (IMPROVEMENT-PLAN.md 2.1) — "5 test queries
return the correct moment" made measurable instead of anecdotal.

Usage (from backend/):
    python eval/run_eval.py
    python eval/run_eval.py --queries eval/queries.yaml --verbose
    python eval/run_eval.py --mode visual_scenes --queries eval/visual_queries.yaml
    python eval/run_eval.py --compare        # dense-only vs dense+BM25 hybrid retrieval

Metrics:
    Recall@1 / Recall@3 / Recall@5 — did a correct result appear in the top K?
    MRR — mean reciprocal rank of the first correct result (0 if none in top-k).
    Mean seek error (sec) — for queries with a correct result found, how far off is that
        result's start_sec from the expected window (0 if inside it)? This is the number
        that maps directly to "jump to moment lands in the wrong place."
    False positive rate — fraction of NEGATIVE queries (about topics NOT in the library)
        that returned anything at all. This is the one metric that actually decides whether
        the empty state means something: a negative query returning *any* result is the
        exact failure mode this harness exists to catch (a demo confidently returning a
        wrong clip) — see IMPROVEMENT-PLAN.md 2.1's "non-negotiable" negative set.

A positive result counts as "correct" if its video_id matches AND its [start_sec, end_sec]
window overlaps the query's expected [expected_start_sec, expected_end_sec] window.
"""
import argparse
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vector_store import VectorStore  # noqa: E402


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return a_start <= b_end and b_start <= a_end


def _seek_error(result_start: float, expected_start: float, expected_end: float) -> float:
    if expected_start <= result_start <= expected_end:
        return 0.0
    return min(abs(result_start - expected_start), abs(result_start - expected_end))


def _is_correct(result: dict, expected_video_id: str, expected_start: float, expected_end: float) -> bool:
    if result.get('video_id') != expected_video_id:
        return False
    return _overlaps(result.get('start_sec', 0), result.get('end_sec', 0), expected_start, expected_end)


def run_eval(store: VectorStore, queries_path: str, search_mode: str = None, top_k: int = 5):
    with open(queries_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    positives = data.get('positive', [])
    negatives = data.get('negative', [])

    recall_hits = {1: 0, 3: 0, 5: 0}
    reciprocal_ranks = []
    seek_errors = []
    per_query_rows = []

    for q in positives:
        mode = search_mode or q.get('search_mode', 'spoken')
        resp = store.search(query=q['query'], top_k=top_k, search_mode=mode)
        results = resp.get('results', [])

        rank = None
        for i, r in enumerate(results):
            if _is_correct(r, q['video_id'], q['expected_start_sec'], q['expected_end_sec']):
                rank = i + 1
                break

        if rank is not None:
            for k in recall_hits:
                if rank <= k:
                    recall_hits[k] += 1
            reciprocal_ranks.append(1.0 / rank)
            seek_errors.append(_seek_error(results[rank - 1]['start_sec'], q['expected_start_sec'], q['expected_end_sec']))
        else:
            reciprocal_ranks.append(0.0)

        per_query_rows.append((q['query'], rank, len(results)))

    n_pos = len(positives)

    false_positives = 0
    for q in negatives:
        mode = search_mode or q.get('search_mode', 'spoken')
        resp = store.search(query=q['query'], top_k=top_k, search_mode=mode)
        if resp.get('results'):
            false_positives += 1

    n_neg = len(negatives)

    metrics = {
        "n_positive": n_pos,
        "n_negative": n_neg,
        "recall@1": recall_hits[1] / n_pos if n_pos else None,
        "recall@3": recall_hits[3] / n_pos if n_pos else None,
        "recall@5": recall_hits[5] / n_pos if n_pos else None,
        "mrr": sum(reciprocal_ranks) / n_pos if n_pos else None,
        "mean_seek_error_sec": sum(seek_errors) / len(seek_errors) if seek_errors else None,
        "false_positive_rate": false_positives / n_neg if n_neg else None,
    }
    return metrics, per_query_rows


def _fmt(x):
    return "n/a" if x is None else f"{x:.2f}"


def _fmt_pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _print_report(label: str, metrics: dict, rows, verbose: bool):
    print(f"\n=== {label} ===")
    print(f"  Positive queries: {metrics['n_positive']}   Negative queries: {metrics['n_negative']}")
    print(f"  Recall@1: {_fmt_pct(metrics['recall@1'])}   Recall@3: {_fmt_pct(metrics['recall@3'])}   Recall@5: {_fmt_pct(metrics['recall@5'])}")
    print(f"  MRR: {_fmt(metrics['mrr'])}")
    print(f"  Mean seek error: {_fmt(metrics['mean_seek_error_sec'])}s (among queries with a correct result found)")
    print(f"  False positive rate on negatives: {_fmt_pct(metrics['false_positive_rate'])}")
    if verbose:
        print("\n  Per-query:")
        for query, rank, n_results in rows:
            status = f"rank {rank}" if rank else "NOT FOUND"
            print(f"    [{status:>10}] ({n_results} results) {query}")


def main():
    parser = argparse.ArgumentParser(description="Vault search eval harness")
    parser.add_argument("--queries", default=os.path.join(os.path.dirname(__file__), "queries.yaml"))
    parser.add_argument("--mode", default=None, help="Force search_mode for every query (default: per-query 'search_mode' field, else 'spoken')")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--verbose", action="store_true", help="Print per-query rank/result count")
    parser.add_argument("--compare", action="store_true", help="Compare dense+BM25 hybrid retrieval vs dense-only (BM25 disabled)")
    args = parser.parse_args()

    store = VectorStore()
    if not store.chunks:
        print("Library is empty — ingest content (or start the backend once to trigger "
              "auto re-chunking of stale data) before running eval.")
        sys.exit(1)

    if args.compare:
        metrics_hybrid, rows_hybrid = run_eval(store, args.queries, args.mode, args.top_k)
        _print_report("dense + BM25 hybrid (current config)", metrics_hybrid, rows_hybrid, args.verbose)

        original_bm25 = store.bm25_index
        store.bm25_index = None
        metrics_dense, rows_dense = run_eval(store, args.queries, args.mode, args.top_k)
        store.bm25_index = original_bm25
        _print_report("dense-only (BM25 disabled)", metrics_dense, rows_dense, args.verbose)

        print("\n=== Delta (hybrid - dense-only) ===")
        for key in ("recall@1", "recall@3", "recall@5", "mrr", "false_positive_rate"):
            a, b = metrics_hybrid.get(key), metrics_dense.get(key)
            if a is not None and b is not None:
                print(f"  {key}: {a - b:+.3f}")
    else:
        metrics, rows = run_eval(store, args.queries, args.mode, args.top_k)
        _print_report("Vault search eval", metrics, rows, args.verbose)


if __name__ == "__main__":
    main()
