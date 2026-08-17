"""
Cuts a clip from source media, reframes it to a platform preset's aspect ratio, overlays
brand-styled captions, and encodes the result — one ffmpeg pass per preset
(ENGINE-PLAN.md Phase 4).

Reframing is a static center crop in v1. An off-centre speaker will be badly framed —
face-tracking crop is explicitly out of scope here and is the highest-value v2 addition;
say so in the UI rather than shipping silent decapitations.
"""
import os
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional

import caption_render
import media_service
import paths

PRESETS: Dict[str, Dict[str, Any]] = {
    "tiktok": {"width": 1080, "height": 1920, "case": "upper", "animation": "pop", "cta_end_cue": False},
    "shorts": {"width": 1080, "height": 1920, "case": "upper", "animation": "pop", "cta_end_cue": True},
    "linkedin": {"width": 1080, "height": 1080, "case": "sentence", "animation": "none", "cta_end_cue": False},
    "x": {"width": 1920, "height": 1080, "case": "none", "animation": "none", "cta_end_cue": False},
}


def _clip_relative_words(words: List[Dict[str, Any]], start_sec: float, end_sec: float) -> List[Dict[str, Any]]:
    out = []
    for w in words:
        if w["end"] <= start_sec or w["start"] >= end_sec:
            continue
        out.append({
            "word": w["word"],
            "start": max(0.0, w["start"] - start_sec),
            "end": max(0.0, w["end"] - start_sec),
        })
    return out


_BEST_ENCODER_FLAGS: Optional[List[str]] = None


def _get_video_encoder_flags() -> List[str]:
    """
    Detect best available H.264 video encoder for FFmpeg.
    Prioritizes NVIDIA NVENC (h264_nvenc) on GPU, falling back to AMD AMF (h264_amf),
    Intel QSV (h264_qsv), or fast CPU libx264 (ultrafast preset).
    """
    global _BEST_ENCODER_FLAGS
    if _BEST_ENCODER_FLAGS is not None:
        return _BEST_ENCODER_FLAGS

    exe = media_service.ffmpeg_exe()
    try:
        res = subprocess.run([exe, "-encoders"], capture_output=True, text=True, timeout=5)
        stdout = res.stdout or ""
        for name, label, flags in _HARDWARE_ENCODERS:
            if name not in stdout:
                continue
            if not _encoder_actually_works(exe, flags):
                print(f"[clip_renderer] {name} is listed but cannot encode on this machine — skipping.")
                continue
            print(f"[clip_renderer] Selected GPU hardware encoder: {name} ({label})")
            _BEST_ENCODER_FLAGS = flags
            return _BEST_ENCODER_FLAGS
    except Exception as e:
        print(f"[clip_renderer] Could not query ffmpeg hardware encoders ({e}), using libx264.")

    print("[clip_renderer] No usable hardware encoder; falling back to libx264 (CPU).")
    _BEST_ENCODER_FLAGS = ["-c:v", "libx264", "-crf", "20", "-preset", "ultrafast"]
    return _BEST_ENCODER_FLAGS


# Tried in order. Each entry is (encoder name as ffmpeg reports it, human label, flags).
_HARDWARE_ENCODERS = [
    ("h264_nvenc", "NVIDIA NVENC", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20"]),
    ("h264_amf", "AMD AMF",
     ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_p", "20", "-qp_i", "20"]),
    ("h264_qsv", "Intel QSV", ["-c:v", "h264_qsv", "-global_quality", "20"]),
]


def _encoder_actually_works(exe: str, flags: List[str]) -> bool:
    """
    Encode one second of test pattern to confirm the encoder RUNS, not merely that ffmpeg
    lists it.

    `ffmpeg -encoders` reports what the BINARY was built with, not what the machine can do —
    and imageio-ffmpeg ships the same build to every install. Proven on the development box:
    h264_nvenc and h264_qsv encode fine there, while h264_amf is listed and fails, on the same
    ffmpeg, at the same moment.

    Selecting on presence alone therefore picked h264_nvenc on every machine, including ones
    with no NVIDIA GPU — where every render then died with "ffmpeg failed (exit N)". Because
    _BEST_ENCODER_FLAGS is cached after the first call, that was unrecoverable for the life of
    the process: not one bad render, but no renders at all, on hardware this local-first tool
    is squarely aimed at.

    Costs one ~1s probe per process, behind the same cache as the selection itself.
    """
    out_path = os.path.join(tempfile.gettempdir(), f"cbrin_encoder_probe_{os.getpid()}.mp4")
    try:
        probe = subprocess.run(
            [exe, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=1",
             *flags, out_path],
            capture_output=True, text=True, timeout=30,
        )
        return probe.returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def _run_ffmpeg(args: List[str]) -> None:
    exe = media_service.ffmpeg_exe()
    result = subprocess.run([exe] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[-2000:]}")


def render_clip(
    clip_id: str,
    source_path: str,
    start_sec: float,
    end_sec: float,
    words: List[Dict[str, Any]],
    brand_kit: Dict[str, Any],
    presets: List[str],
    report: Optional[Callable[[str, float, str], None]] = None,
) -> Dict[str, str]:
    """
    Render `clip_id` for each requested preset. Returns {preset: output_path}. Raises
    ValueError for an unknown preset name before touching ffmpeg or the filesystem.
    """
    unknown = [p for p in presets if p not in PRESETS]
    if unknown:
        raise ValueError(f"Unknown render preset(s): {unknown}. Valid presets: {list(PRESETS.keys())}")

    duration = end_sec - start_sec
    if duration <= 0:
        raise ValueError(f"Invalid clip range: start_sec={start_sec} >= end_sec={end_sec}")

    clip_out_dir = os.path.join(paths.CLIPS_DIR, clip_id)
    os.makedirs(clip_out_dir, exist_ok=True)

    relative_words = _clip_relative_words(words, start_sec, end_sec)

    results: Dict[str, str] = {}
    total = len(presets)
    for i, preset_name in enumerate(presets):
        preset = PRESETS[preset_name]
        if report:
            report("captions", i / total, f"rendering captions for {preset_name}")

        caption_cfg = dict(brand_kit.get("caption", {}))
        caption_cfg["animation"] = preset["animation"]
        kit_for_preset = dict(brand_kit)
        kit_for_preset["caption"] = caption_cfg

        cues = caption_render.build_cues(
            relative_words,
            max_words_per_cue=caption_cfg.get("max_words_per_cue", 4),
            case=preset["case"],
        )

        tmp_png_dir = os.path.join(tempfile.gettempdir(), "vault_engine_captions", f"{clip_id}-{preset_name}")
        caption_render.render_cue_pngs(
            clip_id=f"{clip_id}-{preset_name}",
            cues=cues,
            brand_kit=kit_for_preset,
            size=(preset["width"], preset["height"]),
            duration_sec=duration,
            fps=12,
            out_dir=tmp_png_dir,
        )

        if report:
            report("encoding", (i + 0.5) / total, f"encoding {preset_name}")

        out_path = os.path.join(clip_out_dir, f"{preset_name}.mp4")
        width, height = preset["width"], preset["height"]

        filter_complex = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase:flags=bilinear,"
            f"crop={width}:{height}[v];"
            f"[v][1:v]overlay=format=auto[out]"
        )

        encoder_flags = _get_video_encoder_flags()

        args = [
            "-y",
            "-threads", "0",
            "-ss", str(start_sec), "-to", str(end_sec), "-i", source_path,
            "-framerate", "12", "-i", os.path.join(tmp_png_dir, "cap_%05d.png"),
            "-filter_complex", filter_complex,
            "-map", "[out]", "-map", "0:a?",
            # overlay=format=auto picks its own internal working format when blending the
            # RGBA caption PNGs onto the (yuv420p) source frames — verified live: it upgrades
            # to a wider chroma format (yuv444p / H.264 "High 4:4:4 Predictive" profile), and
            # without an explicit output pixel format libx264 just encodes that as-is. ffmpeg
            # itself decodes it fine, so it looked like a working file in every check that
            # used ffmpeg — but that profile has essentially no support outside ffmpeg-based
            # players: Windows' native player, browsers, and phones all reported it as a
            # corrupt file. Force back to yuv420p, the universally-compatible standard every
            # H.264 "High"-profile player supports.
            "-pix_fmt", "yuv420p",
        ] + encoder_flags + [
            "-c:a", "aac",
            out_path,
        ]

        try:
            _run_ffmpeg(args)
        except Exception:
            if any(h in encoder_flags for h in ["h264_nvenc", "h264_amf", "h264_qsv"]):
                print(f"[clip_renderer] Hardware GPU encoder failed during render for {preset_name}. Retrying with CPU libx264 fallback...")
                fallback_args = [
                    "-y",
                    "-threads", "0",
                    "-ss", str(start_sec), "-to", str(end_sec), "-i", source_path,
                    "-framerate", "12", "-i", os.path.join(tmp_png_dir, "cap_%05d.png"),
                    "-filter_complex", filter_complex,
                    "-map", "[out]", "-map", "0:a?",
                    "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-crf", "20", "-preset", "ultrafast",
                    "-c:a", "aac",
                    out_path,
                ]
                _run_ffmpeg(fallback_args)
            else:
                # Keep the caption PNGs around for diagnosis on failure — only clean up on success.
                raise

        shutil.rmtree(tmp_png_dir, ignore_errors=True)
        results[preset_name] = out_path

        if report:
            report("encoding", (i + 1) / total, f"finished {preset_name}")

    return results
