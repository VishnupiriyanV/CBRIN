import uvicorn
import shutil
import tempfile
import os
import json
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Must run before any os.getenv/os.environ reads below (CORS origins, OPENAI_API_KEY,
# VAULT_WHISPER_MODEL) — see .env.example for what's configurable.
load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import io

import paths
from vector_store import VectorStore, get_cross_encoder
from transcript_service import fetch_youtube_transcript, transcribe_file_with_whisper, fetch_youtube_metadata, preload_whisper_model, content_hash_id, get_youtube_video_id, WHISPER_MODEL_TIERS, WHISPER_MODEL_SIZE
from multimodal_engine import preload_models

# Shared background job queue (backend/jobs.py) — used by both ingestion (upload/YouTube
# fetch/transcribe/chunk/embed, IMPROVEMENT-PLAN.md 3.3) and ENGINE's narrative analysis /
# clip rendering. One serial worker: Whisper, CLIP, and ffmpeg all saturate a single CPU core,
# so nothing here is meant to run concurrently with itself.
import jobs
import media_service
import word_timing
import narrative_engine
import clip_scoring
import brand_kit as brand_kit_module
import clip_renderer

# STUDIO (Layer 4) — text-in/text-out creator tools built on the same llm_client/jobs
# infrastructure ENGINE introduced. See creator-tools-integration-spec.md.
import llm_client
import studio_runner
import studio_prompts
import voice_profile
import platform_rules
import tool_runs
import usage
import agent_engine


def _repair_stale_chunks(store: "VectorStore"):
    """
    One-time migration: chunks persisted before sentence-level indexing (missing
    `sentence_idx`) get evicted from the live index by VectorStore on load (see
    vector_store._evict_stale_chunks) because they break search()'s window-merge logic.
    Re-derive them here from their original source — a fresh YouTube transcript fetch, or
    Whisper re-transcription of the still-persisted local media file — so the library
    repairs itself instead of quietly serving degraded search results forever.

    Runs at most once per video: a successful (or exhausted) repair bumps the on-disk
    schema version, so this is a no-op on every subsequent boot — it does not re-attempt
    on every startup the way the old unconditional visual-embedding reindex did (1.6).
    """
    if not store.pending_rechunk:
        return

    print(f"[Vault API] Re-chunking {len(store.pending_rechunk)} video(s) with an outdated index format...")

    for vid_id in store.pending_rechunk:
        old_meta = store.pending_rechunk_meta.get(vid_id, {"id": vid_id})
        title = old_meta.get('title', vid_id)
        try:
            if old_meta.get('youtube_id'):
                data = fetch_youtube_transcript(old_meta['youtube_id'])
                video_meta = data['video_meta']
                new_chunks = store.chunk_transcript(data['segments'], video_meta)
                if not new_chunks:
                    raise ValueError("Re-fetched transcript produced no chunks.")
                store.add_video(video_meta)
                store.add_chunks(new_chunks)

            elif old_meta.get('is_local'):
                media_path = None
                for ext in ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.mp3', '.wav', '.m4a']:
                    fpath = os.path.join(paths.MEDIA_DIR, f"{vid_id}{ext}")
                    if os.path.exists(fpath):
                        media_path = fpath
                        break
                if not media_path:
                    raise ValueError("Original media file is no longer present on disk.")

                data = transcribe_file_with_whisper(media_path, title)
                video_meta = dict(old_meta)
                video_meta['total_seconds'] = data['video_meta']['total_seconds']
                video_meta['duration_formatted'] = data['video_meta']['duration_formatted']
                video_meta['status'] = 'fully_indexed'
                video_meta['error_message'] = None
                new_chunks = store.chunk_transcript(data['segments'], video_meta, media_path=media_path)
                if not new_chunks:
                    raise ValueError("Re-transcription produced no chunks.")
                store.add_video(video_meta)
                store.add_chunks(new_chunks)

            else:
                raise ValueError("No YouTube ID or local media file available to re-chunk from.")

            print(f"[Vault API] Re-chunked '{title}' successfully.")

        except Exception as e:
            print(f"[Vault API] Automatic re-chunk failed for '{title}' ({vid_id}): {e}")
            store.add_failed_video(
                video_id=vid_id,
                title=title,
                channel=old_meta.get('channel', 'Creator Library'),
                error_msg=f"Index format was upgraded and automatic re-indexing failed: {e}. Delete and re-ingest manually.",
                is_local=old_meta.get('is_local', False),
                youtube_id=old_meta.get('youtube_id'),
                source_url=old_meta.get('source_url'),
            )

    store.finalize_schema_migration()


def _reconcile_interrupted_ingest_jobs(store: "VectorStore"):
    """
    jobs.py marks any job still 'running'/'queued' at process start as failed with
    "interrupted by server restart" (a prior server crash/restart mid-upload) — but jobs.py
    is deliberately store-agnostic, so it never touches videos.json itself. Without this,
    an ingest interrupted mid-flight just vanishes: no success, no failure row, nothing in
    /api/library for the user to see or retry — the upload silently disappears. Back-fill a
    failed video record for any such job whose video_id never made it into store.videos, so
    the failure is visible with a retry option instead of invisible.
    """
    for job in jobs.list_all():
        if job.kind not in ("ingest_upload", "ingest_youtube"):
            continue
        if job.status != "failed" or job.error != "interrupted by server restart":
            continue
        if not job.video_id or job.video_id in store.videos:
            continue

        is_local = job.kind == "ingest_upload"
        store.add_failed_video(
            video_id=job.video_id,
            # The job record doesn't carry the original filename/URL, only video_id — this
            # is the best title recoverable after the fact.
            title="Interrupted Upload" if is_local else "Interrupted YouTube Ingest",
            channel="Local Upload" if is_local else "YouTube Creator",
            error_msg="Ingest was interrupted by a server restart before it could finish. Please retry.",
            is_local=is_local,
        )
        print(f"[Vault API] Recorded interrupted ingest job as failed video: {job.video_id}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-load all machine learning models into memory on server startup."""
    print("[Vault API] Server starting up. Preloading models...")
    try:
        # imageio-ffmpeg's bundled binary isn't on PATH until this runs once — openai-whisper's
        # audio loader and yt-dlp both shell out to a bare "ffmpeg" command rather than
        # accepting a path, so local Whisper transcription (existing upload_transcribe path,
        # plus ENGINE's word_timing) would otherwise fail with WinError 2 on a machine with no
        # system ffmpeg install (verified live on this box).
        media_service.ffmpeg_exe()
    except Exception as e:
        print(f"[Vault API] Error resolving bundled ffmpeg: {e}")

    try:
        preload_models()
    except Exception as e:
        print(f"[Vault API] Error preloading text/CLIP models: {e}")

    try:
        preload_whisper_model()
    except Exception as e:
        print(f"[Vault API] Error preloading Whisper model: {e}")

    try:
        _repair_stale_chunks(store)
    except Exception as e:
        print(f"[Vault API] Stale chunk repair pass failed: {e}")

    try:
        _reconcile_interrupted_ingest_jobs(store)
    except Exception as e:
        print(f"[Vault API] Interrupted-ingest reconciliation pass failed: {e}")

    print("[Cbrin API] Model preloading completed. Server ready on http://localhost:8000.")
    yield
    print("[Cbrin API] Server shutting down.")

app = FastAPI(
    title="Cbrin API",
    description="Multimodal Semantic Search for Creator Content",
    version="0.4.0",
    lifespan=lifespan
)

# Enable CORS for local dev. allow_origins=["*"] + allow_credentials=True is rejected by
# browsers outright — pin to the actual Vite dev origins instead. Override via env var if
# the frontend is served from somewhere else (e.g. a LAN IP or a different port).
_cors_origins = os.environ.get(
    "VAULT_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize vector store
store = VectorStore()


class SearchQuery(BaseModel):
    query: str
    top_k: Optional[int] = 5
    # Two honest modes (IMPROVEMENT-PLAN.md 2.4) — the old 'hybrid'/'questions'/'topics'
    # all ran identical code and only 'visual_scenes' actually branched.
    search_mode: Optional[str] = "spoken"  # spoken, visual_scenes


class IngestRequest(BaseModel):
    youtube_url: str


class HighlightRequest(BaseModel):
    chunk_id: str
    note: Optional[str] = ""


class ImportRequest(BaseModel):
    mode: Optional[str] = "merge"  # merge or replace


class EngineAnalyzeRequest(BaseModel):
    video_id: str
    max_clips: Optional[int] = 6


class EngineAdjustRequest(BaseModel):
    start_sec: float
    end_sec: float


class EngineRenderRequest(BaseModel):
    clip_id: str
    presets: List[str]


class EngineFeedbackRequest(BaseModel):
    clip_id: str
    verdict: str  # "winner" | "dud"


class StudioParseTranscriptRequest(BaseModel):
    text: str


class StudioRunRequest(BaseModel):
    tool_id: str
    inputs: Dict[str, Any]
    use_voice_profile: Optional[bool] = True


class StudioRegenerateRequest(BaseModel):
    run_id: str
    block: str


@app.get("/")
def read_root():
    stats = store.get_stats()
    return {
        "status": "ok",
        "service": "Cbrin API",
        "indexed_chunks": stats["total_chunks"],
        "indexed_videos": stats["indexed_count"],
        "is_fully_indexed": stats["is_fully_indexed"]
    }


@app.get("/api/health")
def health_check():
    return store.get_stats()


@app.get("/api/stats")
def get_stats():
    """Return comprehensive library statistics."""
    return store.get_stats()


@app.get("/api/suggested_queries")
def get_suggested_queries():
    """Return dynamic sample queries derived from actual indexed content."""
    return store.get_suggested_queries()


@app.get("/api/library")
def get_library():
    """Return all indexed videos with real metadata and status."""
    result = []
    for vid_id, meta in store.videos.items():
        chunk_count = sum(1 for c in store.chunks if c.get('video_id') == vid_id)
        # Only count real per-moment frames, not a video-level shared thumbnail (2.10) —
        # otherwise every YouTube video would show a "visual indexed" badge that's honest
        # about individual chunks but misleading about what visual search can do with them.
        visual_count = sum(1 for c in store.chunks if c.get('video_id') == vid_id and c.get('visual_status') == 'ok')
        video_data = {
            "id": vid_id,
            "youtube_id": meta.get('youtube_id'),
            "is_local": meta.get('is_local', False),
            "title": meta.get('title', 'Untitled'),
            "channel": meta.get('channel', 'Creator Library'),
            "duration_formatted": meta.get('duration_formatted', '00:00'),
            "total_seconds": meta.get('total_seconds', 0),
            "thumbnail_url": meta.get('thumbnail_url', ''),
            "chunk_count": chunk_count,
            "visual_chunk_count": visual_count,
            "uploaded_at": meta.get('uploaded_at', ''),
            "category": meta.get('category', 'Indexed Content'),
            "status": meta.get('status', 'fully_indexed'),
            "error_message": meta.get('error_message', None),
            "summary": meta.get('summary', None),
            "topics": meta.get('topics', [])
        }
        result.append(video_data)

    return result


@app.get("/api/media/{video_id}")
def get_media_file(video_id: str):
    """Stream local uploaded audio/video file for HTML5 playback seeking."""
    for ext in ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.mp3', '.wav', '.m4a']:
        fpath = os.path.join(paths.MEDIA_DIR, f"{video_id}{ext}")
        if os.path.exists(fpath):
            return FileResponse(fpath)

    raise HTTPException(status_code=404, detail="Media file not found for local video.")


@app.get("/api/keyframe/{chunk_id}")
def get_keyframe(chunk_id: str):
    """Serve a keyframe thumbnail JPEG for a specific chunk."""
    keyframe_path = os.path.join(paths.KEYFRAMES_DIR, f"{chunk_id}.jpg")
    if os.path.exists(keyframe_path):
        return FileResponse(keyframe_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Keyframe not found for this chunk.")


@app.delete("/api/library/{video_id}")
def delete_video(video_id: str):
    """Delete a video and its transcript chunks from the vector store."""
    if video_id not in store.videos:
        raise HTTPException(status_code=404, detail="Video not found")

    success = store.delete_video(video_id)
    return {
        "success": success,
        "message": f"Deleted video '{video_id}' from library.",
        "stats": store.get_stats()
    }


@app.post("/api/search")
def search_vault(payload: SearchQuery):
    """Semantic multimodal search over the indexed library."""
    if not payload.query or not payload.query.strip():
        raise HTTPException(status_code=400, detail="Search query cannot be empty")

    if not store.chunks:
        return {
            "query": payload.query,
            "results": [],
            "near_misses": [],
            "execution_time_ms": 0,
            "total_chunks_scanned": 0,
            "library_video_count": 0,
            "search_mode": payload.search_mode or "spoken",
            "message": "No content indexed yet. Ingest videos or audio files to start searching."
        }

    return store.search(
        query=payload.query,
        top_k=payload.top_k or 5,
        search_mode=payload.search_mode or "spoken"
    )


def _run_youtube_ingest_job(youtube_url: str):
    """Download-transcript -> chunk (incl. keyframes) -> embed, reported in stages (PRD §7.3:
    ingest must run as a background job with per-stage progress, polled by the existing
    progress modal — a blocking POST previously held the request open for however long
    fetch+chunk+embed took)."""
    def _job(report):
        try:
            report("download", 0.1, "Fetching YouTube transcript...")
            data = fetch_youtube_transcript(youtube_url)
            video_meta = data['video_meta']
            segments = data['segments']

            existing_ids = {c['video_id'] for c in store.chunks}
            if video_meta['id'] in existing_ids:
                report("done", 1.0, "already indexed")
                return {
                    "success": False,
                    "message": f"Video '{video_meta['title']}' is already indexed.",
                    "video": video_meta,
                    "new_chunks_count": 0
                }

            report("chunk", 0.4, "Segmenting transcript and extracting keyframes...")
            new_chunks = store.chunk_transcript(segments, video_meta)

            if not new_chunks:
                raise ValueError("Transcript was fetched but contained no meaningful speech text.")

            report("embed", 0.85, "Embedding chunks into the vector index...")
            store.add_video(video_meta)
            store.add_chunks(new_chunks)

            report("done", 1.0, f"Indexed {len(new_chunks)} chunk(s).")
            return {
                "success": True,
                "message": f"Indexed '{video_meta['title']}' — {len(new_chunks)} transcript chunks embedded.",
                "video": video_meta,
                "new_chunks_count": len(new_chunks)
            }

        except Exception as e:
            try:
                yt_video_id = get_youtube_video_id(youtube_url)
            except ValueError:
                yt_video_id = None

            if yt_video_id:
                meta = fetch_youtube_metadata(yt_video_id)
                vid_id = f"yt-{yt_video_id}"
            else:
                meta = {"title": "Unrecognized YouTube URL", "channel": "YouTube Creator"}
                vid_id = f"yt-unrecognized-{abs(hash(youtube_url)) % 100000}"

            store.add_failed_video(
                video_id=vid_id,
                title=meta['title'],
                channel=meta['channel'],
                error_msg=str(e),
                is_local=False,
                youtube_id=yt_video_id,
                source_url=youtube_url
            )
            raise

    return _job


@app.post("/api/ingest")
def ingest_youtube(payload: IngestRequest):
    """Kick off YouTube ingestion (transcript fetch -> chunk -> embed) as a background job.
    Poll the returned job_id via GET /api/jobs/{job_id}; job.result carries the same
    {success, message, video, new_chunks_count} shape this endpoint used to return directly."""
    if not payload.youtube_url or not payload.youtube_url.strip():
        raise HTTPException(status_code=400, detail="YouTube URL required")

    try:
        yt_video_id = get_youtube_video_id(payload.youtube_url)
        vid_id = f"yt-{yt_video_id}"
    except ValueError:
        vid_id = None

    if vid_id and vid_id in {c['video_id'] for c in store.chunks}:
        existing = store.videos.get(vid_id, {})
        return {
            "success": False,
            "message": f"Video '{existing.get('title', vid_id)}' is already indexed.",
            "video": existing,
            "new_chunks_count": 0
        }

    job_id = jobs.submit("ingest_youtube", _run_youtube_ingest_job(payload.youtube_url), video_id=vid_id)
    return {"job_id": job_id, "video_id": vid_id}


def _run_upload_job(temp_file_path: str, filename: str, file_ext: str, model_tier: str):
    """Transcribe -> chunk (incl. keyframes) -> embed, reported in stages. Runs on the
    background worker thread; `temp_file_path` was already written by the request handler
    before the UploadFile stream closes, so nothing here touches request state."""
    def _job(report):
        try:
            report("transcribe", 0.05, f"Transcribing with Whisper ({model_tier})...")
            data = transcribe_file_with_whisper(temp_file_path, filename, model_tier=model_tier)
            video_meta = data['video_meta']
            segments = data['segments']

            persistent_media_path = os.path.join(paths.MEDIA_DIR, f"{video_meta['id']}{file_ext}")
            shutil.copyfile(temp_file_path, persistent_media_path)

            report("chunk", 0.55, "Segmenting transcript and extracting keyframes...")
            new_chunks = store.chunk_transcript(segments, video_meta, media_path=persistent_media_path)

            # Whisper can return a few segments that are all filler/noise/too-short and get
            # filtered out entirely during sentence-chunking, leaving new_chunks empty even
            # though transcription itself "succeeded". Silently reporting success here (as
            # this used to) meant store.add_video() never ran and the upload vanished from
            # the library with no success AND no failure record — nothing to see or retry.
            # Match the YouTube ingest path's existing behavior: treat "nothing chunkable" as
            # a real failure so it's visible.
            if not new_chunks:
                raise ValueError(
                    f"No indexable visual or text content could be extracted from '{filename}'."
                )

            report("embed", 0.85, "Embedding chunks into the vector index...")
            store.add_video(video_meta)
            store.add_chunks(new_chunks)

            report("done", 1.0, f"Indexed {len(new_chunks)} chunk(s).")
            return {
                "success": True,
                "message": f"Transcribed '{filename}' — {len(new_chunks)} chunks indexed.",
                "video": video_meta,
                "new_chunks_count": len(new_chunks)
            }
        except Exception as e:
            vid_id = content_hash_id(temp_file_path) if os.path.exists(temp_file_path) else f"local-failed-{abs(hash(filename)) % 100000}"
            clean_title = os.path.splitext(filename)[0].replace("-", " ").replace("_", " ").title()
            store.add_failed_video(
                video_id=vid_id,
                title=clean_title,
                channel="Local Upload",
                error_msg=str(e),
                is_local=True
            )
            raise
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    return _job


@app.post("/api/upload_transcribe")
async def upload_and_transcribe_file(file: UploadFile = File(...), model_tier: str = Form(WHISPER_MODEL_SIZE)):
    """Upload a local audio/video file and kick off transcribe -> chunk -> embed as a
    background job (PRD §7.3 — Whisper on CPU runs ~1x realtime, so a 60-minute podcast used
    to block this request for about an hour). Poll the returned job_id via
    GET /api/jobs/{job_id}; job.result carries the same {success, message, video,
    new_chunks_count} shape this endpoint used to return directly.

    `model_tier` selects Whisper accuracy/speed ('base' / 'small' / 'medium', default 'small'
    — PRD §7.2, IMPROVEMENT-PLAN.md 3.4)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    if model_tier not in WHISPER_MODEL_TIERS:
        raise HTTPException(status_code=400, detail=f"model_tier must be one of {list(WHISPER_MODEL_TIERS)}")

    file_ext = os.path.splitext(file.filename)[1].lower()
    temp_dir = tempfile.gettempdir()
    safe_filename = file.filename.replace(" ", "_")
    temp_file_path = os.path.join(temp_dir, safe_filename)

    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Dedup before transcription runs (IMPROVEMENT-PLAN.md 1.4) — this check is cheap (file
    # hash only), so it stays synchronous; only the expensive Whisper/chunk/embed work moves
    # onto the background job below.
    content_id = content_hash_id(temp_file_path)
    if content_id in store.videos:
        os.remove(temp_file_path)
        existing = store.videos[content_id]
        return {
            "success": False,
            "message": f"'{existing.get('title', file.filename)}' is already indexed (identical file content).",
            "video": existing,
            "new_chunks_count": 0
        }

    job_id = jobs.submit(
        "ingest_upload",
        _run_upload_job(temp_file_path, file.filename, file_ext, model_tier),
        video_id=content_id
    )
    return {"job_id": job_id, "video_id": content_id, "filename": file.filename}


@app.get("/api/jobs/{job_id}")
def get_ingest_job(job_id: str):
    """Poll status/progress for any background job — ingest (upload/YouTube) or ENGINE
    (analyze/render). Same job records as /api/engine/jobs/{job_id}; that route is kept as an
    alias for existing ENGINE frontend calls."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job.to_dict()


# --- Highlights / Bookmark Endpoints ---

@app.post("/api/highlights")
def add_highlight(payload: HighlightRequest):
    """Bookmark a chunk result with an optional note."""
    result = store.add_highlight(payload.chunk_id, payload.note or "")
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Highlight failed"))
    return result


@app.get("/api/highlights")
def get_highlights():
    """Return all highlighted/bookmarked moments."""
    return store.get_highlights()


@app.delete("/api/highlights/{chunk_id}")
def remove_highlight(chunk_id: str):
    """Remove a highlight/bookmark."""
    result = store.remove_highlight(chunk_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Highlight not found"))
    return result


# --- Export Endpoints ---

@app.get("/api/export/library")
def export_library(format: str = Query("json", description="Export format: 'json' or 'zip'")):
    """Export the full library as JSON or ZIP."""
    if format == "zip":
        zip_bytes = store.export_library_zip()
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=cbrin_library_export.zip"}
        )
    else:
        data = store.export_library_json()
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        return Response(
            content=json_str,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=cbrin_library_export.json"}
        )


@app.get("/api/export/search")
def export_search_results(
    query: str = Query(..., description="Search query"),
    mode: str = Query("spoken", description="Search mode"),
    format: str = Query("json", description="Export format: 'json' or 'csv'")
):
    """Export search results as JSON or CSV."""
    search_result = store.search(query=query, top_k=20, search_mode=mode)
    results = search_result.get("results", [])

    if format == "csv":
        csv_str = store.export_search_results_csv(results, query)
        return Response(
            content=csv_str,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=cbrin_search_{query[:30].replace(' ', '_')}.csv"}
        )
    else:
        json_str = json.dumps(search_result, indent=2, ensure_ascii=False)
        return Response(
            content=json_str,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=cbrin_search_{query[:30].replace(' ', '_')}.json"}
        )


@app.get("/api/export/highlights")
def export_highlights():
    """Export all highlighted moments as JSON."""
    highlights = store.get_highlights()
    data = {
        "vault_export_version": "1.0",
        "export_type": "highlights",
        "total_highlights": len(highlights),
        "highlights": highlights
    }
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=vault_highlights_export.json"}
    )


# --- Import Endpoint ---

@app.post("/api/import/library")
async def import_library(file: UploadFile = File(...), mode: str = Query("merge", description="Import mode: 'merge' or 'replace'")):
    """Import a previously exported library JSON or ZIP file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    try:
        content = await file.read()

        if file.filename.endswith('.zip'):
            import zipfile
            zip_buffer = io.BytesIO(content)
            with zipfile.ZipFile(zip_buffer, 'r') as zf:
                data = {}
                if 'videos.json' in zf.namelist():
                    data['videos'] = json.loads(zf.read('videos.json'))
                if 'chunks.json' in zf.namelist():
                    data['chunks'] = json.loads(zf.read('chunks.json'))
                if 'highlights.json' in zf.namelist():
                    data['highlights'] = json.loads(zf.read('highlights.json'))
        else:
            data = json.loads(content)

        result = store.import_library(data, mode=mode)
        return result

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


# --- ENGINE (Layer 3): narrative-aware clip generation --------------------------------

def _load_clips() -> Dict[str, Any]:
    if not os.path.exists(paths.CLIPS_FILE):
        return {}
    try:
        with open(paths.CLIPS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_clips(clips: Dict[str, Any]):
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    with open(paths.CLIPS_FILE, 'w', encoding='utf-8') as f:
        json.dump(clips, f, indent=2, ensure_ascii=False)


def _sentences_for_video(video_id: str) -> List[Dict[str, Any]]:
    sentences = [
        {"sentence_idx": c["sentence_idx"], "text": c["text"], "start_sec": c["start_sec"], "end_sec": c["end_sec"]}
        for c in store.chunks
        if c.get("video_id") == video_id and c.get("sentence_idx") is not None
    ]
    sentences.sort(key=lambda s: s["sentence_idx"])
    return sentences


def _run_analyze_job(video_id: str, max_clips: int):
    def _job(report):
        video_meta = store.videos.get(video_id)
        if not video_meta:
            raise ValueError(f"Video '{video_id}' not found in library.")

        sentences = _sentences_for_video(video_id)
        if not sentences:
            raise ValueError(f"Video '{video_id}' has no sentence-level transcript chunks to analyze.")

        report("media", 0.05, "locating source media")
        try:
            media_path = media_service.ensure_media(video_id, youtube_id=video_meta.get("youtube_id"))
        except media_service.MediaUnavailable as e:
            raise ValueError(str(e))

        timing_precise = True
        try:
            report("words", 0.15, "getting word-level timing")
            word_timing.ensure_words(video_id, media_path, report=report)
        except Exception as e:
            timing_precise = False
            print(f"[ENGINE] Word timing unavailable for '{video_id}': {e}. Continuing with sentence-level timing only.")

        report("beats", 0.5, "extracting narrative beats")
        analysis = narrative_engine.analyze_video(sentences, max_clips=max_clips)

        report("scoring", 0.75, "scoring clip candidates")
        sentences_by_idx = {s["sentence_idx"]: s for s in sentences}
        corpus_texts = [c.get("text", "") for c in store.chunks]
        taste_centroid = clip_scoring.compute_taste_centroid()

        ranked = clip_scoring.rank(
            analysis["candidates"], sentences_by_idx, video_id, corpus_texts,
            get_cross_encoder, max_clips=max_clips, taste_centroid=taste_centroid,
        )

        all_clips = _load_clips()
        # Replace this video's previous clips with the fresh analysis.
        all_clips = {cid: c for cid, c in all_clips.items() if c.get("video_id") != video_id}
        for clip in ranked:
            clip["video_id"] = video_id
            clip["degraded"] = analysis["degraded"]
            clip["timing_precise"] = timing_precise
            all_clips[clip["id"]] = clip
        _save_clips(all_clips)

        report("done", 1.0, f"{len(ranked)} clip(s) ready")
        return {"video_id": video_id, "clip_count": len(ranked), "degraded": analysis["degraded"]}

    return _job


@app.post("/api/engine/analyze")
def engine_analyze(payload: EngineAnalyzeRequest):
    """Kick off narrative analysis for a video as a background job. Poll the returned
    job_id via GET /api/engine/jobs/{job_id}, then fetch results via
    GET /api/engine/clips/{video_id}."""
    if payload.video_id not in store.videos:
        raise HTTPException(status_code=404, detail=f"Video '{payload.video_id}' not found.")

    job_id = jobs.submit("engine_analyze", _run_analyze_job(payload.video_id, payload.max_clips or 6), video_id=payload.video_id)
    return {"job_id": job_id}


@app.get("/api/engine/jobs/{job_id}")
def engine_get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job.to_dict()


@app.get("/api/engine/clips/{video_id}")
def engine_get_clips(video_id: str):
    """Return the most recent analysis's ranked clips for a video (empty list if Analyze
    hasn't been run yet, not a 404 — that's a normal, expected state)."""
    all_clips = _load_clips()
    return [c for c in all_clips.values() if c.get("video_id") == video_id]


@app.post("/api/engine/clips/{clip_id}/adjust")
def engine_adjust_clip(clip_id: str, payload: EngineAdjustRequest):
    """Snap a manually-adjusted trim range onto exact word boundaries."""
    all_clips = _load_clips()
    clip = all_clips.get(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail=f"Clip '{clip_id}' not found.")

    snapped_start, snapped_end = word_timing.snap_to_words(clip["video_id"], payload.start_sec, payload.end_sec)
    clip["start_sec"] = snapped_start
    clip["end_sec"] = snapped_end
    all_clips[clip_id] = clip
    _save_clips(all_clips)
    return clip


@app.post("/api/engine/render")
def engine_render(payload: EngineRenderRequest):
    """Render a clip to one or more platform presets as a background job."""
    all_clips = _load_clips()
    clip = all_clips.get(payload.clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail=f"Clip '{payload.clip_id}' not found.")

    unknown_presets = [p for p in payload.presets if p not in clip_renderer.PRESETS]
    if unknown_presets:
        raise HTTPException(status_code=400, detail=f"Unknown preset(s): {unknown_presets}. Valid: {list(clip_renderer.PRESETS.keys())}")

    video_id = clip["video_id"]
    video_meta = store.videos.get(video_id)
    if not video_meta:
        raise HTTPException(status_code=404, detail=f"Video '{video_id}' for this clip no longer exists.")

    def _job(report):
        try:
            media_path = media_service.ensure_media(video_id, youtube_id=video_meta.get("youtube_id"))
        except media_service.MediaUnavailable as e:
            raise ValueError(str(e))

        words = word_timing.load_words(video_id) or []
        kit = brand_kit_module.load()

        results = clip_renderer.render_clip(
            clip_id=payload.clip_id,
            source_path=media_path,
            start_sec=clip["start_sec"],
            end_sec=clip["end_sec"],
            words=words,
            brand_kit=kit,
            presets=payload.presets,
            report=report,
        )
        return {"clip_id": payload.clip_id, "presets": results}

    job_id = jobs.submit("engine_render", _job, video_id=video_id)
    return {"job_id": job_id}


@app.get("/api/engine/clip_file/{clip_id}/{preset}")
def engine_get_clip_file(clip_id: str, preset: str):
    """Serve a rendered clip .mp4. clip_id/preset are validated against known clips/presets
    before touching the filesystem — both are path components."""
    all_clips = _load_clips()
    if clip_id not in all_clips:
        raise HTTPException(status_code=404, detail=f"Clip '{clip_id}' not found.")
    if preset not in clip_renderer.PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown preset '{preset}'.")

    file_path = os.path.join(paths.CLIPS_DIR, clip_id, f"{preset}.mp4")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"'{preset}' has not been rendered for clip '{clip_id}' yet.")
    # Without an explicit filename, the browser infers one from the URL path
    # (/api/engine/clip_file/{clip_id}/{preset}, no .mp4 in it) — give it a real name with
    # the correct extension instead of leaving that to guesswork.
    return FileResponse(file_path, media_type="video/mp4", filename=f"{clip_id}-{preset}.mp4")


@app.get("/api/engine/brand_kit")
def engine_get_brand_kit():
    return brand_kit_module.load()


@app.put("/api/engine/brand_kit")
def engine_update_brand_kit(patch: Dict[str, Any]):
    return brand_kit_module.apply_edit(patch)


@app.post("/api/engine/brand_kit/autoseed")
def engine_autoseed_brand_kit(force: bool = Query(False)):
    try:
        return brand_kit_module.autoseed(force=force)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/engine/feedback")
def engine_feedback(payload: EngineFeedbackRequest):
    if payload.verdict not in ("winner", "dud"):
        raise HTTPException(status_code=400, detail="verdict must be 'winner' or 'dud'.")
    label_count = clip_scoring.record_feedback(payload.clip_id, payload.verdict)
    return {"label_count": label_count}


# --- STUDIO (Layer 4): text-in/text-out creator tools ---------------------------------

@app.get("/api/studio/tools")
def studio_list_tools():
    """llm_configured tells the UI whether to hard-gate every tool. Unlike Vault/ENGINE,
    these tools have no honest heuristic fallback — a rule-based 'repurpose my newsletter'
    would be worse than nothing, so there is no degraded mode here (deliberate divergence,
    see prd.md)."""
    return {"tools": studio_prompts.list_tools(), "llm_configured": llm_client.is_configured()}


@app.post("/api/studio/parse_transcript")
def studio_parse_transcript(payload: StudioParseTranscriptRequest):
    """Pre-flight the UI calls on paste, before a run is spent — classifies SRT/VTT/plain
    and reports whether real timestamps are available, so tool 6 can be disabled and tool 2
    can warn about estimates before generation runs."""
    parsed = studio_runner.parse_transcript_input(payload.text)
    return {
        "format": parsed["format"],
        "has_timestamps": parsed["has_timestamps"],
        "sentence_count": len(parsed["segments"]),
        "duration_sec": parsed["duration_sec"],
        "word_count": studio_runner.word_count(payload.text),
    }


@app.get("/api/studio/transcript_source/{video_id}")
def studio_transcript_source(video_id: str):
    """Sentence units for the 'pick an indexed video' path on tools 2 and 6 — reuses the
    same sentence extraction ENGINE's analyze step uses, so timestamps are real cue data
    from the library, not a re-parse of anything."""
    if video_id not in store.videos:
        raise HTTPException(status_code=404, detail=f"Video '{video_id}' not found.")
    sentences = _sentences_for_video(video_id)
    return {"video_id": video_id, "sentences": sentences, "sentence_count": len(sentences)}


def _run_studio_tool_job(tool_id: str, inputs: Dict[str, Any], use_voice_profile: bool):
    def _job(report):
        report("generating", 0.3, f"running {tool_id}")
        result = studio_runner.run_tool(tool_id, inputs, use_voice_profile=use_voice_profile)
        report("done", 1.0, "done")
        return result
    return _job


@app.post("/api/studio/run")
def studio_run(payload: StudioRunRequest):
    spec = studio_prompts.get_tool(payload.tool_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{payload.tool_id}'")
    if not llm_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail="No LLM API key configured (VAULT_LLM_API_KEY). STUDIO tools have no "
                   "heuristic fallback for text generation.",
        )
    # Cheap checks (word count, hourly rate limit) run synchronously so the UI gets an
    # immediate, specific error instead of watching a job spin up and fail. Tool-specific
    # structural validation (e.g. tool 6's hard timestamp requirement) happens inside the
    # job and surfaces as job.error — the same pattern ENGINE's MediaUnavailable already
    # uses for _run_analyze_job.
    try:
        usage.check_input_words(spec.count_words(payload.inputs))
        usage.check_rate_limit()
    except usage.InputTooLong as e:
        raise HTTPException(status_code=422, detail=str(e))
    except usage.RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    use_vp = payload.use_voice_profile if payload.use_voice_profile is not None else True
    job_id = jobs.submit(
        f"studio_{payload.tool_id}",
        _run_studio_tool_job(payload.tool_id, payload.inputs, use_vp),
        executor=studio_runner.STUDIO_EXECUTOR,
    )
    return {"job_id": job_id}


@app.post("/api/studio/regenerate")
def studio_regenerate(payload: StudioRegenerateRequest):
    run = tool_runs.get(payload.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{payload.run_id}' not found.")
    if not llm_client.is_configured():
        raise HTTPException(status_code=503, detail="No LLM API key configured (VAULT_LLM_API_KEY).")
    try:
        usage.check_rate_limit()
    except usage.RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    def _job(report):
        report("regenerating", 0.3, f"regenerating '{payload.block}'")
        result = studio_runner.regenerate_block(payload.run_id, payload.block)
        report("done", 1.0, "done")
        return result

    job_id = jobs.submit(f"studio_regenerate_{run.tool_id}", _job, executor=studio_runner.STUDIO_EXECUTOR)
    return {"job_id": job_id}


@app.get("/api/studio/runs")
def studio_list_runs(tool_id: Optional[str] = Query(None), limit: int = Query(50)):
    return [r.to_dict() for r in tool_runs.list_runs(tool_id=tool_id, limit=limit)]


@app.get("/api/studio/runs/{run_id}")
def studio_get_run(run_id: str):
    run = tool_runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return run.to_dict()


@app.delete("/api/studio/runs/{run_id}")
def studio_delete_run(run_id: str):
    if not tool_runs.delete(run_id):
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return {"success": True}


@app.get("/api/studio/voice_profile")
def studio_get_voice_profile():
    return voice_profile.load()


@app.put("/api/studio/voice_profile")
def studio_update_voice_profile(patch: Dict[str, Any]):
    return voice_profile.apply_edit(patch)


@app.post("/api/studio/voice_profile/autoseed")
def studio_autoseed_voice_profile(force: bool = Query(False)):
    chunk_texts = [c.get("text", "") for c in store.chunks]
    try:
        return voice_profile.autoseed(chunk_texts=chunk_texts, force=force)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/studio/platform_rules")
def studio_get_platform_rules():
    return platform_rules.load()


@app.put("/api/studio/platform_rules")
def studio_update_platform_rules(patch: Dict[str, Dict[str, Any]]):
    return platform_rules.apply_edit(patch)


class AgentChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    video_id: Optional[str] = None


@app.post("/api/studio/agent/chat")
def studio_agent_chat(req: AgentChatRequest):
    """
    Studio Copilot endpoint: executes natural language multi-turn agent turns,
    calling Vault, ENGINE, Studio tools, and Voice Profile automatically.
    """
    try:
        res = agent_engine.run_agent_turn(messages=req.messages, store=store, video_id=req.video_id)
        if res.get("usage"):
            usage.record("studio_copilot", res["usage"])
        return res
    except llm_client.LLMUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent copilot error: {str(e)}")


@app.post("/api/studio/agent/chat/stream")
def studio_agent_chat_stream(req: AgentChatRequest):
    """
    Streaming counterpart to /api/studio/agent/chat: emits Server-Sent Events as the agent
    reasons, so the UI shows live tokens and tool activity instead of one blocking wait.
    Each event is `data: {json}\\n\\n` with a "type" field (token/tool_start/tool_result/
    step/usage/done/error) — see agent_engine.run_agent_turn_stream for the exact shapes.
    """
    if not llm_client.is_configured():
        raise HTTPException(status_code=503, detail="VAULT_LLM_API_KEY is not configured in .env.")

    def _event_stream():
        try:
            for event in agent_engine.run_agent_turn_stream(
                messages=req.messages, store=store, video_id=req.video_id
            ):
                if event.get("type") == "usage" and event.get("usage"):
                    usage.record("studio_copilot", event["usage"])
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    # reload=True makes uvicorn spawn its actual worker as a SEPARATE process via
    # multiprocessing's "spawn" start method (CreateProcess on Windows), rather than running
    # in this process. On a venv whose pyvenv.cfg `home` points at the Windows Store Python
    # package (verified live on this box — `python -m venv` was originally run from the Store
    # alias), that spawned worker silently escapes the venv's isolated site-packages and runs
    # against the Store package's own environment instead — even though sys.executable and
    # multiprocessing.set_executable() both correctly report this venv's python.exe, and even
    # though everything else (imports, pip, this top-level process) behaves normally. The
    # practical symptom: packages installed into this venv (e.g. imageio-ffmpeg, yt-dlp)
    # silently don't exist for real requests, while `pip show` / manual scripts say they do.
    # This is a known failure mode of venvs created from the Store Python, not fixable from
    # inside this process — so reload defaults OFF. Opt back in with VAULT_RELOAD=1 if your
    # venv's `home` (see .venv/pyvenv.cfg) is a normal python.org install instead.
    reload_enabled = os.environ.get("VAULT_RELOAD", "0") == "1"
    if not reload_enabled:
        print("[Vault API] Auto-reload disabled by default (see comment above __main__). "
              "Restart the server manually after editing backend code, or set VAULT_RELOAD=1.")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload_enabled)
