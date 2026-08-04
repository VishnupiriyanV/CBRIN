---
title: Vault — Improvement Plan
status: Partially landed — see status note below
date: 2026-08-03
scope: backend/ + src/ as of current HEAD
---

# Vault Improvement Plan

Review of the actual code, not the PRD. Findings are ordered by how much they hurt: correctness bugs first, then accuracy, then honesty-of-UI, then usefulness, then hygiene.

**Status as of the STUDIO (Layer 4) revision (2026-08-04).** Section numbers below are kept stable — `prd.md` cites them directly. Landed since this was written: 1.3 (content-hash IDs), the full test suite (§4 "No tests" — now 204 tests across `backend/tests`), a complete pinned `requirements.txt`, BM25 hybrid retrieval (2.5, `rank_bm25` is a dependency), the background job queue (3.3, `jobs.py`), CORS (1.7, origins are pinned). Everything else below is still open — this is not a full re-audit, just a pointer so the cross-references in `prd.md` don't read as more current than they are.

---

## 0. State of the build

**What genuinely works:** YouTube transcript ingest, local Whisper transcription, dense retrieval with `all-MiniLM-L6-v2`, cross-encoder reranking, CLIP keyframe embedding, disk persistence, highlights, export/import, and a complete UI. This is well past a 2-day MVP.

**The core problem:** the retrieval pipeline described in the code's own docstrings is not the pipeline that is running. The persisted index was written by an older version of the chunker, and several assumptions the search code makes about that data are false. Search quality today is materially worse than the code implies.

**Library size:** 2 videos, 22 chunks, ~12 min of audio. Every quality claim is currently unverified.

---

## 1. Critical correctness bugs

### 1.1 The index on disk is incompatible with the search code
`vector_store.search()` builds windows and merges candidates using `chunk['sentence_idx']`. **No chunk in `data/chunks.json` has a `sentence_idx` field.** Every chunk therefore reads as `sentence_idx = 0`.

Consequences:
- `expanded_candidates.sort(key=(video_id, sentence_range[0]))` sorts on a constant — order is arbitrary.
- The merge test `cand_start_s <= last_end_s + 1` becomes `0 <= 1`, which is **always true**. Every candidate from the same video collapses into one merged blob.
- With a 2-video library, the top-5 results degenerate to roughly 2 results, each a smear of the whole video, with fabricated `start_sec`/`end_sec`. "Jump to moment" then jumps to the wrong place.

**Fix:** add an index-version stamp to `chunks.json`; on load, if the version is missing or stale, force a full re-chunk + re-embed. Then guard the merge path so it refuses to run when `sentence_idx` is absent.

### 1.2 Sentence chunking never actually runs
The stored chunks are 51s / 47s / 43s at starts 0, 36, 74 — exactly the 45s window with 10s overlap from the **fallback** branch, not `segment_transcript_into_sentences`. The "small-to-big sentence retrieval" architecture is dead code in practice.

Also latent in `segment_transcript_into_sentences`:
- After a flush, `sentence_start_sec` is set to `None`. If a single Whisper segment contains **two** sentences, the second flush hits `math.floor(None)` → `TypeError`, killing the whole ingest.
- If the transcript has no `.!?` at all (common for YouTube auto-captions), nothing ever flushes and the entire video becomes one giant "sentence".

**Fix:** rewrite the segmenter with an explicit state machine, reset `sentence_start_sec` to the current segment position rather than `None`, and add a hard cap (e.g. flush at 40s or 80 words regardless of punctuation). Unit-test it against: no punctuation, multi-sentence segments, empty segments, single segment.

### 1.3 Local video IDs are not stable
`transcript_service.py` uses `f"local-{abs(hash(file_name)) % 100000}"`. Python randomizes string hashing per process (`PYTHONHASHSEED`), so **the same file uploaded after a restart gets a different ID** — silent duplicates in the library, orphaned media files, and orphaned keyframes. `% 100000` also invites collisions, which would cross-link two videos' chunks.

**Fix:** `hashlib.sha1(file_bytes).hexdigest()[:12]` — content-addressed, stable, and gives you free deduplication.

### 1.4 Local uploads are never deduplicated
`/api/ingest` checks for an existing video ID; `/api/upload_transcribe` does not. Upload the same file twice and you pay for transcription twice and pollute the index. (Fixing 1.3 makes this a two-line check.)

### 1.5 Failed-ingest records create garbage rows
In `main.py`, the YouTube failure path does `vid_id = f"yt-{meta['title']}"` — a video ID built from a title string, with `youtube_id=None` so the retry has nothing to retry with. Use `yt-{video_id}` and persist the original URL.

### 1.6 Startup does unbounded work
`_load_from_disk` calls `reindex_visual_embeddings()` whenever any chunk lacks a visual embedding. For chunks that can never get one (audio-only file, dead thumbnail URL), this re-attempts CLIP encoding on **every single boot**, forever. Mark permanent failures with a `visual_status` field and skip them.

### 1.7 CORS config is invalid
`allow_origins=["*"]` with `allow_credentials=True` is rejected by browsers. Harmless today (no cookies) but wrong. Pin to `http://localhost:3000` / `:5173`.

---

## 2. Accuracy — the part that decides whether this is a real product

### 2.1 Build an eval harness before touching the ranker
The PRD's success criterion is "5 test queries return the correct moment." Nothing measures this. Every tuning decision below is guesswork until it exists.

Ship `backend/eval/`:
- `queries.yaml` — 25–40 queries per test library, each with the ground-truth `video_id` + acceptable time window.
- `run_eval.py` — reports Recall@1/@3/@5, MRR, and mean seek error in seconds.
- A `--compare` flag that diffs two configs (e.g. reranker on vs off).

Non-negotiable: include a **negative set** of ~10 queries about topics genuinely not in the library. These must return an empty state. This is the only defense against the failure mode where the demo confidently returns a wrong clip.

### 2.2 The relevance threshold is effectively off
`search()` defaults to `relevance_threshold=0.1`, and `main.py` never passes it. Cosine similarity on MiniLM for *unrelated* text sits around 0.0–0.15 — so unrelated chunks routinely clear the bar. Combined with 2.3, the empty state almost never fires and users get confident nonsense.

**Fix:** thresholds should be applied to the **reranker** score, not the retriever's. Set the retriever threshold low on purpose (it's just a candidate filter, keep top-30) and gate the final output on the cross-encoder logit. Calibrate the cutoff from the eval negative set — not by eye.

### 2.3 The displayed score is not a similarity
`item['score']` is `sigmoid(cross-encoder logit)`, and the UI renders it as "72% match" with a traffic-light colour. A ms-marco cross-encoder logit is a ranking signal with an arbitrary scale; the sigmoid of it is not a probability of relevance and is not comparable across queries.

**Fix:** either (a) show a rank badge and a calibrated three-bucket confidence (Strong / Possible / Weak) derived from eval-set percentiles, or (b) drop the number entirely. A wrong-looking 84% is worse than no number.

### 2.4 Two of the four search modes are fake
The UI offers `HYBRID`, `QUESTIONS`, `VISUAL (CLIP)`, `TOPICS`. In `vector_store.search()` only `visual_scenes` branches; `questions`, `topics`, and `hybrid` run **identical code**. Users switching modes see no change and lose trust.

**Fix — pick one:**
- Implement them: `questions` embeds against the `questions_answered` field, `topics` against `section_topic` + `implicit_concepts`, `hybrid` = true BM25 + dense fusion via Reciprocal Rank Fusion.
- Or cut to two honest modes: **Spoken** and **On-screen (CLIP)**. Recommended for now — ship two modes that work over four that don't.

### 2.5 "Hybrid" isn't hybrid
There is no lexical retrieval anywhere. Dense-only search is weak exactly where creators need it most: proper nouns, product names, acronyms, guest names — the "when did I mention Kubernetes" query. Add BM25 (`rank_bm25` is enough at this scale) and fuse with RRF. This is the single highest-value accuracy change after the chunking fix.

### 2.6 Enriched text is diluting the embeddings
`generate_enriched_text` prepends a template: `"Topic: X. Questions: Y. Concepts: Z. Spoken: <text>"`. The literal words *Topic*, *Questions*, *Concepts*, *Spoken*, plus the boilerplate question phrasing, appear in **every** chunk and consume real signal in a 384-dim MiniLM vector. Concepts are also duplicated (once raw, once inside the questions).

**Fix:** embed the raw spoken text and the metadata **separately**, then combine scores — or drop the template and prepend just the topic. Measure with the eval harness; this is exactly the kind of change that feels right and tests wrong.

### 2.7 Concept extraction is producing junk
Straight from the live index: `implicit_concepts` includes `"doesn"` (a broken contraction), `"making"`, `"lesson hopefully"` (a crossed sentence boundary), and `"proper english"`. These feed `section_topic`, the suggested queries, the concept pills, and the enriched text — so one weak heuristic degrades four surfaces.

Also: `MEDIA_FILLER` is a 100-word hand-curated blocklist containing terms like `problem`, `solution`, `approach`, `process`, `power`, `modern` — words that are the actual subject matter for a tech creator. The blocklist is overfitted to one test video and will actively suppress real topics.

**Fix:** strip contractions before tokenizing; require n-grams to sit within one sentence; replace the blocklist with corpus-level IDF (a term common across *your* library is uninformative — that's exactly what IDF encodes) plus a small POS filter for noun phrases.

### 2.8 Visual search shares a threshold with text search
CLIP cosine similarities occupy a completely different range from MiniLM's. The same `relevance_threshold` is applied to both. Calibrate independently.

### 2.9 One keyframe per chunk is too coarse for visual search
Chunks span 45+ seconds; a single frame at `start_sec` represents it. Sample 3 frames per chunk (start / mid / end), keep the max-similarity frame, and store its offset so "jump to moment" can land on the frame that actually matched.

### 2.10 YouTube visual search is fake
For YouTube videos, every chunk's "keyframe" is the **same** `hqdefault.jpg` video thumbnail. All 17 chunks of the databases video have identical visual embeddings. Visual search over YouTube content is therefore meaningless — it can only ever rank whole videos, never moments, and the UI's green "CLIP Visual Indexed" eye badge asserts otherwise on every card.

**Fix:** either pull real frames via `yt-dlp`, or mark YouTube chunks `visual_status: "video-level"` and exclude them from visual-scene ranking with an honest badge.

---

## 3. Usefulness

### 3.1 Suggested queries read like a template engine
`get_suggested_queries` walks chunks in index order and cycles six templates, yielding things like *"How do english lesson and weather compare?"* — grammatically broken and not what anyone would type. It's the first thing a new user sees.

**Fix:** rank concepts by corpus IDF, take the top 4 *distinct* ones, use one clean template (`"Where did I talk about {concept}?"`), and cache the result instead of recomputing per request.

### 3.2 The empty state is nearly unreachable
Consequence of 2.2. The most valuable thing this product can say is "you haven't covered this yet" — that's the Content Gap insight the wider CreatorBrain thesis rests on. Right now it can't say it. Gate on the calibrated reranker score and, when a query lands just below the cutoff, show the near-misses under a *"Nothing strong — closest matches:"* header rather than a bare void.

### 3.3 No progress feedback during ingest
`/api/upload_transcribe` is a single blocking POST. Whisper `base` on CPU runs roughly 1× realtime — a 60-minute podcast blocks the request for ~an hour with a spinner and no signal. The PRD targets 10–20 videos; this is a hard blocker for real use.

**Fix:** background job queue + `GET /api/jobs/{id}` polled by the existing `IndexingProgressModal`, with per-stage progress (download → transcribe → chunk → embed → keyframes). Whisper exposes segment callbacks, so real percentages are available.

### 3.4 Whisper `base` is the accuracy floor
Everything downstream inherits transcript errors. `base` mangles proper nouns and technical vocabulary — precisely the high-value search terms. Offer a model selector (`base` / `small` / `medium`) and default to `small`. Better: use `faster-whisper`, which is ~4× quicker at equal accuracy, making `small` cost less than `base` does today.

### 3.5 Two videos is not a validation
The PRD asks for 10–20. Nothing in the quality claims is testable at n=2. Build a fixed 15-video test library and commit its `queries.yaml` alongside.

### 3.6 Cheap wins with high perceived value
- **Filter by video / date** in the results header — trivially easy, immediately useful at 20+ videos.
- **Copy quote with citation** (`"text" — Title @ 12:34`) — one button; this is the actual repurposing workflow.
- **Keyboard**: `/` to focus search, `↑↓` to move through results, `Enter` to open. Removes the mouse from the loop.
- **Query history** in `localStorage`.
- **Notes on highlights** — the backend accepts a `note` field; `addHighlight(result.id, "")` in `App.tsx` always sends an empty string. The feature is built and unreachable from the UI.

---

## 4. Engineering hygiene

| Item | Detail |
|---|---|
| **No tests** | Zero test files. Start with the chunker, the ID generator, and the merge logic — the three places bugs are already living. |
| **`requirements.txt` is incomplete** | Missing `opencv-python`, `Pillow`, `torch`, `openai-whisper`, `rank_bm25`. A clean clone cannot reproduce the running environment. Pin versions. |
| **Runtime pip install** | `ensure_local_whisper_installed()` shells out to `pip install` mid-request. Unpredictable, slow, fails offline, can break a live server. Move to requirements. |
| **Hardcoded URLs** | `http://localhost:8000` appears in `api.ts`, `VideoPlayerModal.tsx`, and — worse — is **baked into persisted data** as `keyframe_url` in every chunk. Change the port and the whole index breaks. Store relative paths; resolve at render time via `VITE_API_URL`. |
| **Full reindex on every write** | `add_chunks` → `reindex()` re-embeds the *entire* corpus for each new video. O(n²) across a library build. Embed incrementally and `np.vstack`. |
| **No index/embedding lock** | Concurrent upload + search can read `dense_embeddings` mid-rebuild, or leave `len(embeddings) != len(chunks)`. Guard with a lock or build into a new array and swap atomically. |
| **Silent excepts** | `except: return []` in `fetchHighlights` / `fetchSuggestedQueries` hides real backend errors as empty UI. |
| **Dead code** | `src/services/mockData.ts` exports two empty arrays; `localMediaParser.ts` is unused. |
| **Duplicated stopword lists** | Maintained separately in `multimodal_engine.py` and `ResultCard.tsx`; they already disagree. |
| **`matched_concepts` duplicates `implicit_concepts`** | Identical values written to both keys on every chunk. Pick one. |
| **No `.env` / key handling** | `OPENAI_API_KEY` read from ambient env with no `.env.example` and no startup validation. |
| **Design drift from PRD §8** | The PRD mandates *hairline borders carry all elevation, no drop shadows anywhere*. The implementation uses `shadow-2xl`, `shadow-xl`, `backdrop-blur-2xl`, and `animate-pulse` throughout. Decide whether the PRD or the code is the source of truth, then update the loser. |

---

## 5. Sequenced plan

### Phase 1 — Make it correct (~1 day)
Nothing else is measurable until this lands.
1. Content-hash video IDs (1.3) + upload dedup (1.4).
2. Rewrite `segment_transcript_into_sentences` with tests (1.2).
3. Index versioning + forced re-chunk on stale data (1.1).
4. Fix the failed-ingest record (1.5), boot-time visual reindex (1.6), CORS (1.7).
5. Complete `requirements.txt`; drop the runtime pip install.

**Exit:** re-ingest both videos; confirm chunks carry `sentence_idx`, are 1–3 sentences long, and that merging no longer collapses a video into one result.

### Phase 2 — Make it measurable (~half day)
6. Build the 15-video test library.
7. Write `queries.yaml` (30 positive + 10 negative) and `run_eval.py`.
8. **Record the baseline.** Every number after this is a delta against it.

**Exit:** `python -m eval.run_eval` prints Recall@1/@3/@5, MRR, seek error, and false-positive rate on negatives.

### Phase 3 — Make it accurate (~1–2 days, eval-gated)
9. BM25 + RRF hybrid retrieval (2.5).
10. Calibrate the reranker threshold from the negative set (2.2), fix the empty state (3.2).
11. Replace the concept-extraction heuristic with IDF + noun phrases (2.7).
12. A/B the enriched-text template against raw text and keep the winner (2.6).
13. Cut to two honest search modes (2.4); recalibrate visual separately (2.8).
14. Multi-frame keyframes (2.9); resolve the YouTube visual-search honesty problem (2.10).

**Exit:** every change ships with its eval delta. Anything that doesn't beat baseline gets reverted, not rationalised.

### Phase 4 — Make it usable (~1–2 days)
15. Background job queue + real ingest progress (3.3).
16. `faster-whisper` with a model selector, defaulting to `small` (3.4).
17. Honest score display (2.3); better suggested queries (3.1).
18. Filters, copy-with-citation, keyboard nav, highlight notes (3.6).

### Phase 5 — Harden (ongoing)
19. Incremental embedding; lock around index writes.
20. Relative `keyframe_url`s + `VITE_API_URL`.
21. Delete dead code; consolidate the stopword lists.
22. Reconcile the design system with PRD §8.

---

## 6. If you only do three things

1. **Fix the chunking/index mismatch (1.1 + 1.2).** Search is currently returning merged blobs with wrong timestamps. Everything else is decoration on top of that.
2. **Build the eval harness (2.1).** Without it there is no way to tell whether any accuracy change helped, and no way to defend a quality claim to anyone.
3. **Add BM25 hybrid retrieval (2.5).** Largest single accuracy gain available, and it fixes the proper-noun failure mode that dense-only search is structurally bad at.

---

## 7. Open questions

- **Is visual/CLIP search actually core, or is it scope creep?** It's the most complex subsystem, it's fundamentally broken for YouTube content (2.10), and the PRD lists nothing like it in scope. Cutting it would meaningfully shrink the surface area to get right.
- **Local Whisper or the OpenAI API as the default path?** They currently produce different segment shapes and different accuracy, and both paths are maintained. Picking one halves the ingest code.
- **What's the target library size?** Brute-force cosine is fine to ~50k chunks (~200 hours). Beyond that this needs a real vector index, and the persistence layer (full JSON rewrite on every save) needs replacing too.
