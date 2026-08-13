# CBRIN

**Local-first video search and clip generation.** Index long-form video into a searchable library, then cut short-form clips from it — transcription, embedding, scoring, and rendering all run on your own machine. Source footage never leaves the device. The only optional network call is to an LLM provider for narrative analysis.

## Contents

- [Overview](#overview)
- [How clip selection works](#how-clip-selection-works)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [API](#api)
- [Development](#development)
- [Repository conventions](#repository-conventions)

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
