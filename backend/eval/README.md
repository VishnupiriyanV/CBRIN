# Vault search eval harness

Implements IMPROVEMENT-PLAN.md §2.1. Makes "does search return the right moment" a number
instead of a vibe, and gives every accuracy change in §3 something to be measured against.

## Running it

```bash
cd backend
python eval/run_eval.py                 # spoken mode, default queries.yaml
python eval/run_eval.py --verbose        # + per-query pass/fail
python eval/run_eval.py --compare        # dense+BM25 hybrid vs dense-only
python eval/run_eval.py --mode visual_scenes --queries eval/queries.yaml
```

## What it measures

- **Recall@1/@3/@5** — did a correct result land in the top K?
- **MRR** — mean reciprocal rank of the first correct result (0 if none in top-5).
- **Mean seek error (sec)** — for queries where a correct result was found, how far off is
  its `start_sec` from the expected window? Maps directly to "jump to moment lands
  in the wrong place."
- **False positive rate on negatives** — the number that actually matters for trusting the
  empty state (3.2): a negative query (about something NOT in the library) returning
  *anything* is the exact failure mode this harness exists to catch.

A result counts as "correct" if its `video_id` matches AND its `[start_sec, end_sec]`
window overlaps the query's expected window.

## Current library

`queries.yaml` is grounded in the only 2 real videos in the library right now:
- `local-39470` — a short English-lesson vlog
- `yt-6szdySvorzA` — "The fascinating history of Databases"

14 positive + 10 negative queries. The plan's target is 25-40 positive queries across a
15-video test library (3.5) — that requires real source videos this environment doesn't
have. Extend `queries.yaml` as the library grows; don't pad it with queries that don't map
to real content, that defeats the point.

## History

**v0 — before 1.1/1.2 (stale sentence_idx, sliding-window fallback chunks).** Not
measurable with this harness: the merge logic collapsed each video into ~1 blob with
fabricated timestamps before a query was ever scored. This is the state IMPROVEMENT-PLAN.md
was written against.

**v1 — after 1.1/1.2 chunking fix + 2.5 BM25 hybrid + 2.2 reranker-gated threshold, before
calibration** (`RERANK_RELEVANCE_THRESHOLD = 0.5`, an uncalibrated starting guess):

```
Recall@1: 21.4%   Recall@3: 21.4%   Recall@5: 21.4%
MRR: 0.21    Mean seek error: 25.33s    False positive rate: 0.0%
```

Investigating *why* recall was this low with `--verbose` and a debug script (see git
history) turned up a real bug, not just a bad threshold: the window-merge step (search()
step 3) had no cap on how large a merged "moment" could grow. A query whose retrieval
signal is spread across most of one video's chunks — e.g. searching a video *that is
about* databases for "database" — chain-merged nearly every adjacent sentence window into
one candidate spanning almost the entire video. That's IMPROVEMENT-PLAN.md 1.1's exact
failure mode ("jump to moment" landing on the whole video), resurfacing through a different
mechanism than the one 1.1 described, even with fully correct per-sentence `sentence_idx`
data. Added `MAX_MERGED_WINDOW_SECONDS = 90` in `vector_store.py`.

**v2 — merge-cap fix, same threshold (0.5):**

```
Recall@1: 42.9%   Recall@3: 42.9%   Recall@5: 42.9%
MRR: 0.43    Mean seek error: 12.50s    False positive rate: 0.0%
```

Doubled. With merging now bounded, sampled the reranker score distribution directly: 5
negative queries (genuinely unrelated topics) scored ~0.000-0.001 at the top; verified
true-positive matches on this library scored ~0.05-0.4+. Clean separation, nowhere near
0.5. Recalibrated `RERANK_RELEVANCE_THRESHOLD` to `0.08` and `RERANK_STRONG_THRESHOLD`
(the "Strong" vs "Possible" UI confidence bucket, 2.3) to `0.35`, both with margin above
the negative cluster.

**v3 — current (merge-cap fix + calibrated threshold):**

```
Positive queries: 14   Negative queries: 10
Recall@1: 78.6%   Recall@3: 85.7%   Recall@5: 85.7%
MRR: 0.82
Mean seek error: 21.42s (among queries with a correct result found)
False positive rate on negatives: 0.0%
```

12/14 positive queries found their correct moment, 0/10 negatives returned anything. The 2
remaining misses ("flowers printed on the umbrella", "the speaker can't help but teach
English on camera") are retrieval-recall gaps, not threshold issues — confirmed with
`RERANK_RELEVANCE_THRESHOLD` temporarily forced to `-999`: the correct chunk never entered
the top-30 candidate pool at all for those specific phrasings, so no threshold value would
have found it. Fixing that is 2.5/2.6-territory (retrieval quality), not calibration; left
for the next round given the current 2-video library doesn't provide enough queries to
tune retrieval by, only to notice this gap exists.

**Do not tune thresholds by eye.** Re-run `python eval/run_eval.py --verbose` after any
change and require both: recall goes up, false-positive rate on negatives stays at (or
near) 0%. If a change trades one for the other, it's not obviously a win — decide
deliberately.

---

## ENGINE clip eval (`clip_eval.py`)

Same rule, applied to ENGINE-PLAN.md Phase 2's narrative clip generation: "does a clip
candidate respect the sentence/setup boundaries it's supposed to" made measurable, not
asserted by fiat.

```bash
cd backend
python eval/clip_eval.py                    # heuristic (degraded) mode, default clip_queries.yaml
python eval/clip_eval.py --verbose           # + per-example pass/fail
python eval/clip_eval.py --mode llm          # LLM-backed beat extraction (needs VAULT_LLM_API_KEY)
python eval/clip_eval.py --compare-modes     # heuristic vs LLM side by side
```

### What it measures

- **mid_sentence_start_rate** — must be `0.0%`. This is the regression guard on ENGINE's
  core claim: every candidate is built from sentence boundaries, so a clip cutting mid-word
  or mid-sentence should be structurally impossible. A nonzero value means
  `narrative_engine.beats_to_candidates` has regressed, not that a threshold moved.
- **setup_containment_rate** — must be `100%`. For every hand-labeled example with a
  `required_setup_idx`, does the best-matching generated candidate's start sit at or before
  it? This is `test_narrative_engine.py`'s dependency-chain guarantee, now checked against
  full multi-beat transcripts instead of hand-built minimal fixtures.
- **coverage_rate** — fraction of hand-labeled examples for which *any* generated candidate
  overlapped the expected window at all. A candidate has to exist before its boundary can be
  judged, and this is the number that's honest about a beat-detector simply missing a beat.
- **mean_iou** / **mean_boundary_error_sec** — quality of the best-matching candidate's
  boundaries against the hand label, among examples with a match.

### Current fixtures

`clip_queries.yaml` has **no real hand-labeled creator library to draw from** —
`backend/data/` is empty and gitignored in this checkout, unlike the search eval above which
at least had 2 real ingested videos at some point. The 8 examples across 2 synthetic
"videos" are constructed transcripts designed to exercise the specific failure modes
ENGINE exists to prevent (a payoff whose setup is several sentences back). Real usage should
point this harness at an actual indexed library; see the YAML file's header comment.

### v0 — heuristic (degraded) mode, synthetic fixtures

```
Examples: 8   Candidates generated: 2
mid_sentence_start_rate: 0.0%
coverage_rate: 50.0%
mean_iou: 0.614
mean_boundary_error_sec: 6.750
setup_containment_rate: 100.0%
```

The hard constraint (`setup_containment_rate`) holds at 100% on every example a candidate
was found for — confirming the dependency-chain guarantee empirically, not just in the
isolated `test_narrative_engine.py` unit tests. `coverage_rate` at 50% is the honest cost of
degraded mode: discourse-marker/question-pairing heuristics found beats for only 2 of the 4
narrative turns per fixture video, missing the "lesson" and "closing" beats entirely because
they don't trip any of the bundled markers. This is exactly `IMPROVEMENT-PLAN.md`-style
"quality without an LLM key is materially lower" (ENGINE-PLAN.md risk #6/#7), now with a
number instead of a claim. `--compare-modes` against an LLM-backed run is the next
measurement once a `VAULT_LLM_API_KEY` is available to test against.
