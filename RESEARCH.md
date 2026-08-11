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

---

### Gap 1 — Boundaries are scored but never moved

**Effort: S. Payoff: high, immediately visible.**

**Now:** `clip_scoring._boundary_cleanliness` (line 274) reads `word_timing.silence_gap_before/after` and rewards a 0.2–0.6s breathing gap, tapering past ~1s. But nothing ever snaps the cut. `narrative_engine._build_candidate_for_seed` (line 445) takes `sentences_by_idx[candidate_start]["start_sec"]` verbatim, and Whisper sentence boundaries drift ±200–300ms.

Net effect: a clip with a genuinely clean pause available 180ms away is *marked down* for a boundary we could have fixed. We measure the defect and ship it.

**Research:** prosodic boundaries are marked by pre-boundary lengthening plus phrase-initial acceleration, not by amplitude alone (Kalimuthu et al., PLOS One). Onset detection is an explicit precision/recall trade: tight windows clip real speech onsets, loose windows land in silence or catch mouth clicks. Guard bands are the standard mitigation.

**Change:** a snapping pass between candidate construction and scoring.

- Search ±400ms around each nominal cut for the silence trough, using word-level timings we already have.
- Snap to it; if no trough is found in the window, leave the boundary untouched.
- Apply ~120ms pre-roll on the in-point so the first phoneme survives, and a short tail on the out-point.
- Re-score `_boundary_cleanliness` *after* snapping, so the signal measures the boundary we actually cut.

This is the most visible defect class in every autoclipper on the market — the "it cut off my first 0.3 seconds" complaint is exactly this. It is also the cheapest item on this list: `word_timing.py` already has the gap functions.

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
C. Solve       narrative deps + referential deps → candidates     (determ.)     [have + Gap 2]
D. Rank        text + acoustic signals, then MMR                  (no LLM)      [have + Gaps 3,4]
E. Snap        waveform search ±400ms, guard band                 (determ.)     [Gap 1]
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
