# Handoff — 2026-08-07

Session covered two things: a strategic review of the whole project, and the first pass of the design change that came out of it. This file is a session record, not a third strategy doc — the direction lives in `STRATEGY.md` and nowhere else.

## Read first

| File | What it is |
|---|---|
| `STRATEGY.md` | **Single source of direction.** Verdict, pivot, feature cuts, phased plan, pricing, §8 design spec, and an appendix salvaged from the deleted docs. |
| `prd.md` | Product and technical truth — user stories, requirements, known defects, roadmap. Unchanged this session. |

Nothing else at root. If a third planning doc appears, something has gone wrong.

---

## 1. Strategic review — what was concluded

**Verdict: the thesis is fine, the shape is wrong, and the shape is what blocks money.** Not a pivot of the idea — a pivot from a three-layer "content OS" to one paid desktop tool.

The five findings that drove it:

1. **One defensible asset.** The narrative boundary solver (`narrative_engine.py` + `clip_scoring.py`) — structurally cannot cut a setup from its punchline. Everything else in the repo is commodity or unverified.
2. **Zero validation.** 4 indexed videos, one of which is a rickroll. No user has ever touched this. None of the six success criteria in `prd.md` §9 has been measured.
3. **The architecture blocks charging.** No auth, no billing, JSON singleton state, Windows `.cmd` install, local torch/Whisper/CLIP.
4. **Local-first is the positioning, not a cost story.** Reframed from "runs at the cost floor" to *your footage never leaves your machine, no credits, no upload queue*. That turns every apparent liability into the wedge against $15–29/mo metered SaaS.
5. **The doc-to-code ratio was the clearest signal in the repo** — ~100KB of planning markdown against a 4-video library.

**Honest ceiling, stated so it isn't drifted past:** a $79 one-time desktop tool selling 500 copies is ~$40K. Good income and a strong portfolio artifact. Not a venture-scale company. The hosted version is a different risk profile and kills the privacy pitch.

**The gate that matters:** pre-sell $49 lifetime. Fewer than 10 buyers in 14 days → stop. That criterion is written down *now*, before there's emotional investment in the outcome.

---

## 2. Docs — consolidated

Deleted: `PITCH.md`, `AGENTIC-PIVOT-PLAN.md`, `IMPROVEMENT-PLAN.md`, `AGENTIC-SYSTEM-AUDIT.md`, `creator-tools-integration-spec.md`.

- The first four were committed → recoverable via `git show HEAD:PITCH.md`.
- **`AGENTIC-SYSTEM-AUDIT.md` was untracked and is gone permanently.** Its findings are condensed into `STRATEGY.md` Appendix C.
- Everything still load-bearing (measurement bars, guardrail register, open defects, architectural invariants) moved to `STRATEGY.md` Appendix A–D before deletion.
- **83 code comments across 48 files still cite the deleted filenames** (e.g. `IMPROVEMENT-PLAN.md 2.3`). Left alone deliberately — mass-editing comments is exactly the churn the strategy argues against. Treat them as historical rationale.

---

## 3. Design — what shipped

Direction and rationale: `STRATEGY.md` §8. The problem was never the palette, it was discipline. Counted before the change:

- accent orange `#ff7a17` used **110×** — an accent used 110 times is a second background colour
- **94** `rounded-full` capsules, across **5** different radii
- **30+** uppercase wide-tracking eyebrow labels in 18 files
- **5** semantic hues in one results list
- decorative icons duplicating adjacent text (`User` beside "CHANNEL", `Clock` beside a timestamp)

### Changed

| File | Change |
|---|---|
| `tailwind.config.js` | True black `#000000`, ink `#ededed`, no chromatic accent, `danger` only. **Every radius token collapses to 2px** so the five-radius drift cannot recur. Geist replaces Inter. |
| `src/index.css` | Redefined `.eyebrow-mono` (no longer uppercase/tracked) and `.highlight-match` (underline, not an orange pulse) — **fixes all 30+ instances centrally instead of editing call sites**. Added `.confidence-rule`. Tabular figures on mono. |
| `index.html` | Geist + Geist Mono, monochrome favicon, white selection. |
| `ui/Button.tsx`, `ui/Pill.tsx`, `ui/Panel.tsx` | White-on-black inversion for primary, 2px radius, `danger` variant added. `Pill` keeps its name for call-site continuity but is no longer pill-shaped. |
| `src/**/*.tsx` (scripted) | Palette rainbow → neutral steps; all radii → `rounded-sm`; inline uppercase/tracking removed; `text-accent-sunset` → `text-ink-body`. |
| `ResultCard.tsx` (by hand) | The worst offender. Five chrome elements above the content → one quiet meta line. Confidence encoded as the **length** of a monochrome rule, not a hue. Quote is now the largest, brightest thing in the card. Unused icon imports dropped. |

**`accent-sunset` still appears in ~22 files.** The token now resolves to white, so those call sites are coherent and compile — it was left named for continuity rather than touching 110 sites. Do not reintroduce a hue behind that name.

### Verified

- `npx tsc --noEmit` → clean
- `npx tailwindcss` → compiles, 44KB, zero `ff7a17` remaining, no pill radii in output
- `npx vite build` → **now passes** (1516 modules, ~2.5s, 31KB CSS / 345KB JS). The previous `@rollup/rollup-linux-x64-gnu` failure was specific to that session's environment; it builds fine on this Windows box.
- **Visually verified in a browser** against the live backend (436 chunks, 4 videos) — see §6.

### Deliberately not restyled

The agent workspace (`components/agent/`) and the four STUDIO tools slated for cutting in `STRATEGY.md` §4 — polishing code that's about to be deleted.

---

## 4. Gotchas for the next session

1. **Line endings.** The working tree already had large pre-existing whole-file churn before this session (`backend/agent_engine.py` alone shows 1,206 changed lines nobody touched today). A scripted pass briefly flipped `src/` CRLF→LF; every file has since been restored to match its `HEAD` endings, so this session's diff is ~39 files / ~500 lines. A `.gitattributes` would prevent recurrence but triggers a mass renormalization — deferred as a deliberate choice.
2. **The Groq key in `.env` is still plaintext in the working tree.** Flagged in two prior audits and again here. Rotate it at console.groq.com. This is the one item that should not wait.
3. **File deletion required an explicit permission grant** in this environment (`rm` returned "Operation not permitted" until approved).
4. **The LLM config is on free tiers and routinely out of quota** — a 25-minute transcript exceeds the TPM limit. Anything that needs live generation will fail until a paid key is in place.

---

## 5. Next actions, in order

1. **Rotate the Groq key.** Today. *(Still open — the only item here that has not moved.)*
2. ~~Run `npx vite build` locally and open the app.~~ **Done — see §6.**
3. **Phase 0 — validate before building** (`STRATEGY.md` §5). ~2 weeks, near-zero code: post the boundary-solver before/after, 10 creator interviews, pre-sell $49 lifetime. Honour the kill criterion.
4. **Only if Phase 0 clears:** Phase 1 — delete the CUT list, build the real 15-video library, hit the measurement bars in Appendix A. That is what earns the right to make the boundary claim publicly.

Do not start Phase 2 (installer, licensing) before Phase 0 returns an answer.

---

# Session 2 — 2026-08-07 (later)

Scope: finish and verify the §8 design pass. No new features, no scope growth.

## 6. The design change is now verified rendered

Build passes and the app was driven live against the backend (started from `backend/` — `main.py` uses `uvicorn.run("main:app")`, so it **must** be launched with `backend/` as cwd or it exits silently).

`ResultCard` renders as §8 specifies: one quiet meta line, confidence encoded as the *length* of a monochrome rule, the transcript quote as the largest and brightest element, `.highlight-match` as an underline.

## 7. One claim in §3 was wrong — the eyebrow fix did not work

§8 rule 3 was recorded as satisfied because `.eyebrow-mono` was redefined with `text-transform: none`, "fixing all 30+ instances centrally instead of editing call sites."

**It didn't.** The caps were *hardcoded into the JSX strings* (`>LIBRARY EMPTY<`, `>SEARCH RESULTS<`, …), not applied by CSS. Removing `text-transform` removed the tracking but left every label rendering in caps. The central fix was necessary but not sufficient, and nothing caught it because the change was never looked at in a browser.

Lesson worth keeping: a CSS-level fix can only reach presentation. Caps baked into content need a content-level pass.

### Fixed this session

| File(s) | Change |
|---|---|
| 6 components (`App`, `Header`, `IndexingProgressModal`, `LibraryModal`, `SearchBar`, `VideoPlayerModal`) | 21 hardcoded-caps JSX text nodes → sentence case. Replacements anchored on `>TEXT<` so identifiers and enum values were untouchable — diff was exactly 21 insertions / 21 deletions. |
| `App`, `HighlightsPanel`, `VideoPlayerModal` | 4 more caps strings the anchored pass correctly *couldn't* reach because they interpolate (`{n} MOMENTS FOUND`, `VIEW ALL ({n})`, `BOOKMARKED MOMENT{S}`, `JUMPED TO MOMENT //`). |
| `SearchBar.tsx` | `SEARCH_MODES` labels → `Spoken` / `On-screen (CLIP)`. Only `label` changed; `id` drives all logic. |
| `CbrinLogo.tsx` | **The last chromatic accent.** The mark still carried a `#ff7a17 → #ff3b00` gradient — violating §8 rule 1 in the single most prominent spot on screen. Now `#ededed → #6b6b6b`. |
| `Sidebar.tsx` | Section labels ("Views", "Library") were decorative mono + `tracking-wider` — rule 3 reserves mono for timestamps/scores/IDs. Now sans. Wordmark tracking normalised. |
| `App.tsx` | A channel name was force-`uppercase`, which also mangled real names ("Rick Astley" → "RICK ASTLEY"). Removed; count moved to mono, text to sans. |

### Audit after (in `src/`, excluding `components/agent/` per §8's scope note)

| Check | Count |
|---|---|
| `uppercase` class | 0 |
| `tracking-wide*` | 0 |
| `rounded-full` | 0 |
| distinct radii | 1 (`rounded-sm`) |
| semantic hue classes (emerald/amber/red/…) | 0 |
| `#ff7a17` | 0 (one mention survives in a code comment) |
| all-caps JSX text nodes | 0 |

`npx tsc --noEmit` clean; `npx vite build` passes.

`accent-sunset` still appears 58× and still resolves to white — left named for call-site continuity, as before. Do not reintroduce a hue behind it.

## 8. A CUT-list claim was falsified — CLIP moved to KEEP

Before executing the §4 cuts, the CLIP rationale was tested rather than taken on trust. **It was wrong.** `STRATEGY.md` §4 and Appendix C are corrected; the short version:

- The claim was "structurally broken for YouTube — every chunk shares one thumbnail."
- Measured: **320 of 436 chunks carry real per-moment keyframes.** The two YouTube videos do fall back to thumbnails, but the ingest downloads video up to 1080p and `yt-pWH1TF1ZfKA.mp4` sits in `data/media/` at exactly the path `vector_store.py:291` looks for.
- Actual cause: a **race** (embedding runs before yt-dlp finishes merging to the final filename) plus a **one-way state gate** (`reindex_visual_embeddings` never revisits a chunk that already has an embedding, so a bad first answer is permanent). Both fixable in a few lines.
- **Decision: CLIP stays.** If it's ever cut, the reason is installer weight, not brokenness.

The entry's second claim — that the UI badges every result as visually indexed — is **also false**. `ResultCard.tsx:188–201` already separates `ok` from `video-level` by badge tint and tooltip. Only a weak version survives: disclosure is hover-only, and `LibraryModal.tsx:588` labels a video "VISUAL" even when all its chunks are video-level.

**The process lesson is worth more than the finding.** This entry sat in two planning docs and nearly deleted a working subsystem; both of its claims were false and each cost one command to check. Worth recording that the first correction written *this session* was also wrong — the "UI ignores `visual_status`" claim came from a grep that searched for `visual_source`, a typo, returned nothing, and was reported as fact without opening the component. An empty search result is evidence about the query before it is evidence about the code. Nothing else in Appendix A has been verified — do that before acting on any of it.

## 9. Unwritten risk: how YouTube ingest gets packaged

Not currently in any doc. YouTube ingest itself is sound and should be kept — it's the zero-friction onboarding path and the only way to build a Phase 0 before/after artifact from content you can legally show in public.

The risk is **bundling yt-dlp inside a paid, signed desktop binary**: downloading YouTube content violates their ToS, and that exposure changes character once money changes hands. It's also a maintenance treadmill on a platform with no telemetry and no hotfix path (§7). Usual resolution is to not bundle it — local files are the first-class input, YouTube is an optional path through a tool the user installs themselves.

This is a **Phase 2 packaging decision, not a Phase 0 one.** It does not threaten the positioning: yt-dlp and Whisper both run locally, so "your footage never leaves your machine" still holds.

## 11. CLIP bugs fixed — every chunk now has a real per-moment keyframe

`backend/vector_store.py`:

- **`find_local_media()` (new).** Prefers the canonical `{video_id}{ext}` but falls back to `{video_id}.<anything>{ext}`, so legacy files like `yt-dQw4w9WgXcQ.mp4.part.mp4` resolve instead of being silently treated as "no local media". Cached per video, so a 400-chunk library does one lookup per video, not per chunk.
- **Upgrade path in `reindex_visual_embeddings()`.** Now re-attempts `video-level` chunks when local media exists. A `visual_upgrade_failed` pin stops it retrying forever when the file is present but a frame still can't be pulled — the same reasoning as the existing `failed` guard. A failed upgrade keeps the old vector rather than downgrading a working chunk to `failed`.
- **Ingest fallback.** `chunk_transcript` now falls back to `find_local_media()` when the caller passes no media path, so a fresh ingest is less likely to embed thumbnails in the first place.

**Result, measured on the live library:**

| | Before | After |
|---|---|---|
| `visual_status: ok` | 320 / 436 | **436 / 436** |
| `video-level` | 116 | **0** |
| Distinct MKBHD keyframes | 1 (all identical) | **108 of 109** |

Confirmed through the search API: MKBHD hits return `status=ok` with different keyframes per timestamp. `npx tsc --noEmit` clean, 277 backend tests pass.

Backup of the pre-fix index is in the session scratchpad (`chunks.json.bak`, `visual_embeddings.npy.bak`) if you want to compare.

## 12. Still open

1. **Rotate the Groq key.** Untouched, and still the one item that shouldn't wait.
2. **`components/agent/` was deliberately left unstyled** — it's on the §4 CUT list. It still contains caps labels and will look inconsistent if you open the Agent view. That's expected, not a regression.
3. **Nothing in Phase 0 has started.** The design work above is polish on a product with zero validation — it does not substitute for the pre-sale, and the kill criterion still stands.
4. **The rest of the §4 CUT list is not executed.** CLIP was removed from it (§8). The remainder — agent layer, 4 of 6 STUDIO tools, import/export/highlights, dual-provider LLM — is still pending a decision. Note that the "3 of 4 search modes" cut is already effectively done: the code is down to `spoken` + `visual_scenes`, and `visual_scenes` now stays with CLIP.
5. ~~Two CLIP bugs are documented but unfixed.~~ **Both fixed and verified — see §11.**
