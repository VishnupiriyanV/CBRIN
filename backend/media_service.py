"""
Guarantees local media bytes exist on disk for a given video_id, regardless of how that
video was ingested.

Local uploads already have their media file written by /api/upload_transcribe
(backend/main.py) at paths.MEDIA_DIR/{video_id}{ext} — ensure_media just finds and returns it.

YouTube-ingested videos have no local media at all: transcript_service.fetch_youtube_transcript
only pulls captions + a shared thumbnail (see IMPROVEMENT-PLAN.md and ENGINE-PLAN.md's "Two
things that must be stated plainly"). ENGINE needs real source frames/audio to render clips,
so this module downloads it via yt-dlp on first use and caches the result.

ffmpeg is resolved via imageio-ffmpeg's bundled static binary — no system install needed, and
verified absent from PATH on this box. That bundle does NOT include ffprobe, so `probe()`
reads dimensions/fps/duration with OpenCV instead (mirrors the approach already used at
multimodal_engine.py's extract_keyframe_and_embed).
"""
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

import paths

MEDIA_EXTS = ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.mp3', '.wav', '.m4a']


class MediaUnavailable(Exception):
    """Raised with a creator-facing, actionable message. API layers should surface this as
    a 422, never a bare 500 — a failed yt-dlp download or a private/region-locked video is
    an expected condition, not a server bug."""


@dataclass
class MediaInfo:
    width: int
    height: int
    fps: float
    duration_sec: float


def _find_existing(video_id: str) -> Optional[str]:
    for ext in MEDIA_EXTS:
        fpath = os.path.join(paths.MEDIA_DIR, f"{video_id}{ext}")
        if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
            return fpath
    return None


_ffmpeg_path: Optional[str] = None
_SHIM_NAME = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def _shim_dir() -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), "vault_ffmpeg_shim")


def ffmpeg_exe() -> str:
    """
    Path to the imageio-ffmpeg-bundled static ffmpeg binary, resolved once and cached.

    imageio-ffmpeg ships its binary under a versioned filename (e.g.
    'ffmpeg-win-x86_64-v7.1.exe'), never plain 'ffmpeg'/'ffmpeg.exe' — verified live:
    prepending its directory to PATH is NOT enough, because openai-whisper's audio loader
    and yt-dlp both shell out to the bare command name "ffmpeg", and shutil.which("ffmpeg")
    (which subprocess/PATH lookup relies on) only matches a file actually named that.
    Whisper failed with WinError 2 on this box even after the directory was on PATH, until
    a stable-named copy existed for that lookup to find.

    Fix: copy the binary once to a fixed-name shim in a stable temp directory, and put THAT
    directory on PATH instead.
    """
    global _ffmpeg_path
    if _ffmpeg_path is None:
        import imageio_ffmpeg
        real_path = imageio_ffmpeg.get_ffmpeg_exe()

        shim_dir = _shim_dir()
        shim_path = os.path.join(shim_dir, _SHIM_NAME)
        if not os.path.exists(shim_path):
            os.makedirs(shim_dir, exist_ok=True)
            import shutil as _shutil
            _shutil.copy2(real_path, shim_path)

        _ffmpeg_path = shim_path
        if shim_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = shim_dir + os.pathsep + os.environ.get("PATH", "")
    return _ffmpeg_path


def ensure_media(video_id: str, youtube_id: Optional[str] = None) -> str:
    """
    Return a filesystem path to playable local media for `video_id`.

    - If media already exists under paths.MEDIA_DIR, returns it immediately (cache hit,
      covers both local uploads and previously-downloaded YouTube videos).
    - If `youtube_id` is given and no local copy exists, downloads it via yt-dlp.
    - Otherwise raises MediaUnavailable.
    """
    os.makedirs(paths.MEDIA_DIR, exist_ok=True)

    existing = _find_existing(video_id)
    if existing:
        return existing

    if not youtube_id:
        raise MediaUnavailable(
            f"No local media file found for '{video_id}' and it has no YouTube source to "
            f"download from. If this was a local upload, the original file may have been "
            f"deleted from the server's data directory."
        )

    return _download_youtube(video_id, youtube_id)


def _download_youtube(video_id: str, youtube_id: str) -> str:
    try:
        import yt_dlp
    except ImportError:
        raise MediaUnavailable(
            "yt-dlp is not installed on the server (see backend/requirements.txt) — cannot "
            "download source media for this YouTube video."
        )

    final_path = os.path.join(paths.MEDIA_DIR, f"{video_id}.mp4")
    # Download to a .part path and atomically rename, so a process kill mid-download can
    # never leave a truncated file that a later call mistakes for a valid cache hit.
    part_path = final_path + ".part"

    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": part_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": os.path.dirname(ffmpeg_exe()),
        "noplaylist": True,
    }

    url = f"https://www.youtube.com/watch?v={youtube_id}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        raise MediaUnavailable(
            f"Could not download source video for '{video_id}' (YouTube ID {youtube_id}): "
            f"{e}. The video may be private, age-restricted, region-locked, or removed — or "
            f"yt-dlp may need an update to handle a recent YouTube change."
        )

    if not os.path.exists(part_path) or os.path.getsize(part_path) == 0:
        raise MediaUnavailable(
            f"yt-dlp reported success but produced no output file for '{video_id}' "
            f"(YouTube ID {youtube_id})."
        )

    os.replace(part_path, final_path)
    return final_path


def probe(path: str) -> MediaInfo:
    """Read width/height/fps/duration via OpenCV — ffprobe is not bundled by imageio-ffmpeg."""
    import cv2

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise MediaUnavailable(f"Could not open media file for probing: {path}")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = frame_count / fps if fps > 0 else 0.0

        return MediaInfo(width=width, height=height, fps=fps, duration_sec=duration_sec)
    finally:
        cap.release()
