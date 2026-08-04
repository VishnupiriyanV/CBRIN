---
title: Vault — Semantic Search for Your Own Content
status: Active — MVP built, hardening in progress; ENGINE (Layer 3) and STUDIO (Layer 4) built on top
version: 0.5 (post-build revision)
owner: TBD
last-updated: 2026-08-04
supersedes: v0.4 (2026-08-04, pre-ENGINE/STUDIO revision)
---

# Product Requirements Document: Vault

> Vault is Layer 1 of the CreatorBrain concept. Layer 3 (ENGINE, narrative-aware clip generation) and Layer 4 (STUDIO, six text-in/text-out creator tools) have since been built on top of it — see §4.4 and §4.5. This document remains the record of the core semantic-search loop that the other layers depend on.

**This is a revision, not a fresh draft.** v0.1 described what was going to be built. This version describes what *was* built, where it diverged, and what has to be true before the demo can be shown as evidence for anything. Companion documents: `IMPROVEMENT-PLAN.md` (file-level defect detail for Vault) and `creator-tools-integration-spec.md` (STUDIO's six tools, mapped to this repo).

---

## 1. Problem

Creators with a large back-catalog (podcast episodes, YouTube videos, newsletters) cannot search what they've already said. YouTube search only indexes titles and descriptions, not spoken content. The result: creators re-cover topics they've already addressed, can't find their own best material to repurpose, and lose the value of their own back-catalog.

There is currently no product that lets a creator type a plain-language question and get back the exact moment, across their whole library, where they said it.

*(Unchanged from v0.1. The problem statement survived contact with the build.)*

## 2. Goal

Prove one thing: **semantic search beats keyword search on a creator's own content.** A query like "when did I talk about imposter syndrome" should return the right clip even if that exact phrase was never spoken.

**Revision to v0.1:** the original goal was "ship a working demo in two days." That shipped, and then some. The goal is now **"make the demo's claims true and measurable."** The gap between what the code appears to do and what it actually does is the central risk — see §5.

## 3. Target user

A single creator (or small team) with an existing library of long-form audio/video content — YouTube, podcast, or raw files — who wants to find and reuse things they've already said.

**Primary use case:** "I remember saying something like X. Where?"

---

## 4. What actually got built

v0.1 scoped a search bar over a local vector index. The delivered system is substantially larger. Recording it here so scope decisions are made against reality.

### 4.1 Delivered beyond the original scope

| Capability | Status | Notes |
|---|---|---|
| YouTube ingest via transcript API + oEmbed metadata | Working | No OAuth, single URL at a time |
| Local file upload + Whisper transcription | Working | Local `base` model, or OpenAI API if key present |
| Cross-encoder reranking (`ms-marco-MiniLM-L-6-v2`) | Working | Not in v0.1 scope |
| CLIP visual/keyframe indexing | Partial — see §5.6 | Not in v0.1 scope |
| Disk persistence + restart survival | Working | Answers v0.1 open question #3 |
| Highlights / bookmarks | Working backend, partial UI | Note field unreachable from UI |
| Export (JSON / ZIP / CSV) + library import | Working | Not in v0.1 scope |
| In-app playback with seek, for both local and YouTube | Working | Answers v0.1 open question #2 — both are supported |
| Failed-ingest visibility with error messages | Working | Not in v0.1 scope |

### 4.2 Technical stack as built

Diverges from v0.1 §9 in two significant ways.

| Layer | v0.1 planned | As built | Why it matters |
|---|---|---|---|
| Transcription | Whisper API | Local Whisper `base`, API optional | `base` is the accuracy floor for everything downstream |
| Embeddings | `text-embedding-3-small` | `all-MiniLM-L6-v2` (384-dim, local) | Free and offline; weaker, and dilution effects are real at 384 dims |
| Vector store | ChromaDB | JSON + NumPy `.npy`, brute-force cosine | Fine at this scale; full-file rewrite on every save won't hold past ~10k chunks |
| Reranking | *not planned* | Cross-encoder, added | Good addition; its score is currently misrepresented in the UI |
| Backend | FastAPI | FastAPI | As planned |
| Frontend | SPA | React + Vite + Tailwind | As planned |

**Model choice is now a product decision, not an implementation detail.** Local models mean zero cost and no API key, but `base` Whisper mangles proper nouns and technical vocabulary — exactly the high-value search terms. See §8, Phase 4.

### 4.3 Current library

The library is currently empty (0 videos) as of this revision — the one test video was removed during manual testing. Every retrieval-quality claim in this document is unverified until a real test library is re-ingested (§9).

### 4.4 ENGINE (Layer 3) — as built

Narrative-aware clip generation on top of Vault's indexed sentences. Delivered per `ENGINE-PLAN.md`'s build plan (that document is now superseded by this section and has been removed — it described a completed build while still reading "not started").

```
Vault (read-only to ENGINE)        ENGINE
─────────────────────────         ────────
store.chunks ──sentences──►  narrative_engine ──beats──► clip_scoring ──► clip_renderer ──► .mp4
store.videos ──metadata────►                                                    ▲
data/keyframes/media ───────►  media_service, word_timing ──────────────────────┘
                                jobs.py drives all of it off the request thread
```

**Storage** (`backend/data/`): `clips.json`, `brand_kit.json`, `words/{video_id}.json`, `media/{video_id}.mp4`, `clips/{clip_id}/{preset}.mp4`.

**Core guarantee.** Every clip is a contiguous range of `MultimodalEngine.segment_transcript_into_sentences` output with its full dependency chain intact — it is structurally impossible for ENGINE to cut between a setup and its punchline. `clip_eval.py` regression-guards a **0% mid-sentence-start rate**. No fabricated numbers: ranking is five named signals rendered as a breakdown, never a "predicted engagement %".

**Disclosed v1 limitations:**
- **Static center-crop reframing.** An off-centre speaker is badly framed; face-tracking crop is the known v2 addition. Disclosed in-product next to the aspect-ratio picker.
- **Captions are Pillow-rendered PNGs, not libass subtitles** — deliberate, since the bundled `imageio-ffmpeg` static build's subtitle-filter support isn't guaranteed. Gives exact control over brand fonts/colors/per-word highlighting at the cost of a custom render pipeline.
- **Degraded mode**, same pattern as Vault's reranker fallback: no LLM key → heuristic beats (discourse markers, Q/A pairing, cross-encoder similarity to bundled archetypes), `degraded: true` surfaced in the UI.

### 4.5 STUDIO (Layer 4) — as built

Six text-in/text-out AI creator tools from `creator-tools-integration-spec.md`, reusing ENGINE-era infrastructure (`llm_client`, `jobs.py`) rather than the no-code SaaS stack the spec was originally written against. Full detail, guardrail-by-guardrail mapping, and per-tool spec live in `creator-tools-integration-spec.md`.

**Delivered:** shared foundation (Voice Profile, Platform Rules config, run history, usage meter, transcript parser, `studio_runner`/`studio_prompts`), all `/api/studio/*` routes, all six tool backends with their guardrails, and a full frontend (Studio nav, six tool screens, Voice Profile/Platform Rules/Run History panels). 71 backend unit tests cover the guardrail mechanisms with a mocked LLM; one live end-to-end run (Repurposer, through the actual browser UI against a real model) confirmed the run→poll→render→regenerate pipeline and framework-preservation guardrail hold against real output, not just mocks.

**Not yet built:** `backend/eval/studio_eval.py`, the committed-fixture conformance harness against real LLM output the STUDIO integration plan calls for (unit tests mock the LLM; nothing yet runs the guardrails against live generations as a repeatable, CI-style check). This is the same "do not tune by eye" gap `run_eval.py`/`clip_eval.py` already closed for Vault/ENGINE — open until STUDIO gets its own version.

**Deliberate divergence from Vault/ENGINE's degraded-mode pattern:** STUDIO hard-gates on `llm_configured` rather than falling back to a heuristic. A rule-based "repurpose my newsletter" has no honest non-LLM equivalent — unlike search (BM25 fallback) or ENGINE (discourse-marker heuristic), a degraded STUDIO output would be worse than an explicit "no key configured" state.

---

## 5. Known defects — blocking correctness

These are the reason this revision exists. Full detail in `IMPROVEMENT-PLAN.md` §1–§2.

### 5.1 The index on disk is incompatible with the search code
Search builds and merges result windows using `sentence_idx`. No chunk in `data/chunks.json` has that field. Every chunk reads as `0`, which makes the merge condition always true — so every candidate from a video collapses into one blob with fabricated timestamps, and "jump to moment" lands in the wrong place. **This breaks user story #3 and #4 below.**

### 5.2 Sentence chunking never runs
Stored chunks are 45-second sliding windows from the fallback branch. The sentence-level small-to-big pipeline the code documents is dead in practice. The segmenter also crashes on multi-sentence Whisper segments and produces one giant chunk for unpunctuated auto-captions.

### 5.3 Nothing measures accuracy
v0.1 §10 set "5 test queries return the correct moment" as the bar. Nothing tests this. No eval harness exists, so no tuning decision can be justified and no quality claim can be defended.

### 5.4 The empty state is unreachable
The relevance threshold sits below the noise floor for the embedding model, so unrelated chunks clear it routinely. The product cannot currently say *"you haven't covered this"* — it returns a confident wrong answer instead. **This breaks user story #5, and it is the more damaging failure mode in a demo.**

### 5.5 Two of four search modes are decorative
`HYBRID`, `QUESTIONS`, `VISUAL`, `TOPICS` are offered in the UI. Only `VISUAL` branches in code; the other three are byte-identical. There is also no lexical retrieval anywhere, so "hybrid" is a misnomer — proper nouns, product names, and guest names are the known weak spot.

### 5.6 Visual search is not moment-level for YouTube
Every chunk of a YouTube video shares the same video thumbnail as its "keyframe," so all chunks have identical visual embeddings. Visual search over YouTube content can rank whole videos but never moments — while the UI badges each result as visually indexed.

### 5.7 The displayed match percentage is not a similarity
The "% match" figure is a sigmoid of a cross-encoder logit — a ranking signal on an arbitrary scale, not comparable across queries. A wrong-looking 84% costs more trust than showing no number.

---

## 6. User stories — revised with status

| # | Story | Priority | Status |
|---|---|---|---|
| 1 | I upload or point to 10–20 videos/audio files so Vault can index them. | P0 | Works per-file; blocked at scale by no ingest progress (§7.3) |
| 2 | I type a plain-language query and get the moments where I discussed that topic, even in different words. | P0 | Works, quality unverified (§5.3) |
| 3 | Each result shows source file, text snippet, and timestamp. | P0 | **Broken** — timestamps unreliable (§5.1) |
| 4 | I click a result and jump straight to that moment. | P1 | **Broken** — seeks to wrong position (§5.1) |
| 5 | If nothing matches well, I see a clear empty state, not forced results. | P1 | **Broken** — threshold miscalibrated (§5.4) |
| 6 | I bookmark a moment and come back to it later. | P1 | Works; note field unreachable from UI |
| 7 | I export results and take them into my editing workflow. | P2 | Works (JSON / CSV / ZIP) |
| 8 | I search what was *shown on screen*, not just what was said. | P2 | Works for local files only (§5.6) |

Stories 6–8 are new — they describe capability that was built but never specified.

**STUDIO (Layer 4) — new stories:**

| # | Story | Priority | Status |
|---|---|---|---|
| 9 | I paste a newsletter/blog post and get platform-native repurposed posts, with any framework I coined preserved verbatim. | P1 | Works — verified live |
| 10 | I paste or pick an indexed transcript and get show notes, chapters, and titles, with timestamps only where real cue data supports them. | P1 | Works (unit-tested; not yet live-verified) |
| 11 | I get YouTube title/hook/thumbnail-text ideas tagged by formula, never silently truncated past 60 characters. | P2 | Works (unit-tested) |
| 12 | I paste a batch of comments and get suggested replies, with hostile/sensitive/business ones flagged for me to handle personally instead of auto-replied to. | P1 | Works (unit-tested) |
| 13 | I paste one caption and get platform-optimized versions for six platforms, editable per-platform rules, never truncated over the limit. | P2 | Works (unit-tested) |
| 14 | I paste a timestamped stream transcript and get a ranked moment map — the tool refuses untimed input rather than guessing. | P2 | Works (unit-tested) |

---

## 7. Requirements

### 7.1 Ingestion
- Accept local video/audio files (single, multi-select, or folder), or a YouTube URL. No OAuth.
- **New:** video IDs must be content-addressed (SHA-1 of file bytes), not `hash()`-derived. Current IDs change across process restarts, silently duplicating the library.
- **New:** duplicate uploads must be rejected before transcription runs, not after.

### 7.2 Transcription
- Preserve segment-level timestamps.
- **New:** model tier must be user-selectable (`base` / `small` / `medium`), defaulting to `small`. `faster-whisper` makes `small` cheaper than today's `base`.

### 7.3 Chunking + embedding
- Group transcript into 1–3 sentence units with an enforced hard cap (~40s / 80 words) for unpunctuated transcripts.
- Store chunk text, source, start/end timestamp, `sentence_idx`, and vector together.
- **New:** the index must carry a version stamp. On load, a stale or missing version forces a full re-chunk rather than silently running against incompatible data.
- **New:** embedding must be incremental. Full-corpus re-embed on every added video is O(n²) across a library build.
- **New:** ingest must run as a background job with per-stage progress (download → transcribe → chunk → embed → keyframes), polled by the existing progress modal. A 60-minute podcast currently blocks a single HTTP request for roughly an hour.

### 7.4 Search
- Accept natural language, return ranked moments with source, timestamp, snippet, and confidence.
- **New:** retrieval must be genuinely hybrid — BM25 fused with dense vectors via Reciprocal Rank Fusion. Dense-only search is structurally weak on proper nouns.
- **New:** the relevance cutoff applies to the *reranker* score, not the retriever's, and is calibrated from an eval negative set rather than chosen by eye.
- **New:** search modes reduce to two honest ones — **Spoken** and **On-screen** — unless `questions` and `topics` are given real implementations.

### 7.5 Results UI
- Search bar, result list, per-result jump-to-moment, empty state below threshold.
- **New:** confidence is shown as a calibrated bucket (Strong / Possible / Weak) or omitted. No raw percentage.
- **New:** when a query falls just below cutoff, show near-misses under "Nothing strong — closest matches" rather than a bare empty state.

### 7.6 STUDIO requirements

- Hard input cap ~15,000 words, enforced before any LLM call (`usage.check_input_words`), plus a 60-runs/hour rate limit — both checked synchronously in the route handler so the UI gets an immediate error rather than a failed job.
- **Timestamp honesty is structural, not a prompt instruction.** Show Notes and Clip-Moment Finder models emit sentence indices only; the backend derives every displayed time from parsed cue data. Clip-Moment Finder hard-rejects (422) untimed input rather than producing a plausible-looking but fabricated moment map.
- **No account-connection invariant.** No platform SDK, no outbound call to any social platform, anywhere in STUDIO. Copy-to-clipboard is the only path from generated text to a platform.
- Copy-to-clipboard on every output block; regenerate targets one block, not the whole run.
- Voice Profile (niche/audience/tone/banned words/CTA style/sample content) injected into every tool's system prompt; banned words are additionally enforced as a post-hoc strip, not just a prompt instruction.
- Usage recorded per run (tokens in/out, model) and surfaced via a usage badge — the reconciliation of the spec's "credit ledger" concept with this app having no accounts or billing.

---

## 8. Non-functional requirements

| | v0.1 target | Revised | Note |
|---|---|---|---|
| Query latency | <2s for 20 videos | <2s for 20 videos | Currently met; reranking is the cost centre |
| Pipeline cost | <$5 for 20 videos | **$0** | Local models; API path optional |
| Ingest throughput | *unspecified* | ≤1× realtime, with visible progress | Currently ~1× realtime and *invisible* — the real blocker |
| Scale | tens of videos | ≤50k chunks (~200 hrs) on brute force | Beyond that needs a real vector index *and* a new persistence layer |
| Startup time | *unspecified* | <30s cold | Currently unbounded — retries permanently-failing CLIP embeds every boot |

---

## 9. Success criteria — revised

v0.1's bar ("5 test queries work") is not measurable and can be satisfied by cherry-picking. Replaced with:

**The MVP is "done" when:**

1. A **15-video test library** is fully indexed, committed, and reproducible from a clean clone.
2. An eval harness (`backend/eval/`) reports Recall@1, Recall@5, MRR, and mean seek error against a committed `queries.yaml`.
3. **Recall@5 ≥ 0.80** on 30 positive queries whose target moment is phrased differently from the spoken words. *(This is the actual "wow" claim, stated as a number.)*
4. **False-positive rate ≤ 0.10** on 10 negative queries about topics genuinely absent from the library. The empty state must fire.
5. **Mean seek error ≤ 5 seconds** — "jump to moment" lands where the user expects.
6. A user unfamiliar with the project can search, read a result, and jump to the right timestamp without instruction.

Criteria 2–5 are new and non-negotiable. Without them there is no way to tell whether a change helped, and no way to defend a quality claim to anyone.

**This remains a validation artifact, not a launch.** Success is "does the core idea hold up," not adoption or retention.

---

## 10. Non-goals (unchanged, and still worth defending)

- Multi-platform account linking (YouTube OAuth, podcast RSS auto-sync, TikTok, newsletter ingestion)
- Analytics/performance correlation (Lens), clip generation (Engine), concept testing (Lab), localization (Globe)
- Content Gap Detector and other derived insights — **though note §5.4: fixing the empty state is the prerequisite for this entire category**
- Multi-user accounts, billing, auth
- Non-English transcription

**Newly added non-goal:** LLM-generated summaries or answers over *retrieved search results*. This prohibits Vault from silently summarizing what a query returned — it does not prohibit STUDIO's user-initiated generation over user-supplied text (a newsletter, comments, a transcript the user pasted or picked). That boundary was ambiguous before STUDIO existed; it's Vault's retrieval output that stays untouched by generation, not "no generation anywhere in the app."

**Hard architectural invariants (STUDIO and any future layer), promoted from `creator-tools-integration-spec.md`'s platform-constraints section:** no TikTok/Instagram/YouTube posting or account connection, no quota-heavy platform-API discovery/analytics features, no scraping of contact info or competitor content. Check whether a platform already ships a feature natively (e.g. YouTube's own thumbnail A/B testing) before building a competing one.

**Candidate for cut:** CLIP visual search. It's the most complex subsystem, it's fundamentally broken for YouTube content (§5.6), and v0.1 didn't scope it. Cutting it would meaningfully shrink the surface area that has to be correct. Flagged as an open question rather than a decision.

---

## 11. Design system

Visual direction adapted from the xAI-inspired design kit (`DESIGN-x_ai.md`) — near-black canvas, white outline pills, restrained type, no shadows.

### Palette

| Token | Value | Use in Vault |
|---|---|---|
| `canvas` | `#0a0a0a` | Page background |
| `canvas-card` | `#191919` | Result cards |
| `canvas-soft` | `#1a1c20` | Search input fill |
| `ink` | `#ffffff` | Primary text, headline |
| `body` | `#dadbdf` | Snippet text |
| `body-mid` / `mute` | `#7d8187` | Timestamps, source labels |
| `hairline` | `#212327` | All borders |
| `accent-sunset` | `#ff7a17` | Sparingly: matched phrase inside a snippet |

### Typography

- Headline: `display-lg` / `display-md`, Universal Sans (substitute: Inter, weight 400, `-1.8px` to `-1.2px` tracking).
- Section eyebrow ("YOUR LIBRARY", "RESULTS"): `caption-mono`, GeistMono, uppercase, positive tracking — signature move from the kit.
- Snippet body: `body-md`. Timestamp / source label: `body-sm` in `mute`.
- No bold anywhere. Weight 400 throughout.

### Constraints from the kit

- Dark canvas only — no light mode.
- Every interactive element is a pill (9999px) except cards, which stay at 8px.
- Hairline borders carry all elevation. No drop shadows anywhere.

### Resolved: kit is the source of truth

Previously flagged as drift: the build used `shadow-2xl`, `shadow-xl`, `backdrop-blur-2xl`, and `animate-pulse` throughout, and rounded cards at 12–16px rather than 8px, contradicting the "hairline borders carry all elevation, no shadows" constraint above.

**Decision: the kit wins.** All box-shadow and backdrop-blur utility classes were stripped from `App.tsx`, `Header.tsx`, `HighlightsPanel.tsx`, `IndexingProgressModal.tsx`, `LibraryModal.tsx`, `SearchBar.tsx`, and `VideoPlayerModal.tsx`; `animate-pulse` status dots/badges were replaced with static ones; card radii were normalized to `rounded-lg` (8px), leaving `rounded-full` pills untouched. Hairline borders now carry elevation everywhere, as the kit specifies.

**Still open, found while building STUDIO:**
- `src/components/engine/*` (ClipCard, ClipStudio) still use `rounded-2xl`, not the mandated `rounded-lg` — not reconciled in this revision. New `src/components/ui/*` and `src/components/studio/*` components use `rounded-lg` throughout.
- `animate-fade-in` is referenced in ~12 places across the codebase but is defined in neither `tailwind.config.js` nor `index.css` — a silent no-op class, not an animation that quietly stopped working.
- `DESIGN-x_ai.md`, cited above as the source of the design kit, is not present in this repo.

**New primitives** (`src/components/ui/`, previously empty): `cn.ts` (clsx + tailwind-merge, installed but unused until now), `Button`, `Pill`/`Tag`, `Panel`, `CopyButton` (+ `useCopyToClipboard` hook, extracted from `ResultCard.tsx`'s one-off implementation), `OutputBlock`, `CappedTextarea`. Built for STUDIO; available to any future surface.

---

## 12. Roadmap

Sequencing rationale: correctness before measurement, measurement before tuning. Tuning an unmeasured system that returns merged blobs is wasted work. Full task detail in `IMPROVEMENT-PLAN.md` §5.

| Phase | Focus | Est. | Exit criteria |
|---|---|---|---|
| **1** | **Correctness** — index/code mismatch, chunking rewrite, stable IDs, dedup, deps | ~1 day | Re-ingest produces chunks with `sentence_idx`, 1–3 sentences each; merging no longer collapses a video into one result |
| **2** | **Measurement** — 15-video library, `queries.yaml`, eval harness, **baseline recorded** | ~0.5 day | `run_eval.py` prints Recall@1/@5, MRR, seek error, false-positive rate |
| **3** | **Accuracy** — BM25 + RRF, threshold calibration, concept extraction, mode honesty | ~1–2 days | Every change ships with its eval delta; anything that doesn't beat baseline is reverted, not rationalised |
| **4** | **Usability** — background jobs, `faster-whisper`, honest scores, filters, keyboard nav | ~1–2 days | 60-min podcast ingests with visible progress; §9 criterion 6 passes with a real stranger |
| **5** | **Hardening** — incremental embedding, index locking, relative URLs, design reconciliation | ongoing | Clean clone reproduces the running environment |

**If only three things get done:** fix the chunking/index mismatch (§5.1–5.2), build the eval harness (§5.3), add BM25 hybrid retrieval (§7.4). The first makes results correct, the second makes them measurable, the third is the largest single accuracy gain available.

| **6** | **STUDIO foundation** — Voice Profile, Platform Rules, transcript parser, usage meter, run history, `studio_runner`/`studio_prompts`, all `/api/studio/*` routes, UI primitives | Delivered | 204/204 backend tests pass; live end-to-end run verified through the browser against a real model |
| **7** | **STUDIO's six tools** — backend guardrails + frontend screens for Repurposer, Show Notes, Titles, Replies, Captions, Moments | Delivered | All six unit-tested (guardrail register in `creator-tools-integration-spec.md`); only Repurposer live-verified end-to-end so far |
| **8** | **STUDIO eval harness** — `backend/eval/studio_eval.py`, real-LLM conformance checks against committed fixtures | Not started | Same "don't tune by eye" gap `run_eval.py`/`clip_eval.py` closed for Vault/ENGINE |

---

## 13. Open questions

**Resolved from v0.1:**
- ~~Whose content library is the test set?~~ → Currently ad-hoc (one English lesson, one databases explainer). Phase 2 requires a deliberate 15-video set with clear usage rights.
- ~~Is "jump to moment" required for local files?~~ → Both are implemented: HTML5 seek for local, `&t=` deep link plus embed for YouTube.
- ~~Does the demo need to survive restart?~~ → Yes, and it does. Persistence works.

**Still open:**
- **Is CLIP visual search core, or scope creep?** (§10) Highest-leverage scope decision available.
- **Local Whisper or OpenAI API as the canonical path?** Both are maintained, they produce different segment shapes and different accuracy. Picking one halves the ingest code.
- **What's the real target library size?** Drives whether the JSON+NumPy persistence layer survives or gets replaced. 20 videos and 2,000 videos are different products.
- **Does "hybrid" mean modes, or fusion?** Users read the mode pill as a filter; the code intends it as a retrieval strategy. The vocabulary needs settling before more modes get added.

**New from STUDIO:**
- Which niche should tool 1 (Repurposer) anchor on if this ever becomes more than a local tool? Still open — see `creator-tools-integration-spec.md`.
- Whether STUDIO ever ships beyond local single-user use — the whole design (no auth, singleton JSON state, usage meter instead of billing) assumes it doesn't.

---

## 14. Risks

- **The demo currently overstates itself.** Merged-blob results with wrong timestamps, a match percentage that isn't a similarity, mode pills that do nothing, and visual-index badges on chunks with identical embeddings. Shown to a technical audience before Phase 1–2 land, this costs more credibility than showing nothing. *Highest risk in this document.*
- **Chunking quality remains the main technical risk** — flagged in v0.1, and the diagnosis held. It went wrong in a way v0.1 didn't anticipate: not bad boundaries, but a pipeline that silently fell back to the branch it was designed to avoid. Budget real time for tuning, and verify what's *running* rather than what's written.
- **Small library, small proof.** 2 videos proves nothing; even 15 says little about hundreds of hours. Flag this explicitly whenever the demo is used as evidence for the wider CreatorBrain thesis.
- **Transcript accuracy is the invisible ceiling.** Whisper `base` errors propagate into chunks, embeddings, concepts, and suggested queries. No amount of retrieval tuning recovers a word the transcriber never got right.
- **Scope has already grown ~3× past v0.1 while the core loop stayed broken.** Export, import, highlights, and visual search all shipped before basic retrieval correctness was verified. The Phase ordering above exists specifically to counter that pattern.
- **STUDIO's guardrails are proven against mocks, not yet against a corpus of real model output.** 71 unit tests assert each guardrail (timestamp honesty, framework preservation, flagged-comment isolation, never-truncate, type diversity) holds against a mocked `llm_client.call_llm`. One live run confirmed the mechanism end-to-end on a single real generation. `backend/eval/studio_eval.py` (§12 Phase 8, not started) is what would close this the way `run_eval.py`/`clip_eval.py` did for Vault/ENGINE.
