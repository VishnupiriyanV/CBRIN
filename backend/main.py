import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from vector_store import VectorStore
from transcript_service import fetch_youtube_transcript

app = FastAPI(
    title="Vault API",
    description="Layer 1 CreatorBrain MVP — Semantic Search for Creator Content Library",
    version="0.1.0"
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

# Seed default chunks on startup
SEED_CHUNKS = [
    {
        "id": "c-101",
        "video_id": "vid-1",
        "video_title": "Overcoming Imposter Syndrome as a Content Creator (My Personal System)",
        "channel": "Creator Craft",
        "youtube_id": "jNQXAC9IVRw",
        "start_sec": 142,
        "end_sec": 187,
        "start_timestamp": "02:22",
        "end_timestamp": "03:07",
        "text": "Whenever I get hit with severe imposter syndrome before filming, I look at my evidence log. The secret is that imposter syndrome isn't a lack of talent—it's a memory loss problem. You literally forget every single piece of value you've ever delivered to your audience. Keeping a dedicated folder of positive emails and comments breaks that cognitive trap instantly.",
        "matched_concepts": ["imposter syndrome", "memory loss problem", "evidence log"],
        "thumbnail_url": "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=600&auto=format&fit=crop&q=80"
    },
    {
        "id": "c-201",
        "video_id": "vid-2",
        "video_title": "How I Recovered from Severe Creator Burnout & Rebuilt My Workflow",
        "channel": "Creator Craft",
        "youtube_id": "L_LUpnjgPso",
        "start_sec": 310,
        "end_sec": 355,
        "start_timestamp": "05:10",
        "end_timestamp": "05:55",
        "text": "Burnout hit me hardest when I separated my creative identity from rest. I was posting 3 videos a week on a relentless treadmill. The breakthrough came when I switched to batch-scripting and batch-recording. By batching research on Mondays and recording on Tuesdays, I freed up 4 days of uninterrupted deep work or rest.",
        "matched_concepts": ["burnout", "batch-recording", "relentless treadmill"],
        "thumbnail_url": "https://images.unsplash.com/photo-1499750310107-5fef28a66643?w=600&auto=format&fit=crop&q=80"
    },
    {
        "id": "c-301",
        "video_id": "vid-3",
        "video_title": "Monetizing a Solo Podcast: Brand Deals vs Digital Products vs Subscriptions",
        "channel": "Creator Craft",
        "youtube_id": "9YfHM8jJ54Y",
        "start_sec": 540,
        "end_sec": 585,
        "start_timestamp": "09:00",
        "end_timestamp": "09:45",
        "text": "Sponsorship deals pay the bills short-term, but owned digital assets build actual long-term equity. A creator with 5,000 hyper-engaged podcast listeners selling a $150 cohort or digital tool can out-earn a channel with 100,000 passive subscribers relying solely on AdSense revenue.",
        "matched_concepts": ["brand deals", "digital products", "monetizing"],
        "thumbnail_url": "https://images.unsplash.com/photo-1557804506-669a67965ba0?w=600&auto=format&fit=crop&q=80"
    },
    {
        "id": "c-401",
        "video_id": "vid-4",
        "video_title": "Mastering YouTube Storytelling: Retention Hooks & Emotional Pacing",
        "channel": "Creator Craft",
        "youtube_id": "v7AYKMP6rOE",
        "start_sec": 95,
        "end_sec": 140,
        "start_timestamp": "01:35",
        "end_timestamp": "02:20",
        "text": "The first 30 seconds of your video determine 80% of your audience retention. Don't waste time saying 'Hey guys welcome back to the channel'. Jump directly into the tension or core problem. Show, don't just explain, why the next 10 minutes matter to their life.",
        "matched_concepts": ["retention hooks", "storytelling", "first 30 seconds"],
        "thumbnail_url": "https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?w=600&auto=format&fit=crop&q=80"
    },
    {
        "id": "c-501",
        "video_id": "vid-5",
        "video_title": "My Complete 2026 Studio Lighting & Audio Setup for Solo Video Essays",
        "channel": "Creator Craft",
        "youtube_id": "f9V024c0C78",
        "start_sec": 215,
        "end_sec": 260,
        "start_timestamp": "03:35",
        "end_timestamp": "04:20",
        "text": "Good audio beats crisp 4K video every single time. Viewers will tolerate mediocre 1080p camera quality, but echoing, harsh audio makes people click away in seconds. Investing $150 in a dynamic broadcast mic and basic acoustic treatment is the highest ROI studio upgrade you can make.",
        "matched_concepts": ["audio setup", "studio lighting", "mic acoustic treatment"],
        "thumbnail_url": "https://images.unsplash.com/photo-1598899134739-24c46f58b8c0?w=600&auto=format&fit=crop&q=80"
    }
]

store.add_chunks(SEED_CHUNKS)

class SearchQuery(BaseModel):
    query: str
    top_k: Optional[int] = 5

class IngestRequest(BaseModel):
    youtube_url: str

@app.get("/")
def read_root():
    return {"status": "ok", "service": "Vault API — CreatorBrain Layer 1"}

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "indexed_chunks": len(store.chunks)}

@app.get("/api/library")
def get_library():
    unique_videos = {}
    for c in store.chunks:
        vid_id = c['video_id']
        if vid_id not in unique_videos:
            unique_videos[vid_id] = {
                "id": vid_id,
                "youtube_id": c.get('youtube_id'),
                "title": c['video_title'],
                "channel": c['channel'],
                "duration_formatted": "18:45",
                "total_seconds": 1125,
                "thumbnail_url": c.get('thumbnail_url', ''),
                "chunk_count": 0,
                "uploaded_at": "2026-07-01",
                "category": "Indexed Content"
            }
        unique_videos[vid_id]["chunk_count"] += 1

    return list(unique_videos.values())

@app.post("/api/search")
def search_vault(payload: SearchQuery):
    if not payload.query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    return store.search(payload.query, top_k=payload.top_k or 5)

@app.post("/api/ingest")
def ingest_media(payload: IngestRequest):
    if not payload.youtube_url:
        raise HTTPException(status_code=400, detail="YouTube URL required")

    try:
        data = fetch_youtube_transcript(payload.youtube_url)
        new_chunks = store.chunk_transcript(data['segments'], data['video_meta'])
        if new_chunks:
            store.add_chunks(new_chunks)
            return {
                "success": True,
                "message": f"Successfully ingested {data['video_meta']['title']} and indexed {len(new_chunks)} chunks.",
                "video": data['video_meta'],
                "new_chunks_count": len(new_chunks)
            }
        else:
            return {
                "success": False,
                "message": "No transcript text could be chunked."
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
