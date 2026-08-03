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
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}[v];"
            f"[v][1:v]overlay=format=auto[out]"
        )

        args = [
            "-y",
            "-ss", str(start_sec), "-to", str(end_sec), "-i", source_path,
            "-framerate", "12", "-i", os.path.join(tmp_png_dir, "cap_%05d.png"),
            "-filter_complex", filter_complex,
            "-map", "[out]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
            "-c:a", "aac",
            out_path,
        ]

        try:
            _run_ffmpeg(args)
        except Exception:
            # Keep the caption PNGs around for diagnosis on failure — only clean up on success.
            raise

        shutil.rmtree(tmp_png_dir, ignore_errors=True)
        results[preset_name] = out_path

        if report:
            report("encoding", (i + 1) / total, f"finished {preset_name}")

    return results
