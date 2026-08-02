---
title: Vault — Semantic Search for Your Own Content
status: Draft
version: 0.1 (MVP)
owner: TBD
last-updated: 2026-08-03
---

# Product Requirements Document: Vault

> Vault is Layer 1 of the CreatorBrain concept — a standalone MVP that proves the core loop before any of the other layers (analytics, clipping, concept testing, localization) get built. This PRD scopes only that MVP: search your own content library in plain language.

## 1. Problem

Creators with a large back-catalog (podcast episodes, YouTube videos, newsletters) cannot search what they've already said. YouTube search only indexes titles/descriptions, not spoken content. The result: creators re-cover topics they've already addressed, can't find their own best material to repurpose, and lose the value of their own back-catalog.

There is currently no product that lets a creator type a plain-language question and get back the exact moment, across their whole library, where they said it.

## 2. Goal

Ship a working demo, in two days, that proves one thing: **semantic search beats keyword search on a creator's own content.** A query like "when did I talk about imposter syndrome" should return the right clip even if that exact phrase was never spoken.

This is a proof-of-concept, not the production Vault. Scope is deliberately narrow — see Non-Goals.

## 3. Target user

A single creator (or small team) with an existing library of long-form audio/video content — YouTube, podcast, or raw files — who wants to find and reuse things they've already said.

**Primary use case (MVP):** "I remember saying something like X. Where?"

## 4. Non-Goals (explicitly out of scope for this PRD)

- Multi-platform account linking (YouTube OAuth, podcast RSS auto-sync, TikTok, newsletter ingestion)
- Analytics/performance correlation (Lens), clip generation (Engine), concept testing (Lab), localization (Globe)
- Content Gap Detector, "what have I covered 3+ times" type derived insights
- Multi-user accounts, billing, auth
- Support for more than ~20 pieces of content or non-English transcription

These are real parts of the larger CreatorBrain vision but are not part of this MVP. Building them now is how a 2-day demo turns into a 2-month demo.

## 5. User stories

| # | Story | Priority |
|---|---|---|
| 1 | As a creator, I upload or point to 10–20 videos/audio files so Vault can index them. | P0 |
| 2 | As a creator, I type a plain-language query and get back the moments where I discussed that topic, even if I used different words. | P0 |
| 3 | As a creator, each result shows me the source file, a text snippet, and a timestamp. | P0 |
| 4 | As a creator, I can click a result and jump straight to that moment in the source video. | P1 |
| 5 | As a creator, if nothing matches well, I see a clear empty state instead of forced/irrelevant results. | P1 |

## 6. Functional requirements

### 6.1 Ingestion
- Accept a folder of local video/audio files, or a hardcoded list of YouTube URLs.
- No OAuth, no platform account linking.

### 6.2 Transcription
- Transcribe each file with word/segment-level timestamps preserved (Whisper or equivalent).

### 6.3 Chunking + embedding
- Group transcript segments into ~45-second chunks with slight overlap so ideas aren't cut mid-thought.
- Generate an embedding per chunk; store chunk text, source file, start/end timestamp, and vector together.

### 6.4 Search
- Accept a natural-language query, embed it with the same model, return the top 5 chunks by similarity.
- Each result includes: source name, timestamp, text snippet, similarity score (internal, not necessarily shown to user).

### 6.5 Results UI
- Search bar + result list.
- Each result is a card: snippet, source label, timestamp, "jump to moment" action.
- Empty state when no result clears a relevance threshold.

## 7. Non-functional requirements

- **Latency:** query-to-results under ~2 seconds for a 20-video library.
- **Cost:** entire pipeline (transcription + embeddings) for a 20-video demo library should run under $5.
- **Scale:** MVP is explicitly sized for tens of videos, not hundreds of hours. No ANN infra required — brute-force cosine similarity over a local vector store is sufficient at this scale.

## 8. Design system

Visual direction is adapted from the uploaded xAI-inspired design kit (`DESIGN-x_ai.md`) — near-black canvas, white outline pills, restrained type, no shadows. Applied to Vault's two screens as follows.

### Palette (as defined in the kit)

| Token | Value | Use in Vault |
|---|---|---|
| `canvas` | `#0a0a0a` | Page background |
| `canvas-card` | `#191919` | Result cards |
| `canvas-soft` | `#1a1c20` | Search input fill |
| `ink` | `#ffffff` | Primary text, headline |
| `body` | `#dadbdf` | Snippet text |
| `body-mid` / `mute` | `#7d8187` | Timestamps, source labels |
| `hairline` | `#212327` | All borders — no shadows anywhere |
| `accent-sunset` | `#ff7a17` | Sparingly: highlight the matched phrase inside a snippet |

### Typography

- Headline ("Search your library"): `display-lg` / `display-md`, Universal Sans (substitute: Inter, weight 400, `-1.8px` to `-1.2px` tracking).
- Section eyebrow ("YOUR LIBRARY", "RESULTS"): `caption-mono`, GeistMono, uppercase, positive tracking — signature move from the kit.
- Snippet body: `body-md`.
- Timestamp / source label: `body-sm` in `mute` color.
- No bold anywhere. Weight 400 throughout, per the kit's "Don't bold display headlines" rule.

### Components (mapped from the kit)

- **Search bar** → `text-input`: `canvas-soft` fill, hairline border, `rounded.sm` (8px), no focus glow — a border color shift only.
- **Result card** → `card-content`: `canvas-card` fill, hairline border, `rounded.sm`, no shadow.
- **"Jump to moment"** → `button-outline-sm`: pill shape, translucent white border, transparent fill.
- **Empty state** → `ex-empty-state-card`: `canvas-soft` fill, `rounded.sm`, generous padding (`spacing.3xl`).
- **Section eyebrow** → `eyebrow-mono` above both the search bar and the results list.

### Explicit constraints from the kit

- Dark canvas only — no light mode for this MVP.
- Every interactive element is a pill (`rounded.pill`, 9999px) except cards, which stay at `rounded.sm` (8px).
- Hairline borders carry all elevation. No drop shadows anywhere, including on the result cards or empty state.

## 9. Technical approach (tied to the build plan)

- **Transcription:** Whisper API, segment-level timestamps retained.
- **Embeddings:** `text-embedding-3-small` (or equivalent) for both chunks and queries.
- **Storage:** ChromaDB, local — no managed vector infra needed at MVP scale.
- **Backend:** FastAPI, single `/search` endpoint.
- **Frontend:** single-page app implementing the components in Section 8.

## 10. Success criteria

The MVP is "done" when:
1. A 10–20 video library is fully indexed.
2. At least 5 test queries return the correct source moment despite not matching keywords verbatim (the core "wow" proof).
3. A user unfamiliar with the project can search, read a result, and jump to the right timestamp without instruction.

This is a validation artifact, not a launch. Success is "does the core idea hold up," not adoption or retention metrics.

## 11. Timeline

| Day | Deliverable |
|---|---|
| Day 1 | Ingestion → transcription → chunking → embedding → local vector index working end-to-end on the test library. |
| Day 2 | Search endpoint + UI (styled per Section 8) + 5–10 validated demo queries. |

## 12. Open questions

- Whose content library is the test set — the creator's own, or a sample library with clear usage rights?
- Is "jump to moment" required for local files (needs an in-browser seekable player) or is YouTube-only (`&t=123s` deep link) acceptable for the demo?
- Does the demo need to survive a restart (persisted index) or is an in-memory index for a single session acceptable?

## 13. Risks

- **Chunking quality is the main technical risk.** Bad chunk boundaries (mid-sentence cuts) will produce mediocre results even with a fine embedding model — budget real time for tuning this, not just building the pipeline.
- **Small library, small proof.** A 20-video demo proves the concept but says nothing about performance at hundreds of hours — flag this explicitly if the demo is shown as evidence for the larger CreatorBrain thesis.
