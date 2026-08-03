# ENGINE — Implementation Plan

**Layer 3: Narrative-Aware Clip Generation**

Status: not started · Target branch: `feat/engine` · Working dir: `D:\hackathon\Project-stones`

---

## 0. What this document is

The design brief for ENGINE established *what* to build and *why*. This document is the
build plan: ordered phases, per-file contracts, the exact functions each module exports,
what each phase must prove before the next one starts, and the tests that prove it.

Read the design brief for rationale. Read this for sequencing.

### Ground rules carried over from the brief

1. **No fabricated numbers.** Ranking is a weighted sum of five named signals rendered as a
   breakdown. No "predicted engagement %", no "72% match". `IMPROVEMENT-PLAN.md` §2.3
   already killed one of these; ENGINE does not reintroduce it.
2. **Sentence boundaries are structural, not heuristic.** Every clip is a contiguous range of
   `MultimodalEngine.segment_transcript_into_sentences` output. Mid-sentence starts are
   impossible by construction, and `clip_eval.py` regression-guards that at 0%.
3. **Degraded mode is honest.** No LLM key → heuristic beats, `degraded: true` on the
   response, amber banner in the UI — mirroring the cross-encoder fallback already at
   [vector_store.py:873](backend/vector_store.py:873).
4. **ENGINE consumes the Vault; it does not modify retrieval.** Search behaviour, thresholds,
   and `backend/eval/run_eval.py` are untouched. ENGINE writes only to new files.

### Repo facts verified before writing this plan

| Claim | Verified |
| --- | --- |
| Sentence chunker with `sentence_idx` / `start_sec` / `end_sec` | ✅ [multimodal_engine.py:316](backend/multimodal_engine.py:316), caps at 40s / 80 words ([:312](backend/multimodal_engine.py:312)) |
| Corpus IDF available for quotability | ✅ [multimodal_engine.py:159](backend/multimodal_engine.py:159) |
| Cross-encoder loader available for hook scoring | ✅ [vector_store.py:66](backend/vector_store.py:66) |
| `openai>=1.0` already a dependency (Groq is wire-compatible) | ✅ `backend/requirements.txt` |
| `opencv-python-headless`, `Pillow`, `numpy`, `scikit-learn` present | ✅ same |
| Test suite clobbers real data | ✅ [test_vector_store.py:129](backend/tests/test_vector_store.py:129) patches `KEYFRAMES_DIR` + `MEDIA_DIR` only — **not** `CHUNKS_FILE`, `VIDEOS_FILE`, `EMBEDDINGS_FILE`, `VISUAL_EMBEDDINGS_FILE`, `HIGHLIGHTS_FILE`, `INDEX_META_FILE` ([vector_store.py:79-86](backend/vector_store.py:79)) |
| `ffmpeg` / `ffprobe` / `yt-dlp` on PATH | ❌ absent — hence `imageio-ffmpeg` |
| Frontend dev server config | ✅ `.claude/launch.json` → `vault-frontend`, port 3000 |

> **Path correction.** The brief writes `data/...`. The actual constant is
> `DATA_DIR = <backend>/data` ([vector_store.py:79](backend/vector_store.py:79)). Every path in
> this plan is **`backend/data/...`**. New modules must import the existing constants rather
> than recomputing them, so a single monkeypatch point stays possible.

---

## 1. Architecture

```
Vault (existing, read-only to ENGINE)        ENGINE (new)
─────────────────────────────────────        ────────────
store.chunks   ──sentences──────────────►  ② narrative_engine  ──beats──┐
store.videos   ──metadata───────────────►                               │
data/keyframes ──frames─────────────────►  ④ brand_kit                  │
data/media     ──bytes──┐                                               ▼
                        ├───────────────►  ① word_timing  ──────────► ③ clip_scoring
① media_service ────────┘                                               │
   (yt-dlp)                                                             ▼
                                           ⑤ caption_render + clip_renderer ──► .mp4
                                           ⑥ jobs.py drives ①–⑤ off the request thread
```

### New backend modules

| File | Exports | Depends on |
| --- | --- | --- |
| `backend/paths.py` | All `DATA_DIR`-derived path constants, one place | — |
| `backend/jobs.py` | `submit`, `get`, `list_for_video`, `JobRecord` | `paths` |
| `backend/media_service.py` | `ensure_media`, `probe`, `ffmpeg_exe`, `MediaUnavailable` | `paths` |
| `backend/word_timing.py` | `ensure_words`, `load_words`, `snap_to_words`, `silence_gap_before/after` | `media_service`, `transcript_service` |
| `backend/llm_client.py` | `complete_json`, `is_configured`, `LLMUnavailable` | `openai` |
| `backend/narrative_engine.py` | `extract_beats`, `heuristic_beats`, `beats_to_candidates`, `analyze_video` | `llm_client`, `word_timing` |
| `backend/clip_scoring.py` | `score_candidate`, `rank`, `WEIGHTS`, `record_feedback` | `vector_store`, `multimodal_engine` |
| `backend/brand_kit.py` | `load`, `save`, `autoseed`, `BrandKit` | `paths`, `sklearn`, `cv2` |
| `backend/caption_render.py` | `build_cues`, `render_cue_pngs` | `brand_kit`, `Pillow` |
| `backend/clip_renderer.py` | `render_clip`, `PRESETS` | `media_service`, `caption_render` |

`backend/paths.py` is an addition to the brief. It exists so Phase 0's test fix has exactly
one seam to monkeypatch, instead of ten scattered module-level constants. `vector_store.py`
re-imports from it for backwards compatibility; nothing else changes there.

### Storage layout (all under `backend/data/`)

```
clips.json                  clip_id -> ClipCandidate (beats + score breakdown + provenance)
brand_kit.json              single BrandKit object
jobs.json                   job_id  -> JobRecord
clip_feedback.json          [{clip_id, verdict, ts}]
words/{video_id}.json       [{word, start, end}]
media/{video_id}.mp4        now also populated for YouTube sources (Stage 0)
clips/{clip_id}/{preset}.mp4
```

Add to `.gitignore`: `backend/data/words/`, `backend/data/clips/`, `backend/data/clips.json`,
`backend/data/jobs.json`, `backend/data/clip_feedback.json`. `brand_kit.json` stays ignored
too — it is creator state, not repo state.

---

## 2. Phases

Each phase lists **deliverable → contract → exit criterion**. Do not start a phase until the
previous one's exit criterion is met and its tests pass.

---

### Phase 0 — Foundation: stop the test suite eating the library

**Why first.** ENGINE adds five more JSON files to `backend/data/`. Every one of them lands
inside the current blast radius. Fixing this after the fact means debugging data loss with
five more moving parts.

#### 0.1 Extract `backend/paths.py`

```python
# backend/paths.py
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

MEDIA_DIR              = os.path.join(DATA_DIR, "media")
KEYFRAMES_DIR          = os.path.join(DATA_DIR, "keyframes")
CHUNKS_FILE            = os.path.join(DATA_DIR, "chunks.json")
EMBEDDINGS_FILE        = os.path.join(DATA_DIR, "embeddings.npy")
VISUAL_EMBEDDINGS_FILE = os.path.join(DATA_DIR, "visual_embeddings.npy")
VIDEOS_FILE            = os.path.join(DATA_DIR, "videos.json")
HIGHLIGHTS_FILE        = os.path.join(DATA_DIR, "highlights.json")
INDEX_META_FILE        = os.path.join(DATA_DIR, "index_meta.json")

# ENGINE
WORDS_DIR              = os.path.join(DATA_DIR, "words")
CLIPS_DIR              = os.path.join(DATA_DIR, "clips")
CLIPS_FILE             = os.path.join(DATA_DIR, "clips.json")
BRAND_KIT_FILE         = os.path.join(DATA_DIR, "brand_kit.json")
JOBS_FILE              = os.path.join(DATA_DIR, "jobs.json")
CLIP_FEEDBACK_FILE     = os.path.join(DATA_DIR, "clip_feedback.json")


def use_root(root: str) -> None:
    """Repoint every path at `root`. Tests call this via the redirect_data fixture."""
```

`use_root` rebinds the module globals. Because every consumer reads them through the module
(`paths.CHUNKS_FILE`, not `from paths import CHUNKS_FILE`), one call redirects the whole
system. This is the seam.

`vector_store.py` and `multimodal_engine.py` keep their existing names as re-exports so no
call site outside them changes:

```python
from paths import DATA_DIR, MEDIA_DIR, CHUNKS_FILE, ...   # replaces the local definitions
```

**Careful:** `vector_store.py` currently does `from multimodal_engine import ..., KEYFRAMES_DIR`
([vector_store.py:13](backend/vector_store.py:13)). Internal reads must become `paths.KEYFRAMES_DIR`
for the redirect to bite. Grep for every bare use of these constants and qualify it.

#### 0.2 Autouse test fixture

`backend/tests/conftest.py` (new):

```python
import pytest, paths

@pytest.fixture(autouse=True)
def redirect_data(tmp_path):
    """Every test in this suite writes to tmp_path. Non-negotiable."""
    paths.use_root(str(tmp_path))
    yield
```

Autouse means no test can forget. Add a guard test that asserts `paths.DATA_DIR` is not the
real backend data dir while tests run — so a future refactor that breaks the seam fails
loudly rather than silently deleting a library.

#### 0.3 Repair the damaged data

`backend/data/` is absent in this checkout (gitignored), but on the user's machine the brief
reports `chunks.json` holding a stray `chunk-vid-b-1` fixture, `videos.json == {}`, and
`visual_embeddings.npy` still at 67 rows. Ship `backend/scripts/repair_index.py`:
detect row-count mismatch between `chunks.json` and the two `.npy` files, report it, and
offer `--rebuild` to drop orphan embedding rows and re-derive `videos.json` from surviving
chunks. If nothing is salvageable it says so plainly rather than half-fixing.

#### 0.4 `backend/jobs.py`

```python
@dataclass
class JobRecord:
    id: str; kind: str; video_id: str | None
    status: Literal["queued", "running", "done", "failed"]
    stage: str; progress: float; message: str
    error: str | None; result: dict | None
    created_at: float; updated_at: float

def submit(kind: str, fn: Callable[[Callable[[str, float, str], None]], dict],
           video_id: str | None = None) -> str: ...
def get(job_id: str) -> JobRecord | None: ...
def list_for_video(video_id: str) -> list[JobRecord]: ...
```

- `ThreadPoolExecutor(max_workers=1)`. Serial by design: Whisper and ffmpeg both saturate CPU,
  and parallelism here trades a slow success for two slow failures.
- `fn` receives a `report(stage, progress, message)` callback; every state change writes
  `jobs.json` under a lock.
- On process start, any job left `running` is marked `failed` with
  `"interrupted by restart"` — never resurrect a dead job as in-flight.
- Retain the last 200 job records; drop older ones.
- Generic enough that `/api/upload_transcribe` can move onto it later
  (`IMPROVEMENT-PLAN.md` §3.3), but **do not migrate it in this phase.**

**Exit criterion.** `pytest backend/tests -v` passes, and after a full run
`git status backend/data` is clean and `chunks.json` byte-identical. Verify by hashing before
and after. A `jobs.py` unit test submits a job that reports three stages and asserts the
persisted record's terminal state.

---

### Phase 1 — Media + precise timing

Nothing downstream works without source bytes and sub-second boundaries.

#### 1.1 `media_service.py`

```python
class MediaUnavailable(Exception):
    """Carries a creator-facing message and a machine-readable reason code."""

def ffmpeg_exe() -> str:            # imageio_ffmpeg.get_ffmpeg_exe(), cached
def ensure_media(video_id: str) -> Path
def probe(path: Path) -> MediaInfo  # width, height, fps, duration_sec — via cv2
```

`ensure_media`:
1. Local upload → `backend/data/media/{video_id}{ext}` already written by
   `/api/upload_transcribe` ([main.py:351](backend/main.py:351)). Return it.
2. YouTube → `yt-dlp`, format `bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]`,
   output `backend/data/media/{video_id}.mp4`. Download to `.part` and atomically rename, so
   an interrupted fetch never leaves a truncated file that later looks cached.
3. Cached — an existing non-zero file short-circuits.
4. Anything else (age-gated, region-locked, private, yt-dlp broken by a YouTube change) →
   `MediaUnavailable` with an actionable message. The API returns **422 with that message**,
   never a 500.

`probe` uses OpenCV (`cv2.VideoCapture` → `CAP_PROP_FRAME_WIDTH/HEIGHT/FPS/FRAME_COUNT`), the
same approach already at [multimodal_engine.py:393](backend/multimodal_engine.py:393).
**`imageio-ffmpeg` bundles `ffmpeg` only — there is no `ffprobe`.** Do not reach for it.

Add a one-line in-product disclosure near the Analyze button: downloading is scoped to the
creator's own catalogue.

#### 1.2 `word_timing.py`

The chunker stores `math.floor(start)` / `math.ceil(end)` — integer seconds. A ±1s slop clips
the first word or leaves dead air, which is the "starts mid-sentence" complaint wearing a
different hat.

```python
def ensure_words(video_id: str, report=None) -> Path      # background job
def load_words(video_id: str) -> list[Word] | None
def snap_to_words(video_id, start_sec, end_sec,
                  lead_in=0.12, tail=0.25) -> tuple[float, float]
def silence_gap_before(video_id, t) -> float
def silence_gap_after(video_id, t) -> float
```

- One Whisper pass per video, `word_timestamps=True`, via
  `transcript_service.preload_whisper_model()`. Write `backend/data/words/{video_id}.json`.
- **No `faster-whisper` in this phase.** It is the known upgrade
  (`IMPROVEMENT-PLAN.md` §3.4) and a separate change; introducing it here couples two risks.
- `snap_to_words` picks the word boundary nearest each requested edge, then applies the
  lead-in/tail so cuts breathe. Never crosses into an adjacent word.
- **Fallback is mandatory.** If the words file is missing, `snap_to_words` returns the input
  unchanged and callers mark `timing_precise: false`. ENGINE degrades; it does not crash.
- A 25-min video on Whisper `base`/CPU takes minutes → strictly a `jobs.py` job, reported as
  its own stage.

**Exit criterion.** `ensure_media` returns a playable file for one YouTube video and one local
upload. `ensure_words` produces a words file whose first and last timestamps sit inside the
video duration. `snap_to_words` unit tests cover lead-in/tail, exact-boundary input, and the
missing-file fallback.

---

### Phase 2 — Narrative intelligence ⭐ **checkpoint phase**

> **If the beats and rankings here aren't visibly better than audio-peak selection, stop.**
> The rendering pipeline is downstream of this claim and worthless without it. This phase is
> deliberately placed before any pixel is rendered so the value is provable while it is still
> cheap to abandon.

#### 2.1 `llm_client.py`

Groq is OpenAI-wire-compatible, so this needs **zero new packages**.

```python
BASE_URL = os.getenv("VAULT_LLM_BASE_URL", "https://api.groq.com/openai/v1")
API_KEY  = os.getenv("VAULT_LLM_API_KEY")
MODEL    = os.getenv("VAULT_LLM_MODEL", "llama-3.3-70b-versatile")

def is_configured() -> bool
def complete_json(system: str, user: str, schema: dict, *, max_retries: int = 1) -> dict
class LLMUnavailable(Exception): ...
```

- `response_format={"type": "json_object"}`; validate the parse against `schema`; on failure
  retry **once** with the validation error appended to the user message; then `LLMUnavailable`.
- Exponential backoff on HTTP 429 (free-tier TPM caps), max 3 attempts, jittered.
- Keeping the provider behind `base_url` + `model` env vars means Groq, Cerebras, OpenRouter's
  free tier, and a local Ollama server all work with no code change.
- **Verify the Groq model ID against their live model list at implementation time.** Groq
  rotates and retires IDs; `llama-3.3-70b-versatile` is a starting point, not a guarantee. On a
  404-model error, surface the provider's message verbatim rather than falling silently into
  degraded mode — a typo'd model name and a missing key deserve different diagnoses.

#### 2.2 Beat extraction

Input is the sentence list the Vault already has: `store.chunks` filtered by `video_id`,
sorted by `sentence_idx`. **No re-derivation** — reusing the same units is what makes the
mid-sentence guarantee structural.

Prompt format:

```
[12] 03:41  So I walked into that meeting completely convinced.
[13] 03:47  And then my manager said something I've never repeated to anyone.
```

Output schema, one object per beat:

```json
{
  "beat_type": "hook|setup|punchline|confession|turning_point|lesson|payoff|cta|tangent",
  "start_sentence_idx": 12,
  "end_sentence_idx": 19,
  "requires_setup_from_idx": 10,
  "title": "The confession",
  "why_it_lands": "The pause before the admission is the payload...",
  "emotional_arc": {"opening": "confident", "peak": "vulnerable", "closing": "resolved"},
  "self_contained": false,
  "quotable_line": "I've never repeated this to anyone."
}
```

Post-parse validation, before anything trusts a beat: indices exist, `start <= end`,
`requires_setup_from_idx <= start_sentence_idx`, `beat_type` in the enum,
`quotable_line` actually appears in the referenced range. Drop invalid beats and log; do not
let a hallucinated index propagate into a cut.

**Long transcripts.** Above ~8k input tokens, window into 60-sentence passes with 10-sentence
overlap, extract per window, dedupe by sentence-range overlap. Cache the result in
`clips.json` — analysis runs **once** per video.

#### 2.3 Beats → clip candidates (the actual fix)

A candidate is a contiguous sentence range that **provably contains every beat its payoff
depends on**. `requires_setup_from_idx` is a hard constraint in a small solver, not a hint.

1. Seed on payoff-class beats: `punchline`, `confession`, `turning_point`, `lesson`, `payoff`.
2. Expand backwards to `min(requires_setup_from_idx)`, **transitively** — a setup with its own
   dependency drags that in too. Guard against cycles.
3. Expand forward to the end of the payoff sentence.
4. Reject if duration falls outside `[MIN_CLIP_SEC=12, MAX_CLIP_SEC=75]`. If over, drop the
   weakest *optional* setup and retry; a required setup is never droppable — the candidate
   dies instead. **A clip that violates its dependency chain must never be emitted, even if
   that means returning fewer clips.**
5. Merge candidates overlapping >60% by sentence count, keeping the higher-scoring one.

> **This is the design's core claim: it is structurally impossible for ENGINE to emit a clip
> that cuts between a setup and its punchline.** `test_narrative_engine.py` and
> `clip_eval.py` both guard it.

#### 2.4 Degraded mode

No key, provider down, or `LLMUnavailable` → `heuristic_beats()`:

- question→answer sentence pairing,
- discourse markers ("but then", "here's the thing", "what nobody tells you"),
- speaking-rate deltas from Phase 1 word timing,
- cross-encoder similarity against a small bundled set of beat archetypes, via the already
  loaded `get_cross_encoder()`.

Responses carry `degraded: true`; the UI shows the same amber banner treatment as
`App.tsx:298`. Honest, weaker, always available — the pattern the search layer already set.

#### 2.5 `clip_scoring.py`

Five signals, each normalised 0–1, weights in one module-level dict so tuning happens in one
place and shows up in one diff.

| Signal | Computation |
| --- | --- |
| `hook_strength` | First 3s. Cross-encoder against bundled hook archetypes, blended with the LLM beat type where `hook` |
| `self_containedness` | Penalise unresolved deixis in the opening sentence (`that`, `he`, `this thing`, `as I said`) using the existing tokenizer/stopword machinery; combined with the LLM `self_contained` flag |
| `emotional_delta` | LLM arc labels **plus** an acoustic proxy: RMS-energy variance and WPM change across the clip, numpy over a wav decoded by the bundled ffmpeg |
| `quotability` | Distinctiveness of `quotable_line` via `compute_corpus_idf` ([multimodal_engine.py:159](backend/multimodal_engine.py:159)) against the whole library — distinctive *for this creator* |
| `boundary_cleanliness` | Silence gap before the first word / after the last, from Phase 1 timings. Rewards clips that don't clip a breath |

Composite = weighted sum → rank. UI renders per-signal bars plus a one-line reason
("#1 — strongest on emotional delta and hook"). **No percentage anywhere.**

Ties break deterministically on `(composite, -start_sec, clip_id)` so repeated runs produce a
stable order — the eval harness depends on it.

**Optional sixth signal — creator-taught taste.** `POST /api/engine/feedback` accumulates
`{clip_id, verdict: winner|dud}` in `clip_feedback.json`. At **≥10 labels**, compute a
preference centroid in MiniLM space over clip text and add `taste_match` (cosine to centroid)
as a sixth weighted signal. Below 10 the signal is **omitted entirely** and the UI says how
many more labels it needs. This is real personalization from data the creator owns — the
honest version of "it knows what performs for you."

**Exit criterion — the checkpoint.** On two real videos, `POST /api/engine/analyze` returns
4–6 ranked candidates with beats and per-signal breakdowns; the same call in degraded mode
returns weaker-but-valid candidates flagged `degraded: true`; `test_narrative_engine.py` proves
the setup constraint holds. **Review the clips by hand against what audio-peak selection would
have picked. If they are not visibly better, stop and reassess before Phase 3.**

---

### Phase 3 — Brand Kit

Auto-seed, then hand control to the creator.

**Auto-seeded:**
- **Palette** — `sklearn.cluster.KMeans` (already installed, `random_state` pinned for
  determinism) over pixels sampled from up to 40 keyframes in `backend/data/keyframes/`.
  Five clusters → primary / accent / text / stroke; accent = most-saturated non-neutral cluster.
- **Rhythm** — mean shot length from OpenCV frame-difference scene detection; WPM from word
  timings.

**Not auto-detected: fonts.** Detecting a typeface from burned-in captions is unreliable, and a
wrong guess is worse than asking. Ship three open-licence fonts in `backend/assets/fonts/`
(Inter, Anton, Archivo Black — check each licence permits redistribution before committing).
Pillow loads them directly: no system-font dependency, byte-identical rendering across machines.

`backend/data/brand_kit.json`:

```json
{
  "fonts": {"caption": "Anton", "display": "Inter"},
  "colors": {"primary": "#0a0a0a", "accent": "#ff7a17", "text": "#ffffff", "stroke": "#000000"},
  "caption": {"position": "bottom-center", "case": "upper", "max_words_per_cue": 4,
              "highlight_style": "active-word-accent", "animation": "pop"},
  "rhythm": {"avg_shot_sec": 2.4, "wpm": 168},
  "safe_margins": {"top": 0.12, "bottom": 0.18},
  "auto_seeded": true
}
```

`auto_seeded` flips to `false` on first edit, so re-seeding never silently overwrites the
creator's choices. `POST /autoseed` on an edited kit must warn before overwriting.

**Exit criterion.** Auto-seed on the existing keyframe set produces a plausible palette and is
byte-identical across two runs. Editing then re-seeding prompts rather than clobbering.

---

### Phase 4 — Render

#### 4.1 `caption_render.py`

**Captions are Pillow-rendered PNGs, not libass.** The bundled `imageio-ffmpeg` static build is
minimal and its subtitle-filter support is not guaranteed. Rendering cues ourselves removes
that dependency risk entirely *and* gives exact control over brand fonts, colours, stroke, and
per-word highlighting — which is the whole point of the feature.

```python
def build_cues(words, max_words_per_cue, case) -> list[Cue]
def render_cue_pngs(clip_id, cues, brand_kit, size, fps=12) -> Path
```

- Group words into cues of `max_words_per_cue`.
- One transparent RGBA PNG per cue-state at 12 fps into `tmp/{clip_id}/cap_%05d.png`. A new
  state is emitted when the active word changes → karaoke-style highlighting.
- Bounded cost: a 30s clip ≈ 360 small PNGs. Delete `tmp/{clip_id}/` after the ffmpeg pass
  succeeds; on failure keep it for diagnosis.
- Text must respect `safe_margins` and wrap rather than overflow the frame.

#### 4.2 `clip_renderer.py`

One ffmpeg pass per preset:

```
ffmpeg -ss <start> -to <end> -i <source>
       -framerate 12 -i tmp/{clip_id}/cap_%05d.png
       -filter_complex "[0:v]scale=...,crop=<W>:<H>[v];[v][1:v]overlay=format=auto[out]"
       -map "[out]" -map 0:a -c:v libx264 -crf 20 -preset veryfast -c:a aac
       backend/data/clips/{clip_id}/{preset}.mp4
```

Place `-ss`/`-to` **before** `-i` for fast seeking, and verify the first frame lands on the
snapped word boundary — input-seek can drift to the nearest keyframe. If drift exceeds ~100ms,
fall back to output-seek for that clip and note the cost.

| Preset | Output | Caption treatment |
| --- | --- | --- |
| `tiktok` | 1080×1920 (9:16) | High-energy, upper-case, active-word accent |
| `shorts` | 1080×1920 (9:16) | Same + end-screen CTA cue in last 2s |
| `linkedin` | 1080×1080 (1:1) | Sentence case, calmer, no pop animation |
| `x` | 1920×1080 (16:9) | Minimal, lower third |

> **Stated v1 limitation: reframing is a static centre crop.** An off-centre speaker will be
> badly framed. Face-tracking / speaker-following crop is explicitly out of scope for v1 and is
> the highest-value v2 addition. **Say so in the UI** next to the aspect-ratio picker rather
> than shipping silent decapitations.

Render runs as a `jobs.py` job reporting stages: `cutting → captions → encoding → done`.

**Exit criterion.** `tiktok` and `linkedin` renders of the same clip both play, both start on
the snapped word, captions use the chosen font and accent colour, aspect ratios are exact.

---

### Phase 5 — API + Frontend

#### 5.1 Routes

All in `backend/main.py`, following the existing Pydantic-model + `store`-singleton pattern
([main.py:145](backend/main.py:145)).

```
POST   /api/engine/analyze                 {video_id, max_clips=6}   -> {job_id}
GET    /api/engine/jobs/{job_id}                                     -> JobRecord
GET    /api/engine/clips/{video_id}                                  -> [ClipCandidate]
POST   /api/engine/clips/{clip_id}/adjust  {start_sec, end_sec}      -> snapped ClipCandidate
POST   /api/engine/render                  {clip_id, presets:[...]}  -> {job_id}
GET    /api/engine/clip_file/{clip_id}/{preset}                      -> FileResponse(mp4)
GET    /api/engine/brand_kit                                         -> BrandKit
PUT    /api/engine/brand_kit               {…}                       -> BrandKit
POST   /api/engine/brand_kit/autoseed                                -> BrandKit
POST   /api/engine/feedback                {clip_id, verdict}        -> {label_count}
```

`/analyze` chains as one job: `ensure_media → ensure_words → beats → candidates → score`,
each a reported stage. `MediaUnavailable` → **422 with the creator-facing message**, not 500.
`clip_file` must validate `clip_id` and `preset` against known values before touching the
filesystem — these are path components.

#### 5.2 Frontend

New top-level **ENGINE** view alongside search (tab in `src/components/Header.tsx`). Reuse the
existing design tokens in `tailwind.config.js` / `src/index.css`.

| Component | Role |
| --- | --- |
| `ClipStudio.tsx` | Video picker → Analyze → ranked clip list |
| `ClipCard.tsx` | Keyframe, title, beat type, duration, `ScoreBreakdown`, render buttons. Mirrors `ResultCard.tsx` and its honest-confidence language |
| `ScoreBreakdown.tsx` | Per-signal horizontal bars + top-contributor sentence. **No %.** |
| `ClipPreview.tsx` | Reuses `VideoPlayerModal`'s player with a DOM caption overlay driven by the *same* brand kit + word timings, so preview matches the render |
| `TrimHandles.tsx` | Drag to adjust, snapping to word boundaries via `/adjust` |
| `BrandKitPanel.tsx` | Palette swatches, font picker, caption position/case/animation, re-seed |
| `RenderQueue.tsx` | Job progress + download links |

Extend `src/services/api.ts` and `src/types.ts` with the ENGINE shapes. Feed the existing
`IndexingProgressModal` real job data instead of derived stats.

> `prd.md` §8 mandates **no shadows**. The codebase has drifted to `shadow-2xl`. Do not
> propagate that into new components.

**Exit criterion.** Full loop in the browser: pick video → Analyze → job progress streams →
ranked clips with breakdowns → edit brand kit → preview overlay updates → render two presets →
both download and play.

---

### Phase 6 — Eval + feedback loop

`backend/eval/clip_eval.py`, extending the harness pattern in
[backend/eval/run_eval.py](backend/eval/run_eval.py), which already established the project rule
**"do not tune thresholds by eye."**

- Hand-label ~10 correct clip boundaries across 2 videos in `clip_queries.yaml`.
- Metrics:
  - **mid-sentence-start rate — must be 0 by construction.** This is the regression guard on
    the core claim; if it is ever non-zero the design is broken, not the threshold.
  - mean boundary error (seconds)
  - setup-containment rate
  - IoU against human labels
- Run LLM mode vs heuristic mode side by side to quantify exactly what the API key buys. If the
  gap is small, that is worth knowing before anyone depends on a paid tier.

---

## 3. Dependencies

`backend/requirements.txt` — two lines:

```
yt-dlp>=2024.1.0          # source media for YouTube-ingested videos
imageio-ffmpeg>=0.4.9     # bundled static ffmpeg binary; no system install
```

Reused, already present: `openai` (Groq-compatible), `Pillow`, `opencv-python-headless`,
`numpy`, `scikit-learn`, `sentence-transformers`, `openai-whisper`, `rank_bm25`.

`.env.example` additions:

```
# ENGINE — narrative analysis LLM. OpenAI-wire-compatible; Groq by default.
# Leave VAULT_LLM_API_KEY unset to run in heuristic (degraded) mode.
VAULT_LLM_BASE_URL=https://api.groq.com/openai/v1
VAULT_LLM_API_KEY=
VAULT_LLM_MODEL=llama-3.3-70b-versatile
```

---

## 4. Verification

### Automated

Every new test relies on the Phase 0 autouse `redirect_data` fixture. No test may write to the
real `backend/data/`.

| File | Asserts |
| --- | --- |
| `test_jobs.py` | Stage reporting, terminal states, `running` → `failed` on restart |
| `test_paths.py` | `use_root` redirects every constant; guard that tests never see the real data dir |
| `test_word_timing.py` | `snap_to_words` lead-in/tail, boundary snapping, missing-file fallback |
| `test_narrative_engine.py` | **Given beats where beat 7 declares `requires_setup_from_idx: 3`, no emitted candidate starts after sentence 3.** Duration-bound rejection. Overlap merging. Transitive dependency chains. Cycle guard |
| `test_clip_scoring.py` | Each signal ∈ [0,1]; `taste_match` absent below 10 labels; deterministic composite ordering |
| `test_brand_kit.py` | k-means seeding deterministic for a fixed frame set; `auto_seeded` flips on edit |
| `test_caption_render.py` | Cue grouping respects `max_words_per_cue`; PNG count matches expected state changes |
| `test_llm_client.py` | Schema-validation retry; `LLMUnavailable` → heuristic path returns `degraded: true` |
| `test_media_service.py` | Cache hit skips download; `MediaUnavailable` carries an actionable message (network mocked) |

```bash
cd "D:\hackathon\Project-stones" && .venv/Scripts/python.exe -m pytest backend/tests -v
```

> The brief's copy of this command points at `C:\Helm\Project stones`, which is not this
> machine. Use the path above.

Immediately after the suite, confirm the Phase 0 fix held:

```bash
cd "D:\hackathon\Project-stones" && git status --short backend/data
```

### End-to-end manual

1. `start.bat`
2. Ingest a YouTube video.
3. Open ENGINE → Analyze. Confirm job progress streams through real stages (not a fake
   progress bar) and clips appear ranked with per-signal breakdowns.
4. Edit the brand kit; confirm the preview overlay updates to match.
5. Render `tiktok` + `linkedin`.
6. Play both `.mp4`s and verify: **no mid-sentence start**, punchline present **with its
   setup**, captions in the chosen font/colour, aspect ratio exact.
7. Unset `VAULT_LLM_API_KEY`, re-run Analyze on a second video, confirm the amber degraded
   banner and that clips still generate.

Verify the frontend with the Browser pane (`preview_start` → the `vault-frontend` dev server in
`.claude/launch.json`) and screenshot the studio view.

---

## 5. Risks

| # | Risk | Mitigation | Phase |
| --- | --- | --- | --- |
| 1 | **Test suite destroys the real library.** [test_vector_store.py:129](backend/tests/test_vector_store.py:129) patches `KEYFRAMES_DIR`/`MEDIA_DIR` but not `CHUNKS_FILE`/`VIDEOS_FILE`/`EMBEDDINGS_FILE`, so `_build_store_with_chunks()` + `delete_video()` call `_save_to_disk()` against `backend/data/`. Confirmed: the brief reports `chunks.json` holding a stray `chunk-vid-b-1` fixture and `videos.json == {}` while `visual_embeddings.npy` still has 67 rows | `paths.py` + autouse fixture + guard test + `repair_index.py` | **0 — blocking** |
| 2 | Groq free-tier rate limits | Windowing, jittered backoff, analysis cached once per video | 2 |
| 3 | Groq rotates/retires model IDs | Model behind an env var; verify the ID at implementation time; surface provider errors verbatim | 2 |
| 4 | Whisper re-transcription slow on CPU `base` | Job queue keeps it off the request path; `faster-whisper` is the known follow-up (`IMPROVEMENT-PLAN.md` §3.4), deliberately not bundled into this change | 1 |
| 5 | Static centre crop mis-frames off-centre speakers | Accepted v1 limitation, **disclosed in-product**; face-tracking is the v2 headline | 4 |
| 6 | yt-dlp fragile against YouTube changes | Failures surface as actionable 422s, not 500s; pin a floor version and expect to bump it | 1 |
| 7 | Quality materially lower without an LLM key | Degraded mode is banner-flagged and mirrors the existing reranker fallback; Phase 6 quantifies the gap | 2, 6 |
| 8 | Full reindex on every write is already O(n²) ([vector_store.py](backend/vector_store.py)) | ENGINE writes to separate files and does not worsen it — but it caps library size, and that ceiling is pre-existing | — |
| 9 | Font licences must permit redistribution | Verify each before committing binaries to `backend/assets/fonts/` | 3 |

---

## 6. Build order summary

| Phase | Deliverable | Gate |
| --- | --- | --- |
| **0** | `paths.py`, `conftest.py` fixture, `repair_index.py`, `jobs.py` | Suite passes; `backend/data` unchanged after a run |
| **1** | `media_service.py`, `word_timing.py` | Media resolves for both source types; words file valid |
| **2** | `llm_client.py`, `narrative_engine.py`, `clip_scoring.py`, clips API | ⭐ **Human review of clip quality vs audio-peak baseline. Stop here if not better.** |
| **3** | `brand_kit.py` + auto-seed | Deterministic palette; edit protection works |
| **4** | `caption_render.py`, `clip_renderer.py`, presets | Two presets render and play correctly |
| **5** | ENGINE studio frontend | Full loop in the browser |
| **6** | `clip_eval.py` + feedback loop | Mid-sentence-start rate = 0; LLM vs heuristic gap quantified |
