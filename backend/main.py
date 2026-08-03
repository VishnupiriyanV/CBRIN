import uvicorn
import shutil
import tempfile
import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import io

from vector_store import VectorStore, MEDIA_DIR
from transcript_service import fetch_youtube_transcript, transcribe_file_with_whisper, fetch_youtube_metadata, preload_whisper_model
from multimodal_engine import preload_models, KEYFRAMES_DIR

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-load all machine learning models into memory on server startup."""
    print("[Vault API] Server starting up. Preloading models...")
    try:
        preload_models()
    except Exception as e:
        print(f"[Vault API] Error preloading text/CLIP models: {e}")

    try:
        preload_whisper_model()
    except Exception as e:
        print(f"[Vault API] Error preloading Whisper model: {e}")

    print("[Vault API] Model preloading completed. Server ready on http://localhost:8000.")
    yield
    print("[Vault API] Server shutting down.")

app = FastAPI(
    title="Vault API",
    description="CreatorBrain Layer 1 MVP — Multimodal Semantic Search for Creator Content",
    version="0.4.0",
    lifespan=lifespan
)

# Enable CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize vector store
store = VectorStore()


class SearchQuery(BaseModel):
    query: str
    top_k: Optional[int] = 5
    search_mode: Optional[str] = "hybrid"  # hybrid, questions, topics, visual_scenes


class IngestRequest(BaseModel):
    youtube_url: str


class HighlightRequest(BaseModel):
    chunk_id: str
    note: Optional[str] = ""


class ImportRequest(BaseModel):
    mode: Optional[str] = "merge"  # merge or replace


@app.get("/")
def read_root():
    stats = store.get_stats()
    return {
        "status": "ok",
        "service": "Vault API — CreatorBrain Layer 1",
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
        visual_count = sum(1 for c in store.chunks if c.get('video_id') == vid_id and c.get('has_visual_embedding', False))
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
        fpath = os.path.join(MEDIA_DIR, f"{video_id}{ext}")
        if os.path.exists(fpath):
            return FileResponse(fpath)

    raise HTTPException(status_code=404, detail="Media file not found for local video.")


@app.get("/api/keyframe/{chunk_id}")
def get_keyframe(chunk_id: str):
    """Serve a keyframe thumbnail JPEG for a specific chunk."""
    keyframe_path = os.path.join(KEYFRAMES_DIR, f"{chunk_id}.jpg")
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
            "execution_time_ms": 0,
            "total_chunks_scanned": 0,
            "library_video_count": 0,
            "search_mode": payload.search_mode or "hybrid",
            "message": "No content indexed yet. Ingest videos or audio files to start searching."
        }

    return store.search(
        query=payload.query,
        top_k=payload.top_k or 5,
        search_mode=payload.search_mode or "hybrid"
    )


@app.post("/api/ingest")
def ingest_youtube(payload: IngestRequest):
    """Ingest YouTube video via transcript API + oEmbed metadata."""
    if not payload.youtube_url or not payload.youtube_url.strip():
        raise HTTPException(status_code=400, detail="YouTube URL required")

    try:
        data = fetch_youtube_transcript(payload.youtube_url)
        video_meta = data['video_meta']
        segments = data['segments']

        existing_ids = {c['video_id'] for c in store.chunks}
        if video_meta['id'] in existing_ids:
            return {
                "success": False,
                "message": f"Video '{video_meta['title']}' is already indexed.",
                "video": video_meta,
                "new_chunks_count": 0
            }

        new_chunks = store.chunk_transcript(segments, video_meta)

        if new_chunks:
            store.add_video(video_meta)
            store.add_chunks(new_chunks)
            return {
                "success": True,
                "message": f"Indexed '{video_meta['title']}' — {len(new_chunks)} transcript chunks embedded.",
                "video": video_meta,
                "new_chunks_count": len(new_chunks)
            }
        else:
            raise ValueError("Transcript was fetched but contained no meaningful speech text.")

    except ValueError as e:
        yt_id = payload.youtube_url
        meta = fetch_youtube_metadata(yt_id)
        vid_id = f"yt-{meta['title']}"
        store.add_failed_video(
            video_id=vid_id,
            title=meta['title'],
            channel=meta['channel'],
            error_msg=str(e),
            is_local=False,
            youtube_id=None
        )
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.post("/api/upload_transcribe")
async def upload_and_transcribe_file(file: UploadFile = File(...)):
    """Upload local audio/video file, transcribe with Whisper, chunk, embed, and store media file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    file_ext = os.path.splitext(file.filename)[1].lower()
    temp_dir = tempfile.gettempdir()
    safe_filename = file.filename.replace(" ", "_")
    temp_file_path = os.path.join(temp_dir, safe_filename)

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        data = transcribe_file_with_whisper(temp_file_path, file.filename)
        video_meta = data['video_meta']
        segments = data['segments']

        persistent_media_path = os.path.join(MEDIA_DIR, f"{video_meta['id']}{file_ext}")
        shutil.copyfile(temp_file_path, persistent_media_path)

        new_chunks = store.chunk_transcript(segments, video_meta, media_path=persistent_media_path)

        if new_chunks:
            store.add_video(video_meta)
            store.add_chunks(new_chunks)

        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        return {
            "success": True,
            "message": f"Transcribed '{file.filename}' — {len(new_chunks)} chunks indexed.",
            "video": video_meta,
            "new_chunks_count": len(new_chunks)
        }
    except ValueError as e:
        vid_id = f"local-{abs(hash(file.filename)) % 100000}"
        clean_title = os.path.splitext(file.filename)[0].replace("-", " ").replace("_", " ").title()
        store.add_failed_video(
            video_id=vid_id,
            title=clean_title,
            channel="Local Upload",
            error_msg=str(e),
            is_local=True
        )
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=500, detail=f"Upload & transcription failed: {str(e)}")


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
            headers={"Content-Disposition": "attachment; filename=vault_library_export.zip"}
        )
    else:
        data = store.export_library_json()
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        return Response(
            content=json_str,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=vault_library_export.json"}
        )


@app.get("/api/export/search")
def export_search_results(
    query: str = Query(..., description="Search query"),
    mode: str = Query("hybrid", description="Search mode"),
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
            headers={"Content-Disposition": f"attachment; filename=vault_search_{query[:30].replace(' ', '_')}.csv"}
        )
    else:
        json_str = json.dumps(search_result, indent=2, ensure_ascii=False)
        return Response(
            content=json_str,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=vault_search_{query[:30].replace(' ', '_')}.json"}
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


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
