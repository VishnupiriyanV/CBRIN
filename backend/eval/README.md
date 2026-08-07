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

`queries.yaml` is grounded in the only real video in the library right now:
- `local-f718cb618763` — a short English-lesson vlog ("Test2")

6 positive + 10 negative queries. The YouTube "fascinating history of Databases" video
(`yt-6szdySvorzA`) this file used to also cover is no longer in the library (removed at
some point independent of the eval harness) — its 8 positive queries were dropped rather
than left permanently failing. Re-add them if that video is re-ingested. The plan's target
is 25-40 positive queries across a 15-video test library (3.5) — that requires real source
videos this environment doesn't have. Extend `queries.yaml` as the library grows; don't pad
it with queries that don't map to real content, that defeats the point.

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

**v4 — agentic-pivot audit, same threshold (0.08), library down to 1 video.** Running
`scripts/repair_index.py --rebuild` to fix an out-of-sync `visual_embeddings.npy` surfaced
(but didn't cause) a real data problem: a leaked pytest-fixture chunk (`video_id: "vid-b"`,
text "This video covers python testing frameworks like pytest", `indexed_at:
2026-01-01T00:00:00`) had contaminated the live `backend/data/chunks.json` — exactly the
test-suite data-clobber failure mode `repair_index.py`'s own docstring describes. Because
that chunk was orphaned (no `videos.json` entry), the *first* `--rebuild` pass "recovered"
it by fabricating a videos.json entry for it, and a subsequent eval run scored **0%
recall** — not a real regression, but `queries.yaml` referencing a stale local video ID
(`local-39470`, pre-dating a re-ingest under a new content-hash ID) and a YouTube video that
had separately been removed from the library at some point. Removed the `vid-b`
contamination via `VectorStore.delete_video()` (keeps chunks/embeddings in lockstep, unlike
hand-editing the JSON/npy files), corrected `queries.yaml`'s video ID, and dropped the 8
queries for the now-missing YouTube video (see "Current library" above). Re-ran clean:

```
Positive queries: 6   Negative queries: 10
Recall@1: 83.3%   Recall@3: 83.3%   Recall@5: 83.3%
MRR: 0.83
Mean seek error: 15.40s (among queries with a correct result found)
False positive rate on negatives: 0.0%
```

Consistent with v3's calibration (78.6-85.7% recall band) — the threshold did not need to
move. The one miss ("flowers printed on the umbrella") is the same known gap from v3: the
correct chunk doesn't enter the top-30 candidate pool for that phrasing at all, so it's a
retrieval-recall gap, not a threshold problem. `agent_tools.deep_research`'s multi-query
expansion (paraphrase the query, search each, fuse via RRF) is the intended fix for exactly
this failure mode — added as part of the agentic pivot, not evaluated against this harness
yet since `run_eval.py` only exercises `store.search()` directly, not the agent tool layer.

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

---

## Hook signal calibration (`hook_eval.py`)

`clip_scoring.py`'s `hook_strength` — one of the five signals in ENGINE's clip composite,
carrying the largest single weight (0.25) — used to feed `(archetype, opening_text)` pairs
to `cross-encoder/ms-marco-MiniLM-L-6-v2`, a query→passage *relevance* model, and take
`sigmoid(max_logit)`. Every real clip opening in this library scored **0.0001–0.0005**, a
constant 0% in the UI, regardless of content. The replacement blends bi-encoder archetype
similarity (`all-MiniLM-L6-v2`, the model `vector_store.py` already loads) with explicit
lexical hook cues (question opener, curiosity-gap phrasing, second-person address,
superlative, negation, numeral), calibrated the same way `RERANK_RELEVANCE_THRESHOLD` above
was: against measured percentiles and a hand-labeled set, not by eye.

```bash
cd backend
python eval/hook_eval.py --distribution              # corpus percentiles + top/bottom 20
python eval/hook_eval.py --labels                     # AUC / class separation vs hook_labels.yaml
python eval/hook_eval.py --clips                      # re-score the openings in data/clips.json
python eval/hook_eval.py --suggest                    # recommended FLOOR/CEIL from --labels
python eval/hook_eval.py --ablate sem                  # AUC with the semantic half zeroed
python eval/hook_eval.py --ablate lex                  # AUC with the lexical half zeroed
```

**Acceptance bar:** ROC-AUC ≥ 0.70 and hook-class median score at least 0.20 above
non-hook-class median, measured against `hook_labels.yaml` (50 hand-labeled sentences drawn
from this checkout's real `chunks.json`, stratified across the score range for labeling
diversity — see that file's header for the sampling method).

### v0 — cross-encoder relevance model (the bug)

```
backend/data/clips.json (8 real persisted clips): hook_strength 0.00001 – 0.00051
```

Every value rounds to 0% at `Math.round(v * 100)` in `ScoreBreakdown.tsx`. Root cause:
ms-marco-MiniLM-L-6-v2 is trained to answer "is this passage a relevant search result for
that query", not "is this sentence stylistically hook-shaped" — an ordinary opening sentence
is not a relevant result for the "query" *"You won't believe what happened next."*, so the
logit is strongly negative before the sigmoid ever runs.

### v1 — bi-encoder + lexical blend, corpus-only calibration (2026-08-05)

Measured over the 436 real sentences in `backend/data/chunks.json`:

```
max-archetype-cosine:  p5=0.0615  p50=0.1585  p95=0.2738  p99=0.3514  max=0.4112
lexical-cue blend:     p50=0.0    p75=0.20    p95=0.35    p99=0.50
correlation(sem, lex): -0.075   (near-independent)
```

`(cos + 1) / 2` — the textbook mapping `_taste_match` uses for cosine similarity — would have
compressed the entire real archetype-cosine spread into roughly `[0.48, 0.71]`; `HOOK_RAW_FLOOR`/
`HOOK_RAW_CEIL` map from the measured range instead. First guess at the weight split was
0.45 semantic / 0.55 lexical, reasoned from the near-zero correlation alone — see v2, that
reasoning doesn't actually hold up against labels.

### v2 — weight split against hand labels

`hook_labels.yaml` created: 50 real sentences (10 judged a hook, 40 not), stratified across
the semantic-cosine score range so the set isn't accidentally all-easy or all-hard. Swept the
semantic/lexical weight split from 0/1 to 1/0 in steps of 0.02, checking AUC *and* median
delta together (checking AUC alone is what produced the 0.45/0.55 guess above, and it hid
that 0.45/0.55 has a visibly weaker median gap than a more lexical-heavy split):

```
sem=1.00 lex=0.00   AUC=0.702   delta=+0.04
sem=0.50 lex=0.50   AUC=0.695   delta=+0.09
sem=0.45 lex=0.55   AUC=0.695   delta=+0.12
sem=0.20 lex=0.80   AUC=0.668   delta=+0.22   <- selected
sem=0.00 lex=1.00   AUC=0.605   delta=+0.20
```

`sem=0.20/lex=0.80` clears the median-delta bar (+0.22 ≥ +0.20) while staying close to the
best observed AUC (0.67 vs 0.70) — the best *joint* result in the sweep, not the top AUC in
isolation. **Honest result, not a clean pass:** no split in the swept range cleared both bars
at once. `FLOOR`/`CEIL` were then re-measured for this specific split over the full,
*unbiased* 436-sentence corpus (not `hook_labels.yaml`'s own percentiles — that set is
deliberately stratified toward extremes for labeling diversity, so its percentiles would not
represent the true corpus distribution):

```
python eval/hook_eval.py --labels --distribution

Calibrated hook_strength percentiles (full corpus): p5=0.0001 p25=0.041 p50=0.130 p75=0.418
  p95=0.715 p99=1.000 max=1.000   (1.1% saturated at 1.0 — was ~100% saturated at 0% before)
Hook-class median: 0.3304   Non-hook-class median: 0.1069   Delta: +0.2235
ROC-AUC: 0.6675
```

**This is not "done."** 50 labels on a 4-video corpus (one of which is song lyrics) is enough
to catch the original bug and get a directionally-sound, spread signal — it is not enough to
trust the exact weight split with confidence. Before relying on this further: label more
sentences (aim for 100+, evenly across several more real creator videos so "hook" isn't
dominated by one channel's style), re-run the sweep, and only move `HOOK_SEM_WEIGHT`/
`HOOK_LEX_WEIGHT`/`HOOK_RAW_FLOOR`/`HOOK_RAW_CEIL` if the new sweep's joint-best point moves —
update this section (and the calibration comment above `clip_scoring.WEIGHTS`) with the new
numbers and date when it does. Don't move these on vibes.
