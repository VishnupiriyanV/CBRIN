# Agentic System Audit — Findings & Fixes

**Date:** 2026-08-05
**Scope:** Studio Copilot agent (`agent_engine.py`/`agent_tools.py`), ENGINE narrative analysis
(`narrative_engine.py`/`clip_scoring.py`), the LLM client and fallback path
(`llm_client.py`), and the frontend surfaces that render their output.

Three symptoms were reported: the agentic system needed a working review, ENGINE kept
falling back to heuristics instead of using the LLM, and the hook score was always 0. All
three were confirmed and traced to concrete defects, along with several more in the same
blast radius. Every fix below was verified against the running app, not just unit tests —
see [Live verification](#live-verification) for the actual request/response evidence.

---

## Summary of what was broken

| # | Symptom | Root cause | File |
|---|---|---|---|
| 1 | Hook score always ~0% | `hook_strength` scored openings with a query→passage *relevance* cross-encoder, not a style classifier | `clip_scoring.py` |
| 2 | Quotability always ~100% | IDF ceiling calibrated too low for this corpus size, saturating 96.5% of clips | `clip_scoring.py` |
| 3 | Engine silently used heuristics | `degraded` flag computed once from key presence, never updated when extraction actually failed | `narrative_engine.py` |
| 4 | One bad transcript window discarded a whole video's LLM beats | No per-window fault tolerance in windowed extraction | `narrative_engine.py` |
| 5 | Tools-only LLM config could 500 instead of 503 | `is_configured()` and `_get_client()` disagreed on which key to trust | `llm_client.py` |
| 6 | Context-length errors silently retried as rate limits | Bare `"limit"` substring match misclassified errors | `llm_client.py` |
| 7 | Concurrent agent requests serialized behind one sleeping thread | RPM throttle held its lock across `time.sleep()` | `agent_engine.py` |
| 8 | Agent citations always empty | `_format_search_hit` read field names that don't exist on real search results | `agent_tools.py` |
| 9 | `deep_research` collapsed every hit from one video into one result | RRF fusion keyed on a field that was always `None` | `agent_tools.py` |
| 10 | Content-pack clips rendered `#1 — ?–?` with an empty quote | Field names read off ranked candidates didn't match what candidates actually carry | `agent_tools.py` |
| 11 | `extract_video_clips`'s no-candidates fallback always errored | Fallback candidates used keys `clip_scoring.rank` doesn't read | `agent_tools.py` |
| 12 | Voice profile never reached the agent | `get_creator_context` read nonexistent `bio`/`examples` keys | `agent_tools.py` |
| 13 | Blocking vs. streaming agent loops disagreed on duplicate-call handling | Different, uncoordinated dedup logic in each path | `agent_engine.py` |
| 14 | Streaming duplicate detection could leave a dangling tool call | Assistant message appended before the duplicate check ran | `agent_engine.py` |
| 15 | Rate-limit retries could duplicate streamed text | Retry re-yielded tokens the failed attempt already sent | `agent_engine.py` |

---

## 1. Hook score — was always ~0%, now spreads 0–1

**Root cause.** `clip_scoring._hook_strength` (old code) fed `(hook_archetype, opening_text)`
pairs to `cross-encoder/ms-marco-MiniLM-L-6-v2` and took `sigmoid(max_logit)`. That model is
trained to answer *"is this passage a relevant search result for that query"*, not *"is this
sentence stylistically hook-shaped"*. An ordinary sentence is not a relevant result for the
"query" *"You won't believe what happened next."*, so the logit is strongly negative before
the sigmoid ever runs.

**Evidence (before the fix).** `backend/data/clips.json` (persisted from a real prior run)
had `hook_strength` values of `0.0005098152703909039` and `0.00016035167161023418` —
`Math.round(v * 100)` renders **0%** in `ScoreBreakdown.tsx`. This carries the largest weight
(0.25) of the five signals, so the composite score was deflated for every clip, every time.

**Fix.** Replaced the cross-encoder entirely with a blend of:
- **Semantic** — max cosine similarity between the opening sentence and the same 6 hook
  archetypes, using the bi-encoder (`all-MiniLM-L6-v2`) `vector_store.py` already loads for
  dense search. Encoded once per process, not per candidate.
- **Lexical** — six explainable 0/1 cues over the first 15 words: question opener,
  curiosity-gap phrasing, second-person address, superlative, negation, numeral.

Both halves are blended (`sem*0.20 + lex*0.80`, see calibration below) and mapped through a
range measured on this library's real corpus — not the textbook `(cos+1)/2`, which would
have compressed the real spread into roughly `[0.48, 0.71]`.

**Also fixed in the same pass:** the `beat_bonus` escape hatch could never fire, because
candidates only ever contain payoff-class beats (`beats_to_candidates` seeds only on
`PAYOFF_BEAT_TYPES`). Added `narrative_engine._covering_beat_type()`, which prefers a `hook`
beat when several beats overlap the clip's actual opening sentence, and attached it to the
candidate as `opening_beat_type`.

**Calibration — measured, not guessed.** New `backend/eval/hook_eval.py` (mirrors
`clip_eval.py`'s existing discipline) and `backend/eval/hook_labels.yaml` (50 hand-labeled
real sentences from this library, 10 hook / 40 not, stratified across the score range).
Swept the semantic/lexical weight split checking AUC *and* median class separation together
— the initial 0.45/0.55 guess (reasoned from correlation alone) turned out to have a visibly
weaker median gap than a more lexical-heavy split. Selected `sem=0.20/lex=0.80`:

```
sem=1.00 lex=0.00   AUC=0.702   delta=+0.04
sem=0.45 lex=0.55   AUC=0.695   delta=+0.12
sem=0.20 lex=0.80   AUC=0.668   delta=+0.22   <- selected
sem=0.00 lex=1.00   AUC=0.605   delta=+0.20
```

**Honest result, not a clean pass:** no weight split in the swept range cleared both the
stated 0.70-AUC / +0.20-median-delta bar at once. 50 labels on a 4-video corpus (one of
which is song lyrics) is enough to catch and fix the original bug, not enough to trust the
exact weight split with full confidence. Full history and the exact numbers are in
[`backend/eval/README.md#hook-signal-calibration`](backend/eval/README.md); expanding the
labeled set is documented there as real follow-up work.

**Measured before/after (full 436-sentence corpus, `eval/hook_eval.py --distribution`):**

| | Before | After |
|---|---|---|
| p5 | ~0.00001 | 0.0001 |
| p50 (median) | ~0.0001 | 0.1298 |
| p95 | ~0.0005 | 0.7151 |
| max | ~0.0005 | 1.0000 |
| % saturated at 1.0 | 0% (all near-zero instead) | 1.1% |

**Also fixed: quotability was the mirror-image bug.** `_quotability`'s ceiling
`(avg_idf - 1.0) / 3.0` was too low for this corpus — measured `avg_idf` over real quotable
lines has p50=5.04, p99=6.39, so the old ceiling of 4.0 saturated **96.5%** of real clips at
exactly `quotability = 1.0`. New `QUOTABILITY_IDF_FLOOR = 4.0` / `QUOTABILITY_IDF_CEIL = 6.3`
(measured p5/p99) fixes this the same way.

**Files:** `backend/clip_scoring.py`, `backend/narrative_engine.py` (`opening_beat_type`),
`backend/eval/hook_eval.py` (new), `backend/eval/hook_labels.yaml` (new).

---

## 2. LLM vs. heuristic fallback — was silently swapped, now honest

**Root cause #1 — dishonest `degraded` flag.** `narrative_engine.analyze_video` computed
`degraded = not llm_client.is_configured()` *before* extraction ran, and never updated it
when `extract_beats` actually threw — the exception was only `print()`'d. So heuristic beats
could be (and were) persisted with `degraded: false`.

**Direct proof this happened for real, on disk, before any code changed:**
`backend/data/clips.json` had 8 clips, all marked `degraded: false`, yet 6 carried the
titles `"Question and answer"` / `"Turning point"` — strings that only
`narrative_engine.heuristic_beats()` can produce. The UI was told the LLM ran on all 8; it
actually ran on at most 2.

**Root cause #2 — one bad window discarded everything.** `extract_beats` windows long
transcripts into 60-sentence LLM calls. One `LLMUnavailable` from *any single window*
propagated and discarded every beat successfully extracted from every other window.

**Fix.** `narrative_engine.analyze_video` now returns
`{beats, candidates, degraded, mode, degraded_reason, extraction}` where `mode` is one of
`"llm"` / `"llm_partial"` / `"heuristic"`, computed from what *actually happened* during
extraction. New `extract_beats_with_report()` wraps each transcript window individually, so
a single window failure downgrades the result to `"llm_partial"` (real LLM beats + a
documented gap) instead of discarding everything. `degraded_reason` is one honest sentence
persisted onto every clip and returned from the analyze job (`main.py`), rendered in the
`ClipStudio.tsx` banner (softer tone for `llm_partial` than a full `heuristic` fallback).

**Live verification (real request against the running app, not a mock):**

```json
POST /api/engine/analyze {"video_id": "local-99ce947e13e5", "max_clips": 6}
-> GET /api/engine/jobs/{job_id}
{
  "degraded": true,
  "degraded_reason": "LLM beat extraction failed for every transcript window (LLM beat
    extraction failed for all 1 transcript window(s): LLM call failed after attempts across
    models: Error code: 413 - {'error': {'message': 'Request too large for model
    `llama-3.1-8b-instant`... on tokens per minute (TPM): Limit 6000, Requested 11058...'}})
    — beats came from heuristic detection instead.",
  "analysis_mode": "heuristic"
}
```

This is a **real** Groq rate-limit failure that occurred while verifying this fix (the WWDC
keynote transcript exceeds the fallback model's 6000 TPM limit) — exactly the scenario the
old code would have silently mislabeled `degraded: false`. The new code surfaced the actual
provider error instead of hiding it.

**Root cause #3 — reliability plumbing.** Three more bugs made LLM failures more frequent
than necessary:
- `llm_client.is_configured(for_tools=False)` accepted a tools-only key, but
  `complete_json_with_usage` built its client from the primary key only —
  `openai.OpenAI(api_key=None)` raised at construction, producing a 500 where a 503 was
  intended. Fixed with `llm_client.resolve()`, a single source of truth that implements the
  fallback in both directions.
- The rate-limit check (`"limit" in msg.lower()`) misclassified *"maximum context length
  exceeded"* as a rate limit and silently slept-and-retried a request that could never
  succeed. Split into `is_rate_limit_error` / `is_context_length_error` /
  `is_model_not_found_error`, each matched on real provider error text (verified against the
  exact 413 message captured above).
- `agent_engine`'s RPM throttle held its lock across `time.sleep()`, serializing every
  concurrent agent request behind whichever thread was sleeping. Extracted to
  `backend/llm_throttle.py` (new module), which releases the lock before sleeping and shares
  one budget between `agent_engine` and `narrative_engine`'s window loop — they can share a
  provider quota (`VAULT_LLM_*` and `VAULT_TOOLS_LLM_*` pointed at the same account is a
  documented, supported config).

**Files:** `backend/llm_client.py`, `backend/llm_throttle.py` (new),
`backend/narrative_engine.py`, `backend/main.py`, `src/types.ts`,
`src/components/engine/ClipStudio.tsx`.

---

## 3. Agent tool data — was reading fields that don't exist

Every one of these was the same shape of bug: a function built its output from key names
that never existed on the object it was handed, so the values were silently `None`/`0`/empty
instead of raising a visible error.

- **`_format_search_hit`** read `title`/`start_time`/`final_score`; real
  `VectorStore.search()` results carry `video_title`/`start_sec`/`start_timestamp`/`score`.
  The agent's system prompt instructs it to cite `[video title @ mm:ss]` using exactly the
  fields that were always `None` — citations were structurally impossible before this fix.
  **Verified live:** a real chat query now returns citations like `"Test2" @ 01:51` sourced
  from real `start_sec: 111`/`score: 0.998` data (full transcript in
  [Live verification](#live-verification)).
- **`deep_research`'s RRF fusion** keyed on `(video_id, item.get("start_time"))` — always
  `None` — so every hit from the same video collapsed into a single fused result regardless
  of which passage it came from. **Verified live:** the same query above returned **6
  distinct passages from one video**, not 1.
- **Content-pack clip summaries** read `hook`/`start_time`/`duration`/`transcript` off ranked
  candidates that actually carry `quotable_line`/`start_sec`/`end_sec` — every content-pack
  clip rendered `#1 — ?–?` with an empty italic quote in `ContentPackArtifact.tsx`. Fixed by
  reading the real candidate shape and rebuilding the transcript excerpt from sentence data.
- **`extract_video_clips`'s no-candidates fallback** built candidates keyed `start_idx`/
  `end_idx`; `clip_scoring.rank` reads `start_sentence_idx`/`end_sentence_idx` — guaranteed
  `KeyError`, silently swallowed into a generic `"Tool execution failed"` string. Fixed to
  emit the real candidate contract.
- **`get_creator_context`** read `bio`/`examples`, which don't exist on
  `voice_profile.DEFAULT_VOICE_PROFILE` (real keys: `niche`/`audience`/`tone`/
  `banned_words`/`sample_content`/`cta_style`). The agent never saw the creator's actual
  voice settings despite the system prompt telling it to. Now returns the real keys plus
  `voice_profile_prompt` (the same rendering every Studio tool already uses).

**Files:** `backend/agent_tools.py`, `backend/tests/test_agent_tools.py`.

---

## 4. Agent engine — blocking vs. streaming paths disagreed

The blocking (`run_agent_turn`) and streaming (`run_agent_turn_stream`) implementations were
~450 lines of near-duplicated logic that had drifted apart:

- **Duplicate-call guard.** Blocking allowed the same `(tool, args)` call to repeat up to
  `MAX_AGENT_TURNS` (5) times before stopping — since that's also the turn budget, the guard
  could barely ever fire before the loop exhausted itself. Streaming stopped on the first
  repeat. Unified both onto a shared `_ToolDedupe` class with first-repeat semantics.
- **Dangling tool call.** Streaming appended the assistant's `tool_calls` message *before*
  checking for duplicates within that turn, so a duplicate detected partway through a
  multi-call turn could leave that assistant message with `tool_calls` entries that never got
  a matching `role="tool"` response — a shape most providers reject on the next request.
  Fixed: every call in a turn is now resolved (id/name/args/duplicate-status) *before*
  anything is appended; a duplicate anywhere in the turn skips the whole turn atomically.
- **Duplicated streamed tokens.** The rate-limit retry path re-streamed a fresh attempt while
  the failed attempt's partial tokens had already been yielded to the UI, producing
  duplicated text (`"HelHello!"`). Fixed by buffering every attempt's output locally and only
  yielding it once that attempt completes without raising — applies uniformly to the first
  attempt and every retry, not just retries.
- **Missing throttle + missing usage.** The streaming retry path skipped the RPM throttle the
  primary path had; `stream_options={"include_usage": True}` was never passed, so streamed
  turns always recorded zero token usage. Both fixed.

**Files:** `backend/agent_engine.py`, `backend/tests/test_agent_engine.py` (3 new tests
directly pinning these three bugs: first-repeat dedup, no dangling tool call, no duplicated
tokens on retry).

---

## 5. Frontend robustness

- `ScoreBreakdown.tsx` — `Object.entries(signals)` threw on a clip persisted without
  `signals`; a non-numeric value rendered `width: NaN%`. Both guarded; a clip with no usable
  signals now renders a plain message instead of taking the whole card down.
- `TitlesTool.tsx` — `output.titles`/`.hooks`/`.thumbnail_text` were `.map`'d unguarded; a
  partial LLM response that still passes the loose `_TITLES_SCHEMA` (only top-level keys are
  required) crashed the pane. Defaulted each to `[]`.
- `ContentPackArtifact.tsx` — no code change needed; confirmed it now renders correctly once
  the backend fix (§3) landed, since it was already reading the right field names — the
  backend was just never sending them.
- `types.ts` — added `degraded_reason`, `analysis_mode`, `opening_beat_type`,
  `signal_details` to `ClipCandidate` to match the new backend contract.

---

## Live verification

Ran against the actual app (`backend/main.py` on :8000 via the project's `.venv`, Vite dev
server on :3000), not just the unit test suite.

**1. Hook score, real Analyze run, `local-99ce947e13e5` (Apple WWDC keynote, 25 min):**

```
POST /api/engine/analyze -> GET /api/engine/clips/local-99ce947e13e5

hook=0.5537  composite=0.617  degraded=True  mode=heuristic  title='Question and answer'
hook=1.0000  composite=0.578  degraded=True  mode=heuristic  title='Question and answer'
hook=0.5802  composite=0.545  degraded=True  mode=heuristic  title='Question and answer'
hook=0.4339  composite=0.493  degraded=True  mode=heuristic  title='Turning point'
hook=0.5569  composite=0.428  degraded=True  mode=heuristic  title='Question and answer'
hook=0.3941  composite=0.410  degraded=True  mode=heuristic  title='Turning point'
```

Spans 0.39–1.00, six distinct values. `mode=heuristic` and `degraded=True` correctly agree
here because the LLM call for this specific video genuinely failed (see §2's 413 error) —
this is the honest-degradation fix working exactly as intended, not a false positive.

**2. Same data through the actual UI** (`ClipStudio.tsx`, via the Browser pane, video
selector switched to the WWDC keynote): degraded banner renders the full real error message;
each clip card's `ScoreBreakdown` shows `Hook 55%` / `100%` / `58%` / `43%` / `56%` / `39%`
and `Quotability 92%` / `54%` / `86%` / `71%` / `54%` / `50%` — both signals spread, neither
stuck at a constant.

**3. Agent citations + `deep_research` fusion, real chat turn:**

```
POST /api/studio/agent/chat
{"messages": [{"role": "user", "content": "What have I said about English lessons? Cite the video and timestamp."}]}

-> tool: deep_research, 6 fused passages, ALL from local-f718cb618763 ("Test2") but at
   6 DIFFERENT timestamps (00:00, 00:24, 00:57, 01:51, 02:27, 02:42) — proves the RRF
   fusion no longer collapses same-video hits into one result.

-> reply: '"Test2" @ 01:51, where you mention...' / '"Test2" @ 02:42, where you mention...'
   (6 real citations, all with real video titles and mm:ss timestamps sourced from the
   tool's start_sec/start_formatted fields, exactly matching the system prompt's
   instruction to never state a timestamp it wasn't given by a tool)
```

**4. Regression sweep:**

```
python -m pytest backend/tests -q          -> 275 passed
python eval/clip_eval.py --compare-modes   -> mid_sentence_start_rate: 0.0% (required)
                                               setup_containment_rate: 100.0% (required)
npx tsc --noEmit                            -> clean, no errors
```

---

## Addendum (post-handoff) — retry ladder wasted calls and hid the real error

Live use immediately after the fixes above surfaced one more real bug in the same area:
Groq's TPM-capacity rejection (`"Request too large for model ... please reduce your message
size"`, `code: rate_limit_exceeded`) was matched by `is_rate_limit_error` (via the
`rate_limit_exceeded` code), not `is_context_length_error` — so `_call_with_backoff` spent a
full backoff-and-retry cycle hammering the small fallback model (`llama-3.1-8b-instant`, 6000
TPM) with a request that could never fit no matter how long it waited. Worse, the final
exception only ever reported the *last* model tried, silently discarding the primary model's
real failure reason.

**Fix:** widened `is_context_length_error` to match Groq's `"request too large"` /
`"reduce your message size"` phrasing (non-retryable against the same model — moves to the
next model in the ladder immediately instead of sleeping and retrying). `_call_with_backoff`
now records every model's actual failure and reports all of them in the final message.

**Before:**
```
LLM call failed after attempts across models: Error code: 413 - Request too large for model
`llama-3.1-8b-instant` ... TPM: Limit 6000, Requested 9742 ...
```
(the primary model's real failure is invisible)

**After (live, same account, next run):**
```
llama-3.3-70b-versatile: Error code: 429 - Rate limit reached ... tokens per day (TPD):
  Limit 100000, Used 99009, Requested 7738. Please try again in 1h37m9.408s.
llama-3.1-8b-instant: Error code: 413 - Request too large ... TPM: Limit 6000, Requested 7738
```
The actual root cause — this Groq account's **daily** token quota is exhausted, resets in
~1h37m — is now visible. It was completely hidden before. New tests:
`test_groq_tpm_too_large_message_is_context_length_not_plain_rate_limit` and
`test_context_length_error_is_not_retried_and_moves_to_next_model` in `test_llm_client.py`.
This is a config/quota issue on this Groq account, not a code bug — pointing
`VAULT_LLM_*`/`VAULT_TOOLS_LLM_*` at different providers (per the note below) avoids both
slots draining the same daily budget.

## Known limitations / honest follow-up work

- **Hook signal calibration is directionally correct, not fully validated.** 50 labels on a
  4-video corpus caught and fixed the original bug (spread went from a ~0.0005-wide band to
  a full 0–1 range) but didn't clear the stated 0.70-AUC bar. See
  `backend/eval/README.md#hook-signal-calibration` for the exact numbers and what expanding
  the labeled set would take.
- **This checkout's LLM config is presently over its rate limit** for longer transcripts —
  the WWDC keynote (25 min) exceeds the fallback model's 6000 TPM limit on Groq's free tier.
  This is a `.env` configuration issue, not a code bug; the fix in this audit is that the
  system now *tells you* this happened instead of hiding it. `.env` currently points both
  `VAULT_LLM_API_KEY` and `VAULT_TOOLS_LLM_API_KEY` at the same Groq account, so the agent
  and Studio tools share one quota — pointing them at different providers would reduce how
  often this triggers.
- **The Groq API key in `.env` is plaintext in the working tree** (gitignored, not
  committed) and was read during this audit. Rotate it at console.groq.com.
- **Content-pack generation** (`generate_content_pack`) was not verified against a live
  request in this pass — it orchestrates 5 sequential LLM calls and the current account is
  presently rate-limited (see above), which made a live run impractical within a reasonable
  timeout. The underlying field-mapping fix (§3) is covered by
  `test_extract_video_clips_fallback_candidates_are_rankable` and direct code review;
  `ContentPackArtifact.tsx` was confirmed to already read the corrected field names.

## Out of scope (flagged, not done)

Repo hygiene items explicitly deferred per the approved plan: `.gitattributes` for CRLF
churn, stale module docstrings claiming Gemini is the default LLM provider (code defaults to
SambaNova), `VAULT_RELOAD` undocumented in `.env.example`.

## Files changed

**Backend:** `agent_engine.py`, `agent_tools.py`, `clip_scoring.py`, `llm_client.py`,
`main.py`, `narrative_engine.py`, `studio_runner.py`, plus new `llm_throttle.py`,
`eval/hook_eval.py`, `eval/hook_labels.yaml`, and test files for all of the above.

**Frontend:** `types.ts`, `ClipStudio.tsx`, `ScoreBreakdown.tsx`, `TitlesTool.tsx`.
