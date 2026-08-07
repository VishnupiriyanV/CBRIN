# CBRIN — Strategic Assessment & Monetization Plan

**Date:** 2026-08-07
**Verdict up front:** The thesis is fine. The *shape* is wrong, and the shape is what's blocking money.
**Recommendation:** Don't pivot the idea. Pivot the product from a three-layer "content OS" to **one paid desktop tool**, cut ~60% of the surface area, and validate with 10 paying users before writing more code.

> Note on this document: this repo already has ~100KB of planning markdown (PITCH, prd, IMPROVEMENT-PLAN, AGENTIC-PIVOT-PLAN, AGENTIC-SYSTEM-AUDIT, creator-tools-integration-spec) against a library of **4 indexed videos, one of which is a rickroll**. That ratio is the single clearest signal in the repo. This doc is deliberately short and decision-dense. It should be the last strategy doc written before there is a paying user.

---

## 1. Honest read of where the project actually is

### What's genuinely good

| Asset | Why it matters |
|---|---|
| **Narrative boundary solver** (`narrative_engine.py` + `clip_scoring.py`) | Structurally cannot cut a setup from its punchline. This is a real, testable engineering claim that the market leader demonstrably fails at. **This is the only defensible thing in the repo.** |
| **Sentence-level index with derived (not model-invented) timestamps** | The honesty mechanism — model returns indices, backend derives times — is a mechanism, not a prompt. Rare and correct. |
| **Engineering discipline** | 204 tests, three eval harnesses, calibration by measurement (`hook_eval.py`), an audit that found 15 real defects including its own. Most solo projects at this stage have none of this. |
| **Local-first stack** | Currently framed as a cost story. It's actually the *positioning* story. See §3. |

### What's actually broken (not opinion — from your own docs)

- **Zero validation.** 4 videos. No user has ever touched this. PRD §9 sets six non-negotiable success criteria (Recall@5 ≥ 0.80, FP ≤ 0.10, seek error ≤ 5s) and **not one has been measured against a real 15-video library.**
- **The hook signal missed its own bar** — AUC 0.668 against a stated 0.70, on 50 labels over a 4-video corpus.
- **The flagship agent feature was never verified live.** `generate_content_pack` orchestrates 5 sequential LLM calls and has never completed a real run because the free-tier key is rate-limited.
- **The LLM layer is on free tiers and constantly out of quota.** A 25-minute keynote exceeds the TPM limit. That is not a product; that's a demo that fails on the second file.
- **Scope grew ~3× while the core loop stayed broken** — your own PRD §14 says this, and then AGENTIC-PIVOT-PLAN added an agent layer, streaming, content packs, and deep research *on top*. The pattern the risk register warned about happened again, in writing, one day later.
- **The architecture makes charging impossible.** No auth, no billing, JSON singleton state, Windows `.cmd` install, local torch/Whisper/CLIP. You cannot put a credit card form on this.

### What is not defensible

**STUDIO's six tools.** Repurposer, show notes, titles, replies, captions, moments are prompt wrappers. The guardrails around them are good engineering, but no one has ever bought a product because its caption generator refuses to truncate. ChatGPT does 80% of this for free and Castmagic does the packaged version. This layer is ~40% of the surface area and ~5% of the differentiation.

**The agent/copilot layer.** Newest, most seductive, least verified, most expensive per run, and it makes the product *less* trustworthy — a ReAct loop on Llama-3.3 with a fallback tool-call parser is exactly the "confident-looking UI over a fragile prompt" that PITCH.md §3 says CBRIN exists to reject.

---

## 2. Is this worth working on? Straight answer.

**As currently scoped — a three-layer content OS competing with Opus Clip, Castmagic, Repurpose.io, vidIQ and Descript simultaneously — no.** One person cannot out-build four funded companies in four categories at once, and the current build is spread thin enough that no single layer is best-in-class.

**As one narrow desktop product built on the boundary solver — yes, conditionally.** The condition is that it stops being a $0 side project with a $0 validation budget and gets 10 real creators in front of it within 30 days.

**Set expectations honestly on ceiling.** A one-time-license desktop tool at $79 that sells 500 copies is ~$40K. That's meaningful income and a great portfolio artifact. It is not a venture-scale company. If you want the company, that's a hosted multi-tenant rewrite with GPU bills and a completely different risk profile (§6). Pick one deliberately; don't drift into the desktop version while telling yourself it's the company.

---

## 3. The pivot: stop fighting the architecture

Right now local-first is treated as a *constraint to eventually escape* — "runs at the cost floor, optional API upgrade path." Flip it. Local-first is the wedge.

Every incumbent meters you:

- Opus Clip: free 60 credits/mo, $15/mo Starter (150 credits), $29/mo Pro
- Castmagic, Repurpose.io, Descript: subscription + upload + processing queue

Every one of them requires you to upload your raw footage to their servers and wait, then charges per minute processed. A streamer with 200 hours of VOD backlog cannot afford any of them, and a creator under NDA or with unreleased footage can't use them at all.

**Reposition to:**

> **Your footage never leaves your machine. No credits. No upload. No queue. And it never cuts your punchline in half.**

That single sentence turns every current liability (local torch, GPU requirement, no cloud, no account) into the product, and turns the boundary solver into the proof. It also makes the "honest by design" register a *retention* asset rather than a headline nobody buys — because nobody has ever purchased software on the promise that it doesn't fabricate timestamps.

**Target user, narrowed to one:** a **streamer or video podcaster with 50+ hours of unmined archive** who has already tried Opus Clip and got mid-sentence clips back. Not "creators." Not five segments. One.

---

## 4. Feature decisions

### CUT — delete, don't defer

| Cut | Why |
|---|---|
| **Agent / Copilot layer** (`agent_engine.py`, `agent_tools.py`, `AgentWorkspace.tsx`, content pack, deep research, SSE streaming) | Unverified, quota-bound, highest maintenance, zero pricing power. This is the hardest cut because it's the newest work. Make it anyway. |
| **STUDIO — 4 of 6 tools** (repurposer, titles, replies, captions) | Commoditized. Keep show_notes + moments only because they ride the transcript you already have. |
| **CLIP visual search** | Your own PRD §10 already flags it: most complex subsystem, structurally broken for YouTube (identical embeddings per video), never in v0.1 scope. Cutting it removes torch-CLIP, `visual_embeddings.npy`, keyframe extraction, and 37MB of state. |
| **3 of 4 search modes** | HYBRID/QUESTIONS/TOPICS are byte-identical. Shipping decorative UI in a product whose pitch is "honest by design" is the worst possible inconsistency. |
| **Import/export/highlights** | Nobody asked. Pure surface area. |
| **Dual-provider LLM juggling** (`VAULT_LLM` + `VAULT_TOOLS_LLM`) | Complexity that exists only to dodge free-tier limits. Solved by a paid key or BYO key. |

Estimated reduction: **~55–60% of code surface**, ~70% of the "things that must stay correct."

### KEEP — this is the product

1. Local ingest (`faster-whisper`, GPU→CPU fallback) — the moat against upload-and-wait
2. Sentence-level chunking with real cues
3. **Narrative boundary solver + 5 inspectable signals** — the whole differentiator
4. Clip render with burned captions, one vertical preset (`clip_renderer.py`, NVENC already detected)
5. Text search over your own archive with accurate seek — the retention hook that makes people keep the app installed after the first batch of clips

### ADD — the minimum to charge money

| Add | Effort |
|---|---|
| **License key activation** (Polar / Lemon Squeezy / Gumroad) — offline-tolerant check | 2–3 days |
| **A real installer** — Tauri or Electron shell wrapping the FastAPI backend + bundled Python; signed. The current `install.cmd` + `start.bat` is a dealbreaker for a paying non-technical user. | 1–2 weeks (the biggest single ADD, and the most underestimated) |
| **BYO API key UX** — a settings screen, not a `.env` file. Keeps your marginal cost at literally zero. | 2 days |
| **The proof artifact** — a side-by-side page: same 40-min source, Opus Clip's cut vs yours, showing the decapitated punchline. This is the marketing asset, and you can only build it once the eval numbers are real. | 3 days |
| **Batch mode** — point at a folder of 50 VODs, walk away. This is the thing metered SaaS structurally cannot offer, and it's the reason a streamer buys. | 1 week |

---

## 5. The plan

### Phase 0 — Validate before building (2 weeks, ~0 code)

Do this first. If it fails, everything below is moot and you've saved three months.

1. Post the boundary-solver claim with a real before/after clip in r/podcasting, r/Twitch, r/NewTubers, and 2 creator Discords. Not a launch — a "does this bother anyone else?" post.
2. 10 interviews with streamers/podcasters holding 50+ hour archives. One question that matters: *"what do you currently pay, and what made you stop using Opus Clip?"*
3. **Pre-sell.** $49 lifetime, first 50 buyers, ships in 8 weeks, refund if it slips.

**Kill criterion, decided now, in writing: fewer than 10 pre-orders in 14 days → stop.** Not "iterate the messaging." Stop, and keep this as the portfolio piece it already is — which is a genuinely good outcome, not a failure.

### Phase 1 — Earn the claim (2 weeks)

You cannot sell the boundary claim until it's measured. This is PRD §9, finally executed.

- Build the real 15-video library (rights-clear, actual long-form podcast/stream content — no rickroll)
- Run `run_eval.py` / `clip_eval.py` / `hook_eval.py` and record baseline
- Hit Recall@5 ≥ 0.80, FP ≤ 0.10, seek error ≤ 5s, hook AUC ≥ 0.70
- Expand `hook_labels.yaml` from 50 → 200 labels across the new corpus
- Delete everything in the CUT list

**Exit:** you can put a number on the box, and the codebase is half the size.

### Phase 2 — Make it installable (3 weeks)

Tauri/Electron shell, bundled runtime, signed installer, settings UI for the API key, license activation, batch folder mode, first-run experience that survives a stranger.

**Exit:** you can send a `.exe` to someone who has never used a terminal and they get a clip out.

### Phase 3 — Ship to the pre-order list (1 week)

Ship to the 10–50 pre-orders. Fix what breaks. Collect three testimonials with real numbers ("mined 80 hours of VOD in a weekend").

### Phase 4 — Decide the ceiling (ongoing)

With real users and real usage data, pick deliberately:

- **Stay desktop.** $79 one-time + $29/yr optional updates. Low risk, capped upside, near-zero opex.
- **Go hosted.** Only if users are actively asking for team/cloud. This is a rewrite — auth, multi-tenancy, queues, object storage, GPU workers, and it kills the "your footage never leaves your machine" pitch that got you the first 50 customers. Don't do it on a hunch.

---

## 6. Pricing

| Tier | Price | Notes |
|---|---|---|
| Free | 3 clips watermarked | Proves the boundary claim before payment; costs you nothing because compute is the user's |
| **Pro (recommended anchor)** | **$79 one-time** | BYO key or local-only. Unlimited, unmetered — the entire pitch against $29/mo credit meters |
| Founding | $49 lifetime, first 50 | Phase 0 pre-sale |
| Updates | $29/yr, optional | Keeps some recurring without breaking the one-time promise |

The math a buyer does: Opus Clip Pro is $348/yr. You're $79 once. You don't need to be better at everything — you need to be better at one thing they can name (not cutting the punchline) and dramatically cheaper at scale.

---

## 7. Risks, stated plainly

1. **Desktop distribution is genuinely hard.** Code signing, Windows SmartScreen, no telemetry, no hotfix, support burden from 500 different GPU configs. This is the real cost of the local-first pivot and it's usually underestimated by 2×.
2. **You may be the only person who cares about clean cuts.** Creators may just re-trim in CapCut and never think about it. Phase 0 exists entirely to test this. Take the answer seriously.
3. **The build-instead-of-ship pattern is the biggest risk in the project.** Documented in PRD §14, then repeated the next day with the agent layer. The countermeasure is the Phase 0 kill criterion — a decision made before you're emotionally invested in the outcome.
4. **Local-first caps your market** to users with a decent GPU and a Windows/Mac machine they'll install software on. That's a real ceiling, accepted knowingly in exchange for the positioning.
5. **Immediate housekeeping:** the plaintext Groq key in `.env` has now been flagged in two separate audit docs and is still there. Rotate it today.

---

## 8. Design direction — minimal black

**Design read:** dense single-operator tool for a technical-ish creator, near-black, restrained. Leaning Linear / Vercel / Raycast, not Awwwards. Dials: `VARIANCE 4 / MOTION 2 / DENSITY 6`. This is a workbench, not a marketing page.

### What's actually wrong now

The current theme is "xAI-inspired near-black + sunset orange." The palette isn't the problem — the *discipline* is. Counted in `src/`:

| Tell | Count | Why it reads as AI slop |
|---|---|---|
| `accent-sunset` (#ff7a17) usages | **110** | An accent used 110 times isn't an accent, it's a second background colour. It's on channel badges, garnish icons, section labels, hover states, headings and borders simultaneously. |
| `rounded-full` | **94** | Pill soup. Every badge, tag and button is a capsule. |
| Distinct corner radii | **5** (`full`, `2xl`, `xl`, `lg`, `md`) | Shape-consistency lock broken. `Panel.tsx` even documents the drift in a comment instead of fixing it. |
| `eyebrow-mono` uppercase wide-tracking labels | **30+ across 18 files** | `CHANNEL:`, `SECTION:`, `ANSWERS QUESTION:`, `VISUAL`, `THUMBNAIL`. The single most recognisable LLM-design tell. |
| Semantic hues in one view | **5** (emerald / amber / red / slate / orange) | Status rainbow. |
| Decorative icons | many | A `User` icon inside a badge that already reads `CHANNEL:`. A `Clock` next to a timestamp. Icons carrying zero information. |

The worst instance is `ResultCard`: five chrome elements (channel pill, timestamp pill, confidence dot, match reason, index badge) stack above the content, so the transcript quote — the only thing the user came for — is the fifth-loudest element on the card.

### The new system

**Rule: the transcript text is the loudest thing on screen. Everything else is chrome and behaves like it.**

```
canvas          #000000   true black, not #0a0a0a
canvas-raised   #0b0b0b   cards
canvas-sunken   #060606   wells, inputs, code
line            #1a1a1a   default hairline
line-strong     #2b2b2b   hover / focus / active
ink             #ededed   primary text (never pure #fff on true black — it vibrates)
ink-body        #9e9e9e
ink-mute        #6b6b6b
ink-faint       #444444
signal          #ffffff   the ONLY accent: pure white, inversion for primary action
danger          #ff5c4d   destructive and error only — nothing else is coloured
```

Hard rules, each one a direct answer to a row in the table above:

1. **No chromatic accent.** Emphasis is white-on-black inversion, weight, and space. Orange is deleted, not re-tinted.
2. **One radius: `2px`.** Sharp reads precise; pills read templated. Status dots become 5px squares — deliberately, not as a compromise.
3. **Mono is functional, never decorative.** `Geist Mono` is reserved for timestamps, durations, scores and IDs. Nothing else. No uppercase wide-tracking eyebrows anywhere — the `eyebrow-mono` class gets redefined rather than removed, so all 30 instances fix at once.
4. **Two status colours, not five.** Confidence is a monochrome rule whose *length* encodes strength. Colour is reserved for danger.
5. **An icon must carry information the text doesn't.** Delete `User` next to "CHANNEL", `Clock` next to a timestamp, `Layers` next to "SECTION". Keep `Play`, `Copy`, `Bookmark` — those are affordances.
6. **Borders carry all elevation.** No shadows, no glows, no blur, no gradient. Already mostly true; keep it.
7. **Motion at 2/10.** 120ms opacity and border-colour transitions. No pulse, no shimmer, no spin except a real loading state.
8. **Type:** `Geist` replaces `Inter` (`Inter + slate + near-black` is the canonical LLM default, and Geist Mono is already loaded so the pairing is free). Display `tracking-tight`, body `leading-relaxed`, `max-w-[68ch]` on any prose.

### Implementation order

`tailwind.config.js` → `index.css` (redefining `.eyebrow-mono` and `.highlight-match` fixes most instances centrally) → `index.html` (font + favicon + selection colour) → `ui/` primitives (`Button`, `Pill`, `Panel`, `OutputBlock`) → then hand-fix `ResultCard`, `Header`, `ClipCard`, `ScoreBreakdown`, which own the structural badge-soup problem that a token change can't reach.

**Scope note:** do this only for the surfaces that survive §4. Restyling the agent workspace and the four cut STUDIO tools is work you're about to delete.

---

## 9. The one-paragraph version

You've built a genuinely well-engineered system around one real differentiator — clip boundaries that can't decapitate a punchline — and then buried it under two other half-products, six commodity prompt wrappers, and an unverified agent layer, none of which anyone has ever paid for or even used. Keep the boundary solver and the local archive search, delete the rest, stop treating local-first as a limitation and sell it as the reason to buy, and go get 10 people to pay $49 before you write another line. If 10 people won't, that's the most valuable thing you'll learn all year — and this stays what it already is, which is a strong piece of engineering work.

---

# Appendix — salvaged from the deleted docs

`PITCH.md`, `AGENTIC-PIVOT-PLAN.md`, `IMPROVEMENT-PLAN.md`, `AGENTIC-SYSTEM-AUDIT.md` and `creator-tools-integration-spec.md` were deleted on 2026-08-07. The four committed ones are recoverable from git history (`git show HEAD:PITCH.md`); `AGENTIC-SYSTEM-AUDIT.md` was untracked and is gone for good, so its findings are condensed into §C below. 83 code comments across 48 files still cite these filenames as rationale — left alone deliberately, since mass-editing comments is exactly the churn this document argues against. Everything below is the part that was still load-bearing.

## A. Measurement bars — the numbers that gate the marketing claim

Nothing may be claimed publicly until it is measured here. Harnesses already exist at `backend/eval/`.

| Metric | Bar | Status |
|---|---|---|
| Recall@5, differently-phrased queries | ≥ 0.80 | Never run against a real library |
| False-positive rate, 10 negative queries | ≤ 0.10 | Never run — the empty state must actually fire |
| Mean seek error | ≤ 5s | Never run |
| Hook-signal AUC (`hook_eval.py`) | ≥ 0.70 | **0.668** — missed, on 50 labels over a 4-video corpus |
| Boundary violations (setup severed from payoff) | 0% | Regression-guarded in the suite; the core claim |
| Test library size | 15 videos, rights-clear | **4**, one of which is a rickroll |

Calibration note worth keeping: the hook signal blends semantic similarity to 6 hook archetypes with 6 lexical cues at `sem=0.20 / lex=0.80`, chosen by sweeping AUC *and* median class separation together, not by eye. Expanding `hook_labels.yaml` from 50 → 200 labels is the cheapest path to clearing 0.70.

## B. Guardrail register — mechanisms, not prompt instructions

These survive the cut because they apply to the clip and show-notes paths that remain. Each is enforced in code and asserted in tests.

| Promise | Enforcement |
|---|---|
| Never fabricates a timestamp | The model returns sentence *indices*; the backend derives every displayed time from parsed cue data. A model-emitted time is not a code path that exists. |
| Never cuts between a setup and its payoff | Candidates are built by a dependency-chain solver over sentence boundaries, not a heuristic. |
| Never invents a confidence number | No "82% viral score." Five named, inspectable signals; ranking scores are shown as buckets, never as percentages. |
| Never truncates over a platform limit | Over-limit triggers one targeted regenerate. Slicing text is not a code path that exists. |
| Never connects to a social account | No platform SDK is a dependency anywhere in the tree. Copy-to-clipboard is the only path out. |
| Hard-gates instead of degrading | With no LLM key, generation refuses rather than emitting a rule-based imitation. |

## C. Known defects still open

- **Two search modes are decorative.** `HYBRID`/`QUESTIONS`/`TOPICS` are byte-identical in code. Shipping fake UI controls in a product whose pitch is honesty is the worst available inconsistency — fixed by §4's cut to a single mode.
- **CLIP visual search is structurally broken for YouTube** — every chunk of a video shares one thumbnail, so all chunks have identical visual embeddings, while the UI badges each result as visually indexed. Cut.
- **`generate_content_pack` has never completed a live run.** Cut.
- **`tool_runs.py` / `usage.py` do whole-file JSON read-modify-write with no locking.** Fine single-user; a data-loss bug the moment anything runs concurrently.
- **The Groq key in `.env` is plaintext in the working tree.** Flagged in two prior audits, still present. Rotate it.

## D. Architectural invariants — carried forward unchanged

No posting or account connection to any platform. No quota-heavy platform-API analytics. No scraping of contact info, follower data, or competitor content. Check whether a platform already ships a feature natively before building a competing one. Users supply their own inputs.
