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

try:
    import torch
    HAS_TORCH = True
except ImportError:
    torch = None
    HAS_TORCH = False

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

# faster-whisper (CTranslate2) is preferred over openai-whisper when available: same model
# weights, ~4x faster on GPU, native word-level timestamps. Purely additive — if it's not
# installed (or CT2/cuDNN isn't set up right), everything below falls back to openai-whisper
# unchanged, so this never blocks a build that skipped the extra native dependency.
_FasterWhisperModel = None
HAS_FASTER_WHISPER = False

try:
    from faster_whisper import WhisperModel as _FasterWhisperModel
    HAS_FASTER_WHISPER = True
    print("[Vault] faster-whisper available — will be preferred for local transcription.")
except ImportError:
    HAS_FASTER_WHISPER = False
    print("[Vault] 'faster-whisper' is not installed — falling back to openai-whisper for "
          "local transcription. For ~4x faster GPU transcription, "
          "`pip install faster-whisper` (requires CUDA + cuDNN for GPU mode).")

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


def _get_local_whisper_model(model_tier: str, force_cpu: bool = False):
    """Load (or return the cached) local Whisper model for the given tier.
    Prioritizes CUDA GPU execution if available, falling back to CPU on failure."""
    cache_key = f"{model_tier}_cpu" if force_cpu else model_tier
    if cache_key not in _LOCAL_WHISPER_MODELS:
        device = "cpu"
        if not force_cpu and HAS_TORCH and torch is not None and torch.cuda.is_available():
            device = "cuda"

        print(f"[Vault] Loading local Whisper '{model_tier}' model on {device.upper()}...")
        try:
            _LOCAL_WHISPER_MODELS[cache_key] = local_whisper.load_model(model_tier, device=device)
            print(f"[Vault] Local Whisper '{model_tier}' model loaded on {device.upper()} and ready.")
        except Exception as e:
            if device != "cpu":
                print(f"[Vault] Could not load Whisper model on CUDA ({e}). Falling back to CPU...")
                _LOCAL_WHISPER_MODELS[cache_key] = local_whisper.load_model(model_tier, device="cpu")
                print(f"[Vault] Local Whisper '{model_tier}' model loaded on CPU fallback.")
            else:
                raise
    return _LOCAL_WHISPER_MODELS[cache_key]


_FASTER_WHISPER_MODELS: Dict[str, Any] = {}


def _get_faster_whisper_model(model_tier: str, force_cpu: bool = False):
    """Load (or return the cached) faster-whisper model for the given tier. CUDA float16
    first, falling back to CPU int8 on load failure — same tier-cache-key shape as
    _get_local_whisper_model so both engines can be swapped without touching call sites."""
    cache_key = f"{model_tier}_cpu" if force_cpu else model_tier
    if cache_key not in _FASTER_WHISPER_MODELS:
        use_cuda = not force_cpu and HAS_TORCH and torch is not None and torch.cuda.is_available()
        device = "cuda" if use_cuda else "cpu"
        compute_type = "float16" if use_cuda else "int8"

        print(f"[Vault] Loading faster-whisper '{model_tier}' model on {device.upper()} ({compute_type})...")
        try:
            _FASTER_WHISPER_MODELS[cache_key] = _FasterWhisperModel(model_tier, device=device, compute_type=compute_type)
            print(f"[Vault] faster-whisper '{model_tier}' model loaded on {device.upper()} and ready.")
        except Exception as e:
            if device != "cpu":
                print(f"[Vault] Could not load faster-whisper on CUDA ({e}). Falling back to CPU int8...")
                _FASTER_WHISPER_MODELS[cache_key] = _FasterWhisperModel(model_tier, device="cpu", compute_type="int8")
                print(f"[Vault] faster-whisper '{model_tier}' model loaded on CPU fallback.")
            else:
                raise
    return _FASTER_WHISPER_MODELS[cache_key]


def _transcribe_local(file_path: str, model_tier: str, word_timestamps: bool = False) -> Dict[str, Any]:
    """
    Unified local transcription used by both transcribe_file_with_whisper's local-fallback
    path and word_timing.ensure_words. Prefers faster-whisper (CTranslate2 — ~4x faster,
    native GPU fp16, built-in word timestamps); falls back to openai-whisper if
    faster-whisper isn't installed or fails to load/run for any reason. Returns a shape
    that's identical regardless of which engine actually ran:
        {"engine": "faster-whisper"|"openai-whisper",
         "segments": [{"text", "start", "end", "words"?: [{"word","start","end"}]}]}
    """
    if HAS_FASTER_WHISPER:
        try:
            model = _get_faster_whisper_model(model_tier)
            segments_iter, _info = model.transcribe(file_path, word_timestamps=word_timestamps)
            segments = []
            for seg in segments_iter:
                entry: Dict[str, Any] = {
                    "text": (seg.text or "").strip(),
                    "start": float(seg.start),
                    "end": float(seg.end),
                }
                if word_timestamps and seg.words:
                    entry["words"] = [
                        {"word": (w.word or "").strip(), "start": float(w.start), "end": float(w.end)}
                        for w in seg.words if (w.word or "").strip()
                    ]
                segments.append(entry)
            return {"engine": "faster-whisper", "segments": segments}
        except Exception as e:
            print(f"[Vault] faster-whisper transcription failed ({e}). Falling back to openai-whisper...")

    if not HAS_LOCAL_WHISPER or local_whisper is None:
        raise RuntimeError(
            "No local transcription engine available — install faster-whisper or "
            "openai-whisper (see backend/requirements.txt)."
        )

    model = _get_local_whisper_model(model_tier)
    is_cuda = hasattr(model, "device") and model.device.type == "cuda"
    try:
        result = model.transcribe(file_path, word_timestamps=word_timestamps, fp16=is_cuda)
    except Exception as cuda_err:
        if is_cuda:
            print(f"[Vault] CUDA error during Whisper transcription: {cuda_err}. Retrying on CPU fallback...")
            cpu_model = _get_local_whisper_model(model_tier, force_cpu=True)
            result = cpu_model.transcribe(file_path, word_timestamps=word_timestamps, fp16=False)
        else:
            raise

    segments = []
    for seg in result.get('segments', []):
        entry = {
            "text": (seg.get('text') or '').strip(),
            "start": float(seg.get('start', 0.0)),
            "end": float(seg.get('end', 0.0)),
        }
        if word_timestamps:
            entry["words"] = [
                {
                    "word": (w.get('word') or '').strip(),
                    "start": float(w.get('start', 0.0)),
                    "end": float(w.get('end', 0.0)),
                }
                for w in (seg.get('words') or []) if (w.get('word') or '').strip()
            ]
        segments.append(entry)
    return {"engine": "openai-whisper", "segments": segments}


def preload_whisper_model():
    """Preload the default-tier local transcription model into memory on startup. Prefers
    faster-whisper when installed, falls back to openai-whisper. Other tiers load lazily on
    first use. Logs the selected engine + device so it's visible at boot whether GPU
    transcription is actually engaged."""
    tier = _resolve_model_tier(None)
    device_note = "CUDA" if (HAS_TORCH and torch is not None and torch.cuda.is_available()) else "CPU"

    if HAS_FASTER_WHISPER:
        try:
            _get_faster_whisper_model(tier)
            print(f"[Vault] Transcription engine: faster-whisper, preferred device: {device_note}.")
            return
        except Exception as e:
            print(f"[Vault] Could not preload faster-whisper model: {e}. Falling back to openai-whisper preload...")

    global HAS_LOCAL_WHISPER
    if HAS_LOCAL_WHISPER and local_whisper is not None:
        try:
            _get_local_whisper_model(tier)
            print(f"[Vault] Transcription engine: openai-whisper, preferred device: {device_note}.")
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

    # 2. Local transcription fallback (faster-whisper preferred, openai-whisper fallback)
    if HAS_FASTER_WHISPER or HAS_LOCAL_WHISPER:
        try:
            local_result = _transcribe_local(file_path, resolved_tier)

            segments = []
            for seg in local_result["segments"]:
                if seg["text"]:
                    segments.append({
                        "text": seg["text"],
                        "start": seg["start"],
                        "duration": seg["end"] - seg["start"]
                    })

            if not segments:
                # Whisper ran fine but found no speech (silent video, music, visual demo).
                # Create synthetic visual scene segments so non-speech video can still be indexed for visual/image search.
                print(f"[Vault] No speech detected in {file_name}. Generating visual scene segments for image search...")
                duration_sec = 0.0
                try:
                    import media_service
                    info = media_service.probe(file_path)
                    duration_sec = info.duration_sec
                except Exception as probe_err:
                    print(f"[Vault] Media probe error for non-speech file {file_name}: {probe_err}")

                if duration_sec > 0:
                    interval = 15.0
                    curr = 0.0
                    while curr < duration_sec:
                        dur = min(interval, duration_sec - curr)
                        s_min, s_sec = int(curr // 60), int(curr % 60)
                        e_min, e_sec = int((curr + dur) // 60), int((curr + dur) % 60)
                        segments.append({
                            "text": f"[Visual Scene {s_min:02d}:{s_sec:02d} - {e_min:02d}:{e_sec:02d}]",
                            "start": round(curr, 2),
                            "duration": round(dur, 2),
                            "is_visual_only": True
                        })
                        curr += interval
                else:
                    segments.append({
                        "text": "[Visual Scene 00:00 - 00:15]",
                        "start": 0.0,
                        "duration": 15.0,
                        "is_visual_only": True
                    })

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
                "error_message": None,
                "is_non_speech": any(s.get('is_visual_only') for s in segments)
            }
            return {"video_meta": video_meta, "segments": segments}

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Local Whisper transcription failed for {file_name}: {str(e)}")

    raise ValueError(
        f"Transcription failed for '{file_name}'. No local transcription engine (faster-whisper "
        "or openai-whisper) is installed and no OPENAI_API_KEY is set — install requirements "
        "(`pip install -r backend/requirements.txt`) or set OPENAI_API_KEY."
    )
