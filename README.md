# CBRIN

**Local-first video search and clip generation.** Index long-form video into a searchable library, then cut short-form clips from it.

Automated clippers choose where to cut from transcript position and engagement heuristics. That is why they hand back a punchline with its setup missing, a clip that opens on *"so he told me the whole thing"*, or a cut that lands halfway through a word — and why, when a clip comes out wrong, there is a single opaque score and nothing to inspect.

CBRIN treats those as constraints rather than scoring problems. A solver refuses to emit a clip that excludes its own setup or opens on a reference the viewer never saw; boundaries are moved onto real word onsets; and ranking is a breakdown of individually named signals instead of one number. Where a constraint cannot be satisfied it produces fewer clips and says why. Everything except narrative analysis runs on your own machine, so source footage is never uploaded and nothing is metered per clip.

## Contents

- [Why this exists](#why-this-exists)
- [Overview](#overview)
- [How clip selection works](#how-clip-selection-works)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [API](#api)
- [Development](#development)
- [Repository conventions](#repository-conventions)

---

## Why this exists

### The problem

The four failures above are structural rather than incidental. Each one follows from deciding cut points by position and heuristic, and none of them is fixed by scoring the same candidates more accurately.

**Clips arrive without their setup.** A punchline is scored highly on its own merits and cut on its own boundaries, leaving the line that made it land somewhere on the cutting-room floor. Nothing in a position-and-heuristic approach represents the dependency between the two, so nothing can prevent the cut.

**Clips open on a reference to something the viewer never saw.** "So he told me the whole thing" is a broken opening line regardless of how strong the moment is. Detecting this requires knowing that a pronoun's antecedent falls outside the clip — a property most tools never compute.

**Cuts land mid-phrase.** Speech-recognition sentence boundaries are text-driven and quantised, often by as much as a second. A cut placed on one clips the first phoneme or opens on dead air.

**The ranking is unexplainable.** Scores are typically presented as a single number with an undisclosed derivation — Opus Clip's virality score, for instance, is documented as 0–99 with the generating algorithm withheld. When a clip ranks poorly there is nothing to inspect and nothing to correct.

Separately, the prevailing delivery model requires uploading source footage to a third-party service and metering output per clip. For unreleased material that is a disclosure decision, not just a workflow one.

### How this addresses it

Each failure is met with a mechanism, not a better heuristic. The guarantees behind these are detailed in [How clip selection works](#how-clip-selection-works):

| Problem | Mechanism |
| --- | --- |
| Setup severed from payoff | A dependency solver treats `requires_setup_from_idx` as a hard constraint. A candidate that cannot include its own setup within the duration bounds is discarded rather than emitted. |
| Dangling references | Referential dependencies are resolved across the transcript. Clips are expanded backward until every reference resolves; whatever cannot be resolved is reported per clip, not hidden. |
| Mid-phrase cuts | Boundaries are chosen at pauses where the duration budget allows, then relocated onto true word onsets with guard bands. |
| Opaque ranking | Ranking is a weighted sum of individually named signals, each surfaced with its own value. Where a signal cannot be measured it reports as unknown rather than defaulting to zero or to perfect. |
| Upload requirement | Every stage except narrative analysis runs locally. Footage is not transmitted, and there is no per-clip metering. |

The design principle throughout is that a guarantee is worth more than a heuristic that is usually right. Where a constraint cannot be satisfied, the system produces fewer clips and says why, rather than producing a plausible-looking one whose defect is invisible until playback.

### Scope

This is a working tool under active development, not a finished product. The pipeline is complete and covered by tests; the evidence that it selects *better* clips than a heuristic baseline is not yet established at scale, because that requires a substantially larger evaluation corpus than the one currently indexed. Calibration constants in `clip_scoring.py` carry the measurements they were derived from, along with the sample sizes behind them.

---

## Overview

Three layers operate over a single indexed library.

| Layer | Responsibility |
| --- | --- |
| **Vault** | Ingests YouTube URLs and local media. Transcribes with Whisper, splits into sentence-level chunks, extracts keyframes, and serves hybrid retrieval across BM25, dense embeddings, and CLIP visual similarity. Optionally returns a grounded one-paragraph answer above the result set. |
| **Engine** | Generates clips. Identifies narrative beats in a transcript, solves for boundaries that provably contain every beat a payoff depends on, ranks candidates against named signals, and renders vertical output with burned-in captions and a configurable brand kit. |
| **Studio** | Runs text tools over an indexed transcript — show notes, key moments, repurposing — governed by a reusable voice profile, with full run history. |

### Technology

**Backend** — Python 3.10+, FastAPI, faster-whisper (falling back to openai-whisper), sentence-transformers, PyTorch/CLIP, rank-bm25, scikit-learn, NumPy/SciPy. FFmpeg is vendored through `imageio-ffmpeg`; no system installation is required.

**Frontend** — TypeScript 5, React 18, Vite 5, Tailwind CSS 3.

---

## How clip selection works

Clip generation runs as five stages. Exactly one calls an LLM; the remainder are deterministic or embedding-based, so the majority of the pipeline executes offline.

| Stage | Operation | LLM |
| --- | --- | :---: |
| **A. Structure** | Sentence embeddings partitioned into topic segments by divisive clustering | — |
| **B. Beats** | Narrative beat extraction over topic-coherent windows, with cross-segment context | Yes |
| **C. Solve** | Narrative dependencies, then referential dependencies, then pause-aligned boundary selection | — |
| **D. Rank** | Weighted scoring across named signals, followed by MMR selection for diversity | — |
| **E. Snap** | Cut points relocated onto true word onsets with guard bands | — |

### Design guarantees

**A clip cannot separate a setup from its payoff.** `requires_setup_from_idx` is a hard constraint enforced by the solver in `narrative_engine.beats_to_candidates()`, not a suggestion the model may disregard. Where a dependency cannot be satisfied within the duration bounds, the candidate is discarded rather than emitted in a broken state.

**The model emits sentence indices, not timestamps.** Every index is validated against the real sentence list, so a hallucinated boundary degrades to a dropped beat instead of an incorrect cut.

**Referential dependencies are verified, not asserted.** A clip that would open on a pronoun whose antecedent it excludes is expanded backward until the reference resolves. Anything that cannot be resolved within the duration bounds is reported per clip rather than suppressed.

**Unmeasurable signals report as unknown.** Absent word timing, unusable pitch data, or a missing embedding model each degrade the affected term and renormalise the remainder. No signal silently scores as zero or as perfect.

### Ranking signals

Candidates are ranked by a weighted sum of inspectable, individually named signals: hook strength, self-containedness, emotional delta, quotability, boundary cleanliness, and — once sufficient feedback has been recorded — taste match. The interface exposes the full breakdown. No predicted-engagement percentage is produced anywhere in the system.

---

## Getting started

### Prerequisites

- Python 3.10 or later
- Node.js 18 or later
- A CUDA-capable GPU is optional and affects transcription speed only

### Installation

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt
npm install
cp .env.example .env
```

On macOS and Linux, substitute `.venv/bin/pip` for `.venv/Scripts/pip`.

### Running

On Windows, `start.bat` launches both servers:

```bash
start.bat
```

Otherwise, run each in its own terminal:

```bash
cd backend && ../.venv/bin/python main.py
```

```bash
npm run dev
```

The API listens on `http://localhost:8000` and the interface on `http://localhost:3000`.

> **First run** downloads Whisper and CLIP model weights — several hundred megabytes. Subsequent starts load from cache and require no network access.

---

## Configuration

All settings are read from `.env`. See `.env.example` for the annotated reference.

| Variable | Purpose | Default |
| --- | --- | --- |
| `VAULT_LLM_BASE_URL` | Primary LLM endpoint. Any OpenAI-wire-compatible provider. | SambaNova |
| `VAULT_LLM_API_KEY` | Primary LLM credential. | — |
| `VAULT_LLM_MODEL` | Primary model identifier. | `Meta-Llama-3.3-70B-Instruct` |
| `VAULT_TOOLS_LLM_*` | Separate provider for Studio tools. Falls back to `VAULT_LLM_*`. | unset |
| `OPENAI_API_KEY` | Enables hosted Whisper transcription instead of local. | unset |
| `VAULT_WHISPER_MODEL` | Local Whisper tier: `base`, `small`, or `medium`. | `small` |
| `VAULT_CORS_ORIGINS` | Permitted frontend origins. | Vite dev ports |
| `VITE_API_URL` | Backend base URL for the frontend. | `http://localhost:8000` |

### Behaviour without an LLM key

Ingestion, search, and playback are unaffected. Engine falls back to heuristic beat detection and labels the output as degraded, with the reason surfaced in the interface, rather than presenting partial analysis as complete.

---

## API

The backend exposes a JSON API on port 8000. Long-running work is dispatched to a serial job queue; ingestion, analysis, and rendering return a job identifier to be polled.

| Group | Base path | Covers |
| --- | --- | --- |
| System | `/api/health`, `/api/stats` | Liveness and index statistics |
| Library | `/api/library`, `/api/ingest`, `/api/upload_transcribe` | Ingestion, listing, deletion, media and keyframe delivery |
| Search | `/api/search`, `/api/answer` | Hybrid retrieval and grounded answers |
| Engine | `/api/engine/*` | Analysis, clip retrieval and adjustment, rendering, brand kit, feedback |
| Studio | `/api/studio/*` | Tool catalogue, execution, run history, voice profile |
| Jobs | `/api/jobs/{id}`, `/api/engine/jobs/{id}` | Progress polling for queued work |

---

## Development

### Tests

```bash
.venv/Scripts/python -m pytest backend/tests -q
```

366 tests, none requiring network access. An autouse fixture redirects every data path to a temporary directory, so the suite cannot write to a real library.

### Evaluation harness

`backend/eval/` calibrates the ranking signals against labelled examples and reports the distributions the scoring constants are derived from. Constants in `clip_scoring.py` carry the measurement that produced them; re-run the harness before changing them. See `backend/eval/README.md`.

### Project structure

```
backend/
  main.py                  API routes and job orchestration
  vector_store.py          Hybrid BM25 + dense + CLIP index
  transcript_service.py    Whisper transcription
  word_timing.py           Word-level timings and boundary snapping
  topic_segmenter.py       Divisive clustering over sentence embeddings
  narrative_engine.py      Beat extraction and the boundary solver
  reference_resolver.py    Referential dependency detection
  prosody.py               Pitch and energy contours
  clip_scoring.py          Ranking signals and diversity selection
  clip_renderer.py         Rendering, captions, brand kit
  studio_*.py              Studio tools
  eval/                    Calibration harness
  tests/                   Pytest suite

src/
  components/
    vault/ engine/ studio/ ui/
  hooks/ services/
```

---

## Repository conventions

- **`internal/`** holds working documents: strategy, product requirements, research notes, and session handoffs. It is git-ignored by design — retained locally, excluded from the repository. No code depends on it.
- **`.agents/`** and **`skills-lock.json`** are local agent tooling and are likewise ignored. They are not part of the product.
- **`backend/data/`** is the persisted library — chunks, embeddings, media, and caches — and is ignored.
- Code comments cite planning documents by name (`ENGINE-PLAN.md`, `IMPROVEMENT-PLAN.md`). Several no longer exist. Treat those citations as historical rationale, not as live file paths.
