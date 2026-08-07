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
- `npx vite build` → **could not run in this environment.** `@rollup/rollup-linux-x64-gnu` is missing because `node_modules` was installed on Windows. Not related to these changes; run the build on your machine to confirm.
- **Not visually verified in a browser.** Nobody has looked at the running app since the change.

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

1. **Rotate the Groq key.** Today.
2. **Run `npx vite build` locally** and open the app. The design change has not been seen rendered.
3. **Phase 0 — validate before building** (`STRATEGY.md` §5). ~2 weeks, near-zero code: post the boundary-solver before/after, 10 creator interviews, pre-sell $49 lifetime. Honour the kill criterion.
4. **Only if Phase 0 clears:** Phase 1 — delete the CUT list, build the real 15-video library, hit the measurement bars in Appendix A. That is what earns the right to make the boundary claim publicly.

Do not start Phase 2 (installer, licensing) before Phase 0 returns an answer.
