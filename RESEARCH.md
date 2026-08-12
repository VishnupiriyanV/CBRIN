# Research — context-aware clip extraction

**What this is:** a technical reference for the clip-extraction pipeline. Literature reviewed, which of our design decisions it validates, which gaps it exposes, and a prioritized plan mapped to files and line numbers.

**What this is not:** a direction doc. It does not set scope, pricing, or sequencing against the business plan — that lives in `STRATEGY.md`. Read this when working on `narrative_engine.py`, `clip_scoring.py`, or `word_timing.py`.

Compiled 2026-08-11. Source index in §7.

---

## 1. Scope

Reviewed: 2024–26 work on video temporal grounding, moment/highlight detection, linear and hierarchical transcript segmentation, engagement prediction, prosodic boundary detection, and diversity-aware selection. Plus the production tools (Opus Clip) and the open-source clones (`autoclip`, `AI-Youtube-Shorts-Generator`, `opensource-clipping`) for what the commodity baseline actually does.

The question driving it: **what makes a cut land in the right place, and what makes the clip make sense on its own.**

Domain matters for reading the literature. Most temporal-grounding benchmarks (QVHighlights, Charades-STA, ActivityNet) are visually driven. Our content is talking-head and podcast — the transcript carries nearly all the signal, the audio carries most of the rest, and the visual channel is close to irrelevant. Several methods that top those leaderboards are the wrong tool here; §6 lists them.

---

## 2. Design decisions the literature validates

### 2.1 Sentence-index grounding beats LLM-emitted timestamps

The most-reported failure mode in the grounding literature is that LLMs are bad at emitting precise numeric boundaries. The workarounds are elaborate:

| Method | Workaround for imprecise timestamps |
|---|---|
| ED-VTG | LLM emits a special `<INT>` token; a separate lightweight decoder regresses center/width with L1 + gIoU losses |
| TimeRefine | Predict coarse, then iteratively refine |
| MarkIt | Burn visual markers into frames so the model has discrete labels to name |

`narrative_engine._format_transcript_window` (line 77) sidesteps the problem rather than patching it: the model emits **indices into a list we control**, and `_validate_and_clean_beats` (line 84) rejects any index outside `valid_indices`. A hallucinated boundary becomes a dropped beat instead of a bad cut.

For speech-driven content this is strictly better than a regression decoder, and it costs nothing. **Do not replace this with timestamp emission.**

### 2.2 Structure first, then score

TF-SELECTOR (SVHighlights: 320 videos, ~2h average) is a *training-free* pipeline that beat trained SOTA by +2.50 HIT@1 / +4.04 HIT@K / +2.95 IoU using our shape: segment into semantically coherent units, then score whole segments with an LLM.

Its central finding is the one that matters for us: **shot boundaries alone fragment semantically continuous content.** It fixes that by merging adjacent shots when ASR words span the boundary within a 1-second interval — arriving at the setup/payoff insight from the video side.

That a training-free pipeline with one reasoning stage beats trained end-to-end models on long video is direct support for the current architecture, and for keeping the LLM confined to one stage.

---

## 3. Gaps, in priority order

Priority is payoff-per-unit-effort, with dependencies respected. Each gap states what the code does today, what the research says, and the concrete change.

| # | Gap | Effort | Status |
|---|---|---|---|
| 1 | Boundaries scored but never snapped | S | **done** — 2026-08-11 |
| 2 | `self_contained` asserted, not proven | M | **done** — 2026-08-11 |
| 3 | Prosody is speech-rate only | M | **done** — 2026-08-11 (hook term deferred) |
| 4 | Dedup isn't diversity | S | open |
| 5 | Sliding windows can't see long-range deps | L | open |

Pause-aligned boundary selection (under Gap 1) also landed, in `narrative_engine` rather than the scorer.

---

### Gap 1 — Boundaries are scored but never moved

**Effort: S. Payoff: high, immediately visible.**

**Now:** `clip_scoring._boundary_cleanliness` (line 274) reads `word_timing.silence_gap_before/after` and rewards a 0.2–0.6s breathing gap, tapering past ~1s. But nothing ever snaps the cut. `narrative_engine._build_candidate_for_seed` (line 445) takes `sentences_by_idx[candidate_start]["start_sec"]` verbatim.

The drift is worse than the ASR literature's ±200–300ms would suggest, because it isn't ASR drift. `multimodal_engine.py:362` stores `math.floor(sentence_start_sec)` / `math.ceil(sentence_end_sec)` — **whole-second quantisation**, confirmed against the corpus, where every `start_sec`/`end_sec` in `data/chunks.json` is an integer. So candidates are wrong by up to **1.0s on each side**, in two distinguishable ways:

- `floor()` moves the in-point earlier → up to a second of dead air before the first word. Fatal for a short-form hook, where the first second is the whole pitch.
- When the *previous* sentence's last word ends after that floored second, the same cut opens on the tail of a foreign word. This is the "starts mid-sentence" complaint, and it is why a plain silence-trim pass is not sufficient.

Net effect: a clip with a genuinely clean pause available is *marked down* for a boundary we could have fixed. We measure the defect and ship it.

**Research:** prosodic boundaries are marked by pre-boundary lengthening plus phrase-initial acceleration, not by amplitude alone (Kalimuthu et al., PLOS One). Onset detection is an explicit precision/recall trade: tight windows clip real speech onsets, loose windows land in silence or catch mouth clicks. Guard bands are the standard mitigation.

**Change:** a snapping pass between candidate construction and scoring.

- Search ±1.2s around each nominal cut (whole-second quantisation plus Whisper's own segment slop) for the true speech onset/offset, using word-level timings we already have.
- Snap to it; if no trough is found in the window, leave the boundary untouched.
- Apply ~120ms pre-roll on the in-point so the first phoneme survives, and a short tail on the out-point.
- Re-score `_boundary_cleanliness` *after* snapping, so the signal measures the boundary we actually cut.

This is the most visible defect class in every autoclipper on the market — the "it cut off my first 0.3 seconds" complaint is exactly this.

#### Implemented 2026-08-11 — and what it turned up

`word_timing.snap_clip_bounds()` plus a rewritten `clip_scoring._boundary_cleanliness`. Two findings that were not visible before measuring:

**The metric was inverted.** `_boundary_cleanliness` called `silence_gap_before/after` on the cut timestamp — "how much dead air sits next to my cut" — which is *maximised by cutting in the middle of a pause*, the exact defect. Measured over the 14 real persisted clips, adding a correct snapper moved the old signal from 0.342 to 0.113 mean and made **12 of 14 clips score worse**, purely because tightening onto speech removed the dead air the formula was rewarding. A signal that punishes the fix is worse than no signal.

The replacement (`phrase_gap_before/after`) measures the pause around the clip's first and last *word* — a property of the speech, not of cut placement. It is snap-invariant by construction, which the same 14 clips confirm (before == after on every one).

**Sentence boundaries are not acoustic boundaries.** Measuring `phrase_gap_before` at all 426 sentence starts in the corpus:

| p5 | p25 | p50 | p75 | p90 | p95 |
|---|---|---|---|---|---|
| 0.000 | 0.000 | 0.120 | 0.620 | 0.920 | 1.220 |

**49% have no recorded pause at all.** Sentence segmentation in `multimodal_engine` is text-driven (punctuation and length), so half the boundaries the solver can choose from don't coincide with a pause. Snapping fixes *placement within* a boundary; it cannot make a mid-phrase boundary into a phrase boundary.

That is the ceiling on this gap, and raising it is a `narrative_engine` change, not a scoring one.

#### Pause-aligned boundary selection — implemented 2026-08-11

`narrative_engine._select_bounds()`. When the duration bounds leave slack, the solver now prefers a sentence boundary that lands on a real pause.

Three properties it holds by construction:

- **Expansion-only.** The in-point may move earlier (adds context, cannot drop a required setup); the out-point may move later (the payoff stays in). Neither direction can violate the dependency guarantee, so boundary quality is never traded against it. Capped at 3 sentences back / 2 forward.
- **Never pads to reach `MIN_CLIP_SEC`.** The tight window must clear the duration bounds on its own, exactly as before. Turning a rejected short candidate into a padded one would contradict "fewer clips beats a broken one."
- **Never widens for a marginal gain.** `MIN_BOUNDARY_GAIN = 0.15` (~0.18s of extra pause on one edge); ties break toward the tightest clip.

The scorer is *injected*, not imported — `clip_scoring.make_boundary_scorer(video_id)` passed down from `main.py`. That keeps `narrative_engine` pure (no `video_id`, no filesystem, tests pass sentence dicts alone), and it shares one definition with `_boundary_cleanliness` so the thing the solver optimises and the thing the ranker reports cannot drift apart. With no scorer the path is byte-identical to the old first-fit behaviour.

Measured by replaying the 14 persisted clips' sentence ranges as seeds against the real transcripts and word timings:

| | value |
|---|---|
| alignment fired | 5 / 14 (36%) |
| mean boundary score | 0.193 → **0.371** |
| clips worsened | **0** |
| sentences added when it fired | 2.0 mean, 3 max |
| clips at the 0.0 floor | 9 → 8 |

Caveat worth keeping in view: all five firings are on one video — the only one in the corpus with ordinary conversational speech. The other two have no usable pauses anywhere near their candidate boundaries, which is why the floor barely moves. The direction is right; the sample cannot support a magnitude.

One correction that came out of the rewrite: `phrase_gap_*` returns `None` for two unrelated reasons — the clip opens or closes the recording (a perfect boundary) and there is no word-timing file at all (unknown). Scoring the second as 1.0 would rank an un-timed video's clips *above* properly measured ones. The old `silence_gap_*` formula had the mirror bug, scoring missing timing as the worst possible boundary. Both are dishonest; `BOUNDARY_UNKNOWN_SCORE = 0.5` reports it as unknown, consistent with how `_taste_match` and `_emotional_delta` already handle absent evidence.

Context for reading those percentiles: faster-whisper emits contiguous word timings — only 5–12% of inter-word transitions carry any gap — so a non-zero gap is strong evidence of a real pause, while a zero gap is weaker evidence of its absence. The signal is more trustworthy high than low.

---

### Gap 2 — `self_contained` is asserted, not proven

**Effort: M. Payoff: strengthens the core differentiating claim.**

**Now:** `clip_scoring._self_containedness` (line 205) counts `_DEIXIS_TERMS` in the first ten words, checks `_DEIXIS_PHRASES`, and adds ±0.2 based on the LLM's `self_contained` boolean.

That is a heuristic wrapped around an unverified model claim — which sits badly next to the rest of the design, where the whole point is that the setup constraint is structural rather than something an LLM can shrug off (`narrative_engine.py` module docstring, line 1). We enforce narrative dependency and merely *ask about* referential dependency.

**Research:** coreference resolution is a mature, well-benchmarked task with local, fast implementations. The relevant predicate is a dangling anaphor — a mention whose antecedent lies outside the excerpt.

**Change:** resolve coreference over the full transcript once at ingest, cache the mention→antecedent map alongside chunks. Then for each candidate, check whether every mention inside `[start_sentence_idx, end_sentence_idx]` has its antecedent inside the same range.

The output is not a score. It is a **guarantee**: *this clip contains zero dangling references.* Same category of claim as the setup constraint, and demonstrable.

Architecturally this generalizes the solver rather than bolting something on: `requires_setup_from_idx` is a narrative dependency, a dangling anaphor is a referential dependency. Both are dependency edges the same expansion logic in `_build_candidate_for_seed` can satisfy — extend backward until the antecedent is included, subject to the same `MAX_CLIP_SEC` bound and the same "fewer clips beats a broken one" rule at line 467.

Keep the deixis heuristic as the degraded-mode path, mirroring `heuristic_beats`.

#### Implemented 2026-08-11

`backend/reference_resolver.py`, satisfied by `narrative_engine._extend_for_references()`, reported by a rewritten `clip_scoring._self_containedness`.

**The dependency-type generalisation held.** `requires_setup_from_idx` is a narrative dependency; a dangling anaphor is a referential one. Both are backward-expansion edges, so the solver satisfies them with the same machinery — the second type cost a ~40-line function, not a second solver.

Expansion order in `_build_candidate_for_seed` is now: narrative (hard, never relaxed) → referential (soft, relaxed only against `MAX_CLIP_SEC`) → pause alignment (a preference). Correctness, then comprehensibility, then polish. Running alignment earlier would let a cosmetic boundary preference decide whether a pronoun resolves.

Referential dependencies are **soft** by necessity, not by preference: nearly every spoken sentence carries some anaphor, so hard-failing would reject almost every candidate. What survives relaxation is reported rather than hidden — `dangling_reference_indices` carries the literal offending sentence indices, and `_self_containedness` penalises them at 0.35 each. **The LLM's `self_contained` boolean is now ignored entirely.** It was the only input to that signal that nothing could check.

Measured over the corpus:

| | |
|---|---|
| sentences opening with an unbound anaphor | 24 / 439 (5%) |
| clips that would have opened on a dangling reference | 1 / 14 (7%) |
| resolved by expansion | 1 / 1 |
| still dangling after expansion | 0 |

7% sits at the 5% base rate, which is the right sanity check — but it means this is a *correctness guarantee, not a score mover* on this corpus. Its value is that it cannot be violated, not that it fires often. Two caveats: the measurement replays existing clip boundaries as synthetic seeds, so real LLM-chosen beats would trip it at a different rate; and `dangling_reference_indices` is `None` rather than `[]` when resolution is off, because an empty list claims "we checked and nothing escapes" and asserting that for a run that never looked would reproduce the exact defect this replaces.

**What it does not claim.** This is not full coreference resolution. It does not identify *which* entity a pronoun refers to — it detects that a sentence *opens* with an unbound anaphor and therefore needs what came before, leaning on the locality of pronominal anaphora rather than a parser the project doesn't ship. It excludes first/second person (deictic, always resolvable), pleonastic *it* ("it turns out…", "it rained…"), and demonstrative determiners on temporal or self-referential nouns ("this week", "this video" — deictic to the moment of speaking or to the artifact already on screen).

Known over-firing, stated rather than tuned away: a bare demonstrative heading an artifact reference — *"This is probably going to be one of my shortest lessons ever"* — is deictic but surface-indistinguishable from the anaphoric *"This is why nobody does it"* without a parser. Roughly a fifth of flagged sentences are this pattern. Left in on purpose, because the asymmetry runs one way: a false positive costs a clip a sentence or two longer than it needed to be, a false negative ships a clip that opens on nothing.

Swapping in a real coref model (fastcoref, spaCy) means replacing `referential_dependencies()` and nothing else — the solver and scorer consume a `{sentence_idx: earliest required idx}` mapping and never look inside it. That upgrade is a genuine dependency decision for a local-first desktop tool (spaCy plus a few hundred MB of weights on top of an installer that already ships torch and Whisper), so it is left as a choice rather than made silently.

---

### Gap 3 — Prosody is speech-rate only

**Effort: M. Payoff: strongest external evidence of anything on this list.**

**Now:** `clip_scoring._emotional_delta` (line 224) computes a words-per-minute delta between clip halves from `word_timing.load_words`. That is one prosodic dimension of three, and the weakest one. Pitch and energy are absent. The pipeline has no acoustic feature extraction at all.

**Research:** the ICCV VQualA 2025 engagement challenge is the strongest evidence available here — head-to-head on SnapUGC, 90,000 real short videos, engagement labels from 2,000+ users each.

| Model | Modalities | Final score |
|---|---|---|
| VideoLLaMA2-7B-AV | visual + text + **audio** | 0.695 |
| Qwen2.5-VL-7B | visual + text (newer model) | 0.664 |
| Ensemble | — | 0.710 (1st place) |

The newer, stronger vision-language model **lost to the older model that could hear.** The paper's stated conclusion is that audio should not be overlooked. Independently, TF-SELECTOR feeds raw audio volume into its scoring LLM alongside captions and ASR.

**Change:** add f0 (pitch) range/variance and RMS energy contour over the candidate window. ~50 lines with `librosa` over audio already on disk. No new model, no LLM call, no network.

- `_emotional_delta`: replace the WPM proxy with a blend over pitch range, energy delta, and speech rate. Arc delta measured acoustically is a categorically better signal than word count over time.
- `hook_strength`: a hook delivered flat is not a hook, and no amount of lexical cue matching detects that. Acoustic energy on the opening sentence is orthogonal evidence.

That orthogonality is the point. `clip_scoring.py:64` records the measured correlation between the semantic and lexical halves of `hook_strength` at **−0.075**, and cites near-independence as the reason to blend them. Acoustic features are the cheapest available source of a third independent signal — which matters given the honest state of that calibration: at 50 labels, no weight split in a 0.0–1.0 sweep cleared both the AUC and median-delta bars (line 74).

#### Implemented 2026-08-11

`backend/prosody.py`, consumed by a rewritten `clip_scoring._emotional_delta`, extracted in `main.py` alongside `word_timing.ensure_words`.

**No new dependency.** librosa is the obvious tool and drags soundfile/audioread/pooch behind it; torchaudio isn't installed. This needs coarse prosody — animated or flat — not precise f0 tracking, so it decodes with the ffmpeg already bundled for clip rendering and computes contours with numpy and scipy, both already present as scikit-learn dependencies. Nothing touches the network. Extraction runs 43 minutes of video in ~9s and caches 356KB.

Pitch is expressed in **semitones relative to the speaker's own median**, which is what makes it comparable across people rather than reporting that one voice is deeper than another. Measured baselines across the library span 98–208 Hz, so this was not optional.

`_emotional_delta` is now `0.35 × arc + 0.65 × acoustic`, where acoustic blends pitch range (0.40), energy delta (0.30), pitch direction (0.15), and speaking rate (0.15) — the old whole signal demoted to one term of four. Terms are *dropped and the remainder renormalised* when unmeasurable, never zero-filled; `window_features` returns `None` for "not measured", the same distinction `BOUNDARY_UNKNOWN_SCORE` draws.

Effect on the 14 persisted clips:

| | old (rate only) | new |
|---|---|---|
| mean | 0.124 | 0.212 |
| **stdev** | **0.100** | **0.164** |
| range | 0.016–0.308 | 0.057–0.567 |

The spread is the point — the signal now separates the monotone speaker (`yt-pWH1TF1ZfKA`, pitch range 6–8 st, every clip scoring 0.06–0.13) from the animated one (`13e5-clip-0`, 22 st with an energy delta of 0.34, scoring 0.567). The words-per-minute proxy could not see that difference; it ranked those two clips 0.109 and 0.299.

**Two DSP bugs found by measuring, not by testing.** Both would have shipped silently, and every unit test passed throughout:

1. Median `pitch_range_st` was **17.0 semitones**, p99 **32.8** (2.7 octaves) — human speaking range is ~10–12 semitones end to end. Raw f0 percentiles came back p1 = 60.2 Hz and p99 = 400.0 Hz: the `F0_MIN_HZ`/`F0_MAX_HZ` search bounds themselves, to one decimal. Frames with no real periodicity still produce an `argmax`, which lands on whichever end of the range the correlation slopes toward, so 29% of "voiced" frames were reporting the rails rather than the speaker. Fixed by requiring the peak to be an interior local maximum and raising the voicing threshold 0.3 → 0.45. Median dropped to **11.0 st**.
2. A median filter over the pitch track went in first, on the assumption these were isolated octave errors. It moved the median only 17.0 → 15.4 — which is what proved the errors were sustained rather than isolated and redirected the diagnosis. Kept, since it does remove genuine octave jumps, but it was not the fix.

Calibration floors/ceilings are the measured p5/p95 over all 439 sentences, recorded above `PITCH_RANGE_FLOOR_ST` in `clip_scoring.py`. They were invalidated once mid-implementation: calibrating against the pre-fix distribution would have baked the rail artifact permanently into the weights.

**Deferred: the `hook_strength` acoustic term.** A hook delivered flat is not a hook, and opening energy is genuinely orthogonal evidence — but `hook_strength` carries a documented calibration (`HOOK_RAW_FLOOR`/`CEIL` from a 436-sentence distribution, plus a brute-force sem/lex weight sweep against `hook_labels.yaml`). Adding a third component invalidates all of it. At 50 labels no weight split already clears both acceptance bars, so fitting a third signal on that set would be overfitting — and `clip_scoring.py:92` says it plainly: *don't move these on vibes*. Unblocked by expanding `hook_labels.yaml`, not by more code.

---

### Gap 4 — Deduplication is not diversity

**Effort: S. Payoff: prevents a specific, silent failure.**

**Now:** `narrative_engine._merge_overlapping_candidates` (line 481) collapses candidates overlapping >60% by sentence count, keeping the one with more contained beats.

That catches *temporal* overlap only. Two clips fifteen minutes apart making the same point are non-overlapping by this test, both survive, and both can rank in the top 5.

**Research:** MMR (Carbonell & Goldstein) is the standard relevance/novelty trade-off; Gygli et al. established submodular objectives with greedy selection for video summarization; the extension to multimodal is AV-MMR. The useful framing comes from the frame-selection work: the failure pair is **redundancy collapse** (picks cluster on one salient stretch) versus **coverage collapse** (picks spread uniformly and miss the good part). We are currently exposed to the first.

**Change:** after `clip_scoring.rank()` produces the composite ordering, select greedily with

```
argmax over remaining:  λ · composite − (1 − λ) · max_cosine_to_already_selected
```

using embeddings from `vector_store`'s existing `all-MiniLM-L6-v2`. Roughly 30 lines. Start λ ≈ 0.7 and tune against the eval harness.

Keep the existing overlap merge — it is doing a different job (structural dedupe) and should run first.

---

### Gap 5 — Sliding windows cannot see long-range dependencies

**Effort: L. Payoff: largest, and it raises the ceiling on everything above.**

**Now:** `narrative_engine._windows_for` (line 137) cuts at `WINDOW_SENTENCE_COUNT = 60` with `WINDOW_OVERLAP = 10` once past 6000 words.

A payoff at sentence 340 whose setup lives at sentence 12 is **structurally invisible**. No window contains both, so no LLM call can ever emit that `requires_setup_from_idx`. The solver is provably correct given the beats it receives; the windowing silently bounds which beats can exist. For a 40-minute podcast with a callback to an opening anecdote — exactly the clip most worth cutting — the guarantee is vacuous.

`_dedupe_beats` (line 255) handles the seam between windows, but seams are not the problem. Range is.

**Research:**

- **TreeSeg** — embeddings plus divisive clustering producing a binary tree over the transcript. Built specifically for ASR noise, scarce labels, and the case where the true segment count is unknown. Beat all baselines on ICSI, AMI, and the purpose-built TinyRec corpus.
- **NEST** — same conclusion from the video side: flat representations degrade sharply past 30 minutes; hierarchy is what recovers them.
- **Linear text segmentation survey** — the numbers that decide build-vs-prompt on dialogue:

| Method | Pk (lower is better) |
|---|---|
| TextTiling + BERT | 33.6 |
| ChatGPT zero-shot | 31.8 |
| Supervised TextSeg | **19.9** |

**Prompting an LLM to segment is barely better than TextTiling (1997) and far worse than a supervised model.** Do not spend LLM budget on segmentation.

**Change:** two parts.

1. Replace fixed 60-sentence windows with **topic-coherent segments** derived from embeddings we already compute — divisive clustering over sentence embeddings, TreeSeg-style, no LLM. The LLM then sees a coherent unit instead of an arbitrary 60-sentence slab, which should improve beat quality independent of the range fix.
2. Add a cheap **global linking pass**: embed each segment, find long-range referential/semantic links between segments, and permit a beat to declare `requires_setup_from_idx` pointing outside its own segment. The solver already chases transitive chains with a visited guard (line 413) and already drops deeper requirements first when duration runs long — it needs no change to consume cross-segment edges.

Sequenced last because it is the largest change and the other four are independently valuable. Sequenced *at all* because until it lands, the structural guarantee only holds within a 60-sentence horizon, and that limit should be stated honestly anywhere the claim is made publicly.

---

## 4. Reference architecture

```
A. Structure   embeddings → divisive clustering → topic tree      (no LLM)      [Gap 5]
B. Beats       LLM over coherent segments + cross-segment links   (LLM)         [have]
C. Solve       narrative deps + referential deps → candidates     (determ.)     [done]
               pause-aligned boundary selection                                 [done]
D. Rank        text + acoustic signals, then MMR                  (no LLM)      [Gap 4 open]
               pitch/energy prosody in emotional_delta                          [done]
E. Snap        onset/offset search ±1.2s, guard band              (determ.)     [Gap 1 — done]
```

Note the shape: **one LLM stage, everything else deterministic or embedding-based.** That matches TF-SELECTOR's result, and it keeps stages A, D, and E entirely offline — no network call, which preserves the local-first positioning rather than fighting it.

---

## 5. Evaluation

`backend/eval/` has the harness (`clip_eval.py`, `hook_eval.py`, `run_eval.py`). The gap is labels: 50 in `hook_labels.yaml`, over a 4-video corpus, one of which is song lyrics.

Three changes worth making:

**Rank correlation, not accuracy.** The engagement challenge reports SROCC and PLCC. For a ranked clip list that is the right target, and it is more label-efficient: pairwise judgments ("which of these two clips is better") produce usable signal at a fraction of the cost of pointwise scoring, and are far easier for a human to answer consistently.

**Pk / WindowDiff for stage A.** The standard boundary metrics. They let segmentation be validated independently instead of only ever measuring the pipeline end-to-end — which matters most for Gap 5, where a regression would otherwise surface as a diffuse drop in clip quality.

**A dangling-reference check as a hard gate.** Once Gap 2 lands, the count of clips containing a dangling anaphor should be a pass/fail in the harness, not a score to average. It is the one property we claim structurally.

Standing caveat: the corpus is too small for any of this to be conclusive. Expanding `hook_labels.yaml` and the video library is prerequisite work for trusting the weights, as `eval/README.md#hook-signal-calibration` and `clip_scoring.py:74` both already state.

---

## 6. Considered and rejected

**MLLM frame segmentation** (0/1 character per frame, output tokens doubling as foreground probabilities, segmentation loss alongside causal LM loss). Genuinely elegant, and strong numbers — 56.74 HIT@1 on QVHighlights with only 25 frames, under half what comparable methods use. Rejected: it requires training, and 25 frames over a 40-minute podcast is one frame per 96 seconds. Wrong tool for talking-head content.

**LLM-prompted segmentation.** Rejected on the Pk numbers in §3 Gap 5 — barely better than a 1997 algorithm, and it would consume LLM budget that beat extraction needs.

**Timestamp regression decoders** (ED-VTG's `<INT>` head, TimeRefine's iterative refinement). Rejected: they solve a problem sentence-index grounding does not have. See §2.1.

**Visual-heavy grounding generally.** For our domain the transcript carries nearly all the signal and audio carries most of the rest. CLIP scoring earns its place for retrieval and for B-roll-adjacent judgments; it should not drive boundary decisions.

---

## 7. Source index

| Work | Relevance |
|---|---|
| [ED-VTG: Enrich and Detect](https://arxiv.org/html/2510.17023v1) | Two-stage grounding; evidence that LLM timestamp emission is imprecise |
| [TimeRefine](https://arxiv.org/html/2412.09601v1) | Iterative temporal refinement; same underlying problem |
| [MarkIt](https://arxiv.org/pdf/2604.25886) | Training-free visual markers for temporal grounding |
| [TF-SELECTOR / SVHighlights](https://arxiv.org/html/2606.06926v2) | Training-free segment-then-score on 2h video; ASR-cued shot merging |
| [TreeSeg](https://arxiv.org/abs/2407.12028) | Hierarchical binary-tree transcript segmentation via divisive clustering |
| [NEST](https://arxiv.org/pdf/2606.19706) | Narrative event hierarchy; flat representations degrade past 30 min |
| [Linear text segmentation survey](https://aclanthology.org/2024.findings-emnlp.174.pdf) | Pk comparison: TextTiling vs ChatGPT vs supervised |
| [Engagement prediction with LMMs](https://arxiv.org/html/2508.02516v2) | ICCV VQualA 2025 winner; audio ablation on 90k videos |
| [MLLM frame segmentation](https://arxiv.org/abs/2512.12246) | 0/1-per-frame trick; considered and rejected |
| [Prosodic boundary detection](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0250969) | Acoustic signature of phrase boundaries |
| [Coreference & anaphora resolution survey](https://www.sciencedirect.com/science/article/abs/pii/S1566253519303677) | Toolchain and metrics for Gap 2 |
| [MMR](https://www.researchgate.net/publication/2269571_The_Use_of_MMR_Diversity-Based_Reranking_for_Reordering_Documents_and_Producing_Summaries) | Relevance/novelty trade-off |
| [Submodular video summarization](https://openaccess.thecvf.com/content_cvpr_2015/papers/Gygli_Video_Summarization_by_2015_CVPR_paper.pdf) | Greedy selection with approximation guarantees |
| [Adaptive greedy frame selection](https://arxiv.org/html/2603.20180) | Redundancy collapse vs coverage collapse framing |
| [autoclip](https://github.com/artbyjazi/autoclip) | Closest open-source competitor: local-first, Whisper + Ollama |
| [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) | Commodity baseline: LLM highlight detection + chunking |
| [Opus Clip virality score](https://help.opus.pro/docs/article/virality-score) | Market incumbent's scoring surface (algorithm undisclosed) |
