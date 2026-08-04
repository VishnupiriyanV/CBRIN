# CBRIN → Agent-First Content Studio — Implementation Plan

> Status: **Approved**, ready to execute. Target: shippable in **1 day**.
> LLM stays on Groq `llama-3.3-70b-versatile`. No provider switch, no auto-posting, no auth/billing.

## Context

CBRIN ("CreatorBrain") is a local-first content OS with three layers on one FastAPI backend:
**Vault** (hybrid semantic search), **ENGINE** (narrative clip discovery), **STUDIO** (six text
repurposing tools). A "Studio Copilot" ReAct agent was started (`backend/agent_engine.py`,
`backend/agent_tools.py`, `src/components/studio/StudioCopilotPanel.tsx`) but it is bolted on:
a cramped `h-[680px]` side panel treated as "one more tool," a single blocking (non-streaming)
request, several real bugs, and no artifacts.

This plan makes the **agent the center stage**, adds two genuinely useful flagship capabilities —
**Autonomous Content Pack** and **Deep Research with cited timestamps** — fixes the tool bugs,
streams reasoning live, migrates Whisper to `faster-whisper` (~4× speedup) with fallback, and
optimizes search accuracy.

---

## Confirmed decisions
- **Flagship features:** BOTH Autonomous Content Pack *and* Deep Research with citations.
- **Whisper:** migrate to `faster-whisper` (CUDA fp16 → int8 CPU → `openai-whisper` fallback).
- **UI:** dedicated **agent-first view** as the default landing surface; the 3-pill nav demotes to secondary.
- **Model:** keep Groq Llama-3.3; harden the fallback parser + turn-exhaustion handling.

---

## Bugs found during exploration (fix these)

1. **`get_creator_context` silently returns `{}`** — `agent_tools.py:324` calls non-existent
   `platform_rules.load_rules()`; the `hasattr` guard swallows it. **Fix:** call `platform_rules.load()`
   (confirmed real fn at `platform_rules.py:77`).
2. **Fabricated timestamps** — `agent_tools.py:296-303` invents 15s/line cues for `moments`/`show_notes`.
   Violates the PITCH "honest by design" promise. **Fix:** use real chunk cues (`store.chunks` carry
   `sentence_idx`/`start_sec`/`end_sec`) via the tools' `source="library"` path; if absent, pass no cues.
3. **`run_studio_tool` passes the WRONG input keys for 4 of 6 tools** (newly found). It shotguns
   `transcript_text`/`source_text`/`input_text` (`agent_tools.py:305-309`), but the tools read
   different keys (see contract table below): `repurposer`/`captions` → `text`; `titles` → `topic`;
   `replies` → `comments` (a **list**); only `show_notes`/`moments` read `transcript_text`. So repurposer,
   titles, replies, captions currently receive empty input. **Fix:** per-tool input mapping.
4. **Turn exhaustion loses content** — `agent_engine.py:189-193` returns generic `"Execution finished."`
   if all `MAX_AGENT_TURNS` used tools. **Fix:** final no-tools completion (`tool_choice="none"`).
5. **Fallback path uses synthetic user/assistant text** instead of proper `role:"tool"` messages
   (`agent_engine.py:117-126`), and can re-trigger the same `tool_use_failed` every turn. **Fix:** append
   a real tool-role message; guard against loops.
6. **No streaming** despite "Agent Active"/"reasoning loop" copy — endpoint is fully buffered.

### STUDIO tool input contract (from `backend/studio_prompts.py`)
| tool_id | reads keys | notes |
|---|---|---|
| `repurposer` | `text`, `emphasize?` | plain source text |
| `show_notes` | `source="library"`+`sentences[]` **or** `transcript_text` | library path = real timestamps |
| `titles` | `topic`, `niche?`, `audience_level?`, `past_titles[]?` | topic string |
| `replies` | `comments[]` (list of strings), `tone?`, `length?` | **list**, not text |
| `captions` | `text`, `cta?`, `platforms[]?` | platforms: `tiktok/instagram/youtube_short/youtube_long/x/linkedin` |
| `moments` | `source="library"`+`sentences[]` **or** `transcript_text` | **requires timestamps** (422 otherwise) |

`sentences[]` shape (see `main.py:_sentences_for_video`, `:747`):
`{sentence_idx, text, start_sec, end_sec}` — filter `store.chunks` by `video_id` where `sentence_idx` is not None, sorted.

---

## Workstream A — Backend agentic core

**Files:** `backend/agent_tools.py`, `backend/agent_engine.py`, `backend/main.py`.

### A1. Streaming (SSE)
- Add `run_agent_turn_stream(messages, store, video_id)` **generator** in `agent_engine.py` (keep the
  buffered `run_agent_turn` for back-compat/tests). Same ReAct loop but `stream=True` on
  `client.chat.completions.create`. Accumulate `delta.content` (yield `token` events) and
  `delta.tool_calls` fragments (index-keyed: `id`/`name`/`arguments` arrive piecemeal — concatenate by
  `tc.index`). Between turns execute tools and yield `tool_start` `{tool,args}` then `tool_result`
  `{summary,data}`. End with `usage` then `done` `{reply}`. On error yield `error` `{message}`.
- Add `POST /api/studio/agent/chat/stream` in `main.py` returning
  `StreamingResponse(gen, media_type="text/event-stream")`, each event serialized as
  `data: {json}\n\n`. Record usage from the final event. Keep `POST /api/studio/agent/chat` as fallback.
- Groq tool-call streaming caveat: when the model streams a tool call, `finish_reason == "tool_calls"`;
  assemble the full arguments string before `json.loads`. Also keep the existing `tool_use_failed`
  fallback parser wired into the streaming path.

### A2. Fix tool bugs (`agent_tools.py`)
- `get_creator_context`: `platform_rules.load()`.
- Remove the fabricated-timestamp block; route `show_notes`/`moments` through a real-cue path.
- New helper `_studio_inputs_for(tool_id, input_text, platform, video_id, store)` implementing the
  contract table (split `replies` input into a list on newlines; normalize `platform` aliases
  `twitter→x`, `youtube→youtube_long`).
- `search_vault`: also return `start_sec`/`end_sec`/`start_formatted` (needed for citations). Keep the
  relaxed-threshold retry.

### A3. Harden ReAct loop (`agent_engine.py`)
- Turn exhaustion → final `tool_choice="none"` completion; return its text.
- Fallback parse → append `role:"tool"` result (synthesize a `tool_call_id`); track handled failures to
  avoid infinite re-trigger.
- Bump `MAX_AGENT_TURNS` to **8**.
- Update `SYSTEM_PROMPT`: require inline citations `[title @ mm:ss]` when answering from vault content;
  prefer `generate_content_pack` for "turn X into content" goals; prefer `deep_research` for questions
  spanning the library.

### A4. Flagship tool — `generate_content_pack(video_id, goal, platforms)` (deterministic composite)
Add to `TOOL_SCHEMAS` + `execute_tool`. Because Llama-3.3 tool-calling is unreliable across long chains,
this ONE tool orchestrates server-side:
1. Resolve `video_id` (first library video if empty). Pull `sentences` from `store.chunks` (real cues).
2. Extract clips: reuse the existing `extract_video_clips` logic (`narrative_engine.analyze_video` +
   `clip_scoring.rank`) → top clips with real timestamps.
3. Run STUDIO tools via `studio_runner.run_tool` with correctly-mapped inputs:
   `repurposer` (text = joined transcript, capped), `titles` (topic = video title/goal),
   `show_notes` (`source="library"`, sentences), `captions` (text = summary/hook, platforms).
4. Assemble `ContentPack`: `{video_id, video_title, goal, clips[], repurposed{}, titles[], show_notes{},
   captions{}, sources[]}`. Wrap each sub-tool in try/except → per-section `error` so a partial pack still
   returns.
- **Concurrency note:** `tool_runs.py`/`usage.py` do whole-file JSON read-modify-write with **no locking**,
  and Groq free tier rate-limits. Run the sub-tools **sequentially** (correctness > a few seconds), OR add a
  `threading.Lock` around `tool_runs._save_all`/`usage._save_all` if parallelizing. Default: sequential.
- Stream per-stage progress via `tool_start`/`step` events (e.g. "Extracting clips", "Drafting LinkedIn +
  X", "Writing show notes").

### A5. Flagship capability — `deep_research(query, top_k)` (multi-query expansion)
Add to `TOOL_SCHEMAS` + `execute_tool`:
- Generate 2–3 paraphrases of `query` via `llm_client.complete_json` (schema: `{"queries":[...]}`).
- Run `store.search` for the original + each paraphrase; fuse by Reciprocal Rank Fusion keyed on
  `(video_id, start_time)` (self-contained RRF, k=60; `vector_store._reciprocal_rank_fusion` at `:678`
  is internal to a single ranked list so reimplement the fusion over result lists here).
- Return deduped, RRF-ranked passages with `video_id`/`title`/`start_sec`/`end_sec`/`text` so the model can
  cite them.

---

## Workstream B — Agent-first frontend

**Files:** `src/App.tsx`, `src/components/Header.tsx`, **new** `src/components/agent/AgentWorkspace.tsx`,
`src/services/api.ts`, `src/types.ts`, retire `src/components/studio/StudioCopilotPanel.tsx`,
dead-import cleanup in `StudioView.tsx`/`ToolRail.tsx`.

### B1. New default view
- Add `'agent'` to `activeView` (`App.tsx:18`) and `AppView` (`Header.tsx:7`); make it the **default**.
  Search/Engine/Studio stay reachable via the (demoted) pill nav.
- **New** `AgentWorkspace.tsx` — centered, full-height, **responsive** hero (replace fixed `h-[680px]`):
  centered conversation column, right-hand **live tool timeline** (streaming `tool_start`/`step`/
  `tool_result` cards), and an **Artifacts panel** (Content Packs + cited research). Reuse `ui/`
  primitives (`Button`, `Panel`, `Pill`, `OutputBlock`, `CopyButton`) + `canvas`/`ink`/`accent-sunset`
  tokens. Move the copilot logic here; drop the hardcoded "Open in Repurposer" button and the static
  duplicated welcome text.

### B2. Streaming client (`api.ts`)
- Add `studioAgentChatStream(payload, videoId, onEvent)` using `fetch` + `response.body.getReader()` +
  `TextDecoder`, parsing `data: {json}\n\n` frames and dispatching typed events
  (`token`/`tool_start`/`tool_result`/`step`/`usage`/`done`/`error`). Keep `studioAgentChat` (`:528`)
  as fallback. Render tokens as they arrive; render tool cards live; render `UsageBadge` from `usage`.

### B3. Artifacts & citations (`types.ts` + workspace)
- Add types: `ContentPack`, `AgentStreamEvent`, `Citation`.
- Render Content Pack as tabbed, copy-able blocks (clips w/ timestamps, posts per platform, titles, show
  notes) + **Download pack** (JSON, reuse the anchor-download pattern in `api.ts`).
- Parse `[title @ mm:ss]` in research answers → clickable chips opening the existing `VideoPlayerModal`
  at the timestamp.

---

## Workstream C — Whisper speed (faster-whisper + fallback)

**Files:** `backend/requirements.txt`, `backend/transcript_service.py`, `backend/word_timing.py`.

- Add `faster-whisper` (+ `ctranslate2`; comment the cuDNN requirement).
- Loader tries `faster-whisper` on CUDA first (`WhisperModel(model, device="cuda", compute_type="float16")`),
  falls back to `int8` CPU, then to the current `openai-whisper` path if CT2/faster-whisper unavailable.
  Preserve the existing CUDA→CPU retry semantics (`transcript_service.py:57-77`, `:271-280`;
  `word_timing.py:81-90`).
- Map `faster-whisper` segment/word output to the current internal shape so chunking, keyframes, and
  caption sync are unchanged. Use its native `word_timestamps=True` for `word_timing.ensure_words`.
- Leave the hosted OpenAI `whisper-1` path (`transcript_service.py:220-228`) untouched when
  `OPENAI_API_KEY` is set.
- Log the selected engine + device at startup (`torch.cuda.is_available()`).

---

## Workstream D — Search accuracy

**Files:** `backend/scripts/repair_index.py` (run it), `backend/eval/run_eval.py` (run it),
`backend/vector_store.py` (thresholds only, if eval supports).

- **Repair the degraded index first:** the persisted index predates `sentence_idx` (`IMPROVEMENT-PLAN.md`).
  Confirm the startup `_repair_stale_chunks` pass (`main.py:49-119`) re-chunks, and/or run
  `backend/scripts/repair_index.py` to rebuild `data/chunks.json` + `data/embeddings.npy`.
- **Multi-query expansion** (Workstream A5) — the highest-leverage accuracy win for conversational queries,
  fused via RRF.
- **Threshold tuning:** re-run `run_eval.py` against `eval/queries.yaml`; only adjust
  `RERANK_RELEVANCE_THRESHOLD` (`vector_store.py:53`, currently 0.08) / RRF `k` / candidate-pool size
  (30→50) if the eval shows gains. Do not hand-tune blindly.

---

## Workstream E — Overall speed
- Streaming (A1/B2) removes the biggest perceived-latency wall (blank "reasoning loop" wait).
- `faster-whisper` (C) for real transcription throughput.
- GPU video encode (NVENC/AMF/QSV) already auto-detected in `clip_renderer.py:44-74` — verify it engages.

---

## Verification (end-to-end)
1. **Backend tests:** `cd backend && python -m pytest`. Add focused tests: `get_creator_context` returns
   real platform rules; no fabricated timestamps in `moments`; `run_studio_tool` maps keys correctly;
   `generate_content_pack` returns a well-formed pack; streaming generator emits `done`.
2. **GPU check:** log `torch.cuda.is_available()` + faster-whisper device at startup; transcribe a short
   clip and confirm the CUDA path + faster wall-clock.
3. **Search eval:** `python backend/eval/run_eval.py` before/after index repair + threshold changes;
   confirm no regression.
4. **App run + browser verification** (`.claude/launch.json` `vault-frontend` @3000; backend
   `python backend/main.py` @8000):
   - Agent-first view is the default landing surface.
   - Research prompt → tokens stream live, tool cards appear incrementally, citations are clickable chips
     opening the player at the right timestamp.
   - "Turn my last video into a week of content" → `generate_content_pack` runs, artifacts render, Download
     works.
   - Check console/preview logs for errors; resize to confirm responsiveness (no fixed-height overflow).
5. **Screenshot** the working agent-first view with a completed Content Pack.

---

## Out of scope
- No provider switch (staying on Groq Llama-3.3).
- No auto-posting/scheduling (violates PITCH "honest by design").
- Face-tracking reframing stays v2.
- No auth/billing/multi-tenant.

---

## Security note (not code, but flagged)
The working-tree `.env` (gitignored, not committed) contains a live Groq key in plaintext
(`VAULT_LLM_API_KEY="gsk_…"`). Consider rotating/scrubbing it.
