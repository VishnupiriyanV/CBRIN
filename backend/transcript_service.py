import os
import re
import math
import urllib.request
import json
import hashlib
from typing import List, Dict, Any, Optional
from youtube_transcript_api import YouTubeTranscriptApi

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

local_whisper = None
HAS_LOCAL_WHISPER = False

try:
    import whisper as lw
    local_whisper = lw
    HAS_LOCAL_WHISPER = True
    print("[Vault] Local Whisper module available.")
except ImportError:
    HAS_LOCAL_WHISPER = False
    print("[Vault] 'openai-whisper' is not installed. Local (offline) transcription is "
          "unavailable — install it with `pip install -r backend/requirements.txt`, or set "
          "OPENAI_API_KEY to use the hosted Whisper API instead.")

# 'base' mangles proper nouns and technical vocabulary — exactly the high-value search terms
# (PRD §7.2, IMPROVEMENT-PLAN.md 3.4) — so the default tier is 'small'. Still overridable via
# env, and selectable per-upload (see WHISPER_MODEL_TIERS / transcribe_file_with_whisper's
# model_tier param).
WHISPER_MODEL_SIZE = os.getenv("VAULT_WHISPER_MODEL", "small")
WHISPER_MODEL_TIERS = ("base", "small", "medium")

# One loaded model per tier, cached lazily — a user picking 'medium' for one upload shouldn't
# force every other tier to reload from scratch on next use.
_LOCAL_WHISPER_MODELS: Dict[str, Any] = {}


def _resolve_model_tier(model_tier: Any = None) -> str:
    """Fall back to the configured default for anything not in WHISPER_MODEL_TIERS, rather
    than letting a bad/empty value reach whisper.load_model() as an opaque failure."""
    if model_tier in WHISPER_MODEL_TIERS:
        return model_tier
    return WHISPER_MODEL_SIZE if WHISPER_MODEL_SIZE in WHISPER_MODEL_TIERS else "small"


def _get_local_whisper_model(model_tier: str):
    """Load (or return the cached) local Whisper model for the given tier."""
    if model_tier not in _LOCAL_WHISPER_MODELS:
        print(f"[Vault] Loading local Whisper '{model_tier}' model...")
        _LOCAL_WHISPER_MODELS[model_tier] = local_whisper.load_model(model_tier)
        print(f"[Vault] Local Whisper '{model_tier}' model loaded and ready.")
    return _LOCAL_WHISPER_MODELS[model_tier]


def preload_whisper_model():
    """Preload the default-tier local Whisper model into memory on startup, if the package
    is installed. Other tiers load lazily on first use (see _get_local_whisper_model)."""
    global HAS_LOCAL_WHISPER
    if HAS_LOCAL_WHISPER and local_whisper is not None:
        try:
            _get_local_whisper_model(_resolve_model_tier(None))
        except Exception as e:
            print(f"[Vault] Could not preload local Whisper model: {e}")


def content_hash_id(file_path: str) -> str:
    """Content-addressed, stable ID for a local file — same bytes always yield the same ID,
    independent of Python's per-process string hash randomization."""
    sha1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            sha1.update(block)
    return f"local-{sha1.hexdigest()[:12]}"


def get_youtube_video_id(url_or_id: str) -> str:
    """Extract YouTube video ID from URL or validate raw ID."""
    pattern = r"(?:v=|\/|youtu\.be\/)([a-zA-Z0-9_-]{11})"
    match = re.search(pattern, url_or_id)
    if match:
        return match.group(1)
    if len(url_or_id) == 11 and re.match(r'^[a-zA-Z0-9_-]+$', url_or_id):
        return url_or_id
    raise ValueError(f"Invalid YouTube URL or Video ID: '{url_or_id}'")


def fetch_youtube_metadata(video_id: str) -> Dict[str, str]:
    """Fetch real YouTube video title, channel, and thumbnail via oEmbed API."""
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                return {
                    "title": data.get("title", f"YouTube Video ({video_id})"),
                    "channel": data.get("author_name", "YouTube Creator"),
                    "thumbnail_url": data.get("thumbnail_url", f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg")
                }
    except Exception as e:
        print(f"[Vault] Could not fetch oEmbed metadata for {video_id}: {e}")

    return {
        "title": f"YouTube Video ({video_id})",
        "channel": "YouTube Media",
        "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    }


def fetch_youtube_transcript(youtube_url: str) -> Dict[str, Any]:
    """
    Fetch real transcript from YouTube using youtube-transcript-api.
    Raises explicit error if transcript is unavailable — no fake/mock fallback.
    """
    video_id = get_youtube_video_id(youtube_url)
    meta = fetch_youtube_metadata(video_id)

    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, 'fetch'):
            transcript = api.fetch(video_id)
        elif hasattr(YouTubeTranscriptApi, 'get_transcript'):
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        else:
            transcript = api.list(video_id).find_transcript(['en', 'en-US', 'en-GB']).fetch()

        segments = []
        for item in transcript:
            if isinstance(item, dict):
                text = item.get('text', '')
                start = item.get('start', 0.0)
                duration = item.get('duration', 0.0)
            else:
                text = getattr(item, 'text', '')
                start = getattr(item, 'start', 0.0)
                duration = getattr(item, 'duration', 0.0)

            clean_text = text.replace('\n', ' ').strip()
            if clean_text:
                segments.append({
                    "text": clean_text,
                    "start": float(start),
                    "duration": float(duration)
                })

        if not segments:
            raise ValueError(f"Transcript for video {video_id} is empty or unreadable.")

        last_seg = segments[-1]
        total_duration = last_seg['start'] + last_seg['duration']
        total_seconds = int(total_duration)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        duration_formatted = f"{hours}:{minutes:02d}:{secs:02d}" if hours > 0 else f"{minutes:02d}:{secs:02d}"

        video_meta = {
            "id": f"yt-{video_id}",
            "youtube_id": video_id,
            "title": meta["title"],
            "channel": meta["channel"],
            "thumbnail_url": meta["thumbnail_url"],
            "total_seconds": total_seconds,
            "duration_formatted": duration_formatted,
            "uploaded_at": __import__('datetime').datetime.now().isoformat(),
            "category": "YouTube",
            "status": "fully_indexed",
            "error_message": None
        }

        return {
            "video_meta": video_meta,
            "segments": segments
        }
    except Exception as e:
        raise ValueError(f"Failed to fetch transcript for YouTube video '{meta['title']}': {str(e)}")


def transcribe_file_with_whisper(file_path: str, file_name: str, model_tier: Optional[str] = None) -> Dict[str, Any]:
    """
    Transcribes audio/video files using:
    1. OpenAI Whisper API (if OPENAI_API_KEY is set) — always uses OpenAI's hosted model;
       `model_tier` only applies to the local fallback below, since the API isn't sized the
       same way.
    2. Local Whisper model, loaded (or reused from cache) at `model_tier`
       ('base' / 'small' / 'medium', default 'small' — see WHISPER_MODEL_TIERS).
    Raises explicit error if transcription fails.
    """
    resolved_tier = _resolve_model_tier(model_tier)
    api_key = os.getenv("OPENAI_API_KEY")
    clean_title = os.path.splitext(file_name)[0].replace("-", " ").replace("_", " ").title()

    # 1. Try OpenAI Whisper API first if API key is present
    if api_key and HAS_OPENAI:
        try:
            client = openai.OpenAI(api_key=api_key)
            with open(file_path, "rb") as audio_file:
                transcript_obj = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json"
                )

            segments = []
            for seg in getattr(transcript_obj, 'segments', []):
                text = seg.get('text', '').strip() if isinstance(seg, dict) else getattr(seg, 'text', '').strip()
                start = seg.get('start', 0.0) if isinstance(seg, dict) else getattr(seg, 'start', 0.0)
                end = seg.get('end', 0.0) if isinstance(seg, dict) else getattr(seg, 'end', 0.0)
                if text:
                    segments.append({
                        "text": text,
                        "start": float(start),
                        "duration": float(end - start)
                    })

            if segments:
                total_seconds = int(segments[-1]['start'] + segments[-1]['duration'])
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                secs = total_seconds % 60
                duration_formatted = f"{hours}:{minutes:02d}:{secs:02d}" if hours > 0 else f"{minutes:02d}:{secs:02d}"

                video_meta = {
                    "id": content_hash_id(file_path),
                    "title": clean_title,
                    "channel": "Local Media",
                    "is_local": True,
                    "total_seconds": total_seconds,
                    "duration_formatted": duration_formatted,
                    "thumbnail_url": "",
                    "uploaded_at": __import__('datetime').datetime.now().isoformat(),
                    "category": "Local Upload",
                    "status": "fully_indexed",
                    "error_message": None
                }
                return {"video_meta": video_meta, "segments": segments}

        except Exception as e:
            print(f"[Vault] Whisper API error for {file_name}: {e}. Falling back to local Whisper...")

    # 2. Local Whisper model fallback
    if HAS_LOCAL_WHISPER:
        try:
            model = _get_local_whisper_model(resolved_tier)
            result = model.transcribe(file_path)

            segments = []
            for seg in result.get('segments', []):
                text = seg.get('text', '').strip()
                if text:
                    segments.append({
                        "text": text,
                        "start": float(seg.get('start', 0.0)),
                        "duration": float(seg.get('end', 0.0) - seg.get('start', 0.0))
                    })

            if segments:
                total_seconds = int(segments[-1]['start'] + segments[-1]['duration'])
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                secs = total_seconds % 60
                duration_formatted = f"{hours}:{minutes:02d}:{secs:02d}" if hours > 0 else f"{minutes:02d}:{secs:02d}"

                video_meta = {
                    "id": content_hash_id(file_path),
                    "title": clean_title,
                    "channel": "Local Media",
                    "is_local": True,
                    "total_seconds": total_seconds,
                    "duration_formatted": duration_formatted,
                    "thumbnail_url": "",
                    "uploaded_at": __import__('datetime').datetime.now().isoformat(),
                    "category": "Local Upload",
                    "status": "fully_indexed",
                    "error_message": None
                }
                return {"video_meta": video_meta, "segments": segments}

            # Whisper ran fine but found no recognizable speech (silence, music-only, a tone/
            # test file). Falling through to the "openai-whisper is not installed" message
            # below would be actively wrong here — it IS installed and just ran — so raise a
            # specific error instead of misdiagnosing a working install as a missing one.
            raise ValueError(f"No speech was detected in '{file_name}'.")

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Local Whisper transcription failed for {file_name}: {str(e)}")

    raise ValueError(
        f"Transcription failed for '{file_name}'. Local 'openai-whisper' is not installed and "
        "no OPENAI_API_KEY is set — install requirements (`pip install -r backend/requirements.txt`) "
        "or set OPENAI_API_KEY."
    )
