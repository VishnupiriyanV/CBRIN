"""
Captions are Pillow-rendered transparent PNGs, not libass subtitles (ENGINE-PLAN.md Phase 4)
— the bundled imageio-ffmpeg static build's subtitle-filter support isn't guaranteed, and
rendering cues ourselves gives exact control over brand fonts/colors/stroke and per-word
highlighting, which is the point of the feature.

A "cue" is a group of up to `max_words_per_cue` words shown on screen together. Within a
cue, the "active" word (the one currently being spoken) changes over time — each distinct
(cue, active_word) pairing is a "state". render_cue_pngs emits one PNG per output frame tick
(so ffmpeg's image2 sequence demuxer has a file for every tick), but only re-runs Pillow
drawing when the state actually changes, reusing the previous frame's bytes otherwise.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")

_FONT_FILENAMES = {
    "Inter": "Inter-Bold.ttf",
    "Anton": "Anton-Regular.ttf",
    "Archivo Black": "ArchivoBlack-Regular.ttf",
}


@dataclass
class Cue:
    start: float
    end: float
    words: List[Dict[str, Any]] = field(default_factory=list)  # [{text, start, end}]


def build_cues(words: List[Dict[str, Any]], max_words_per_cue: int, case: str = "upper") -> List[Cue]:
    """Group consecutive words into cues of at most `max_words_per_cue`. Case transform
    ('upper'/'sentence'/'none') is applied to the stored word text so render doesn't need
    to know the brand kit's case setting separately."""
    if not words:
        return []

    def _apply_case(text: str) -> str:
        if case == "upper":
            return text.upper()
        return text

    cues: List[Cue] = []
    for i in range(0, len(words), max_words_per_cue):
        group = words[i:i + max_words_per_cue]
        cue_words = [{"text": _apply_case(w["word"]), "start": w["start"], "end": w["end"]} for w in group]
        cues.append(Cue(start=group[0]["start"], end=group[-1]["end"], words=cue_words))
    return cues


_warned_missing_fonts = set()


def _resolve_font(font_name: str, size: int):
    from PIL import ImageFont

    filename = _FONT_FILENAMES.get(font_name)
    if filename:
        path = os.path.join(FONTS_DIR, filename)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
        if font_name not in _warned_missing_fonts:
            _warned_missing_fonts.add(font_name)
            print(f"[caption_render] Font file not found for '{font_name}' at {path} — "
                  f"falling back to Pillow's default bitmap font. See backend/assets/fonts/README.md.")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _active_word_index(cue: Cue, t: float) -> int:
    for i, w in enumerate(cue.words):
        if w["start"] <= t < w["end"]:
            return i
    # Between words or past the last word's end but still within the cue span: hold on the
    # nearest word rather than rendering nothing.
    if t < cue.words[0]["start"]:
        return 0
    return len(cue.words) - 1


def _find_active_cue(cues: List[Cue], t: float) -> Optional[Tuple[int, Cue]]:
    for i, cue in enumerate(cues):
        if cue.start <= t <= cue.end:
            return i, cue
    return None


def _draw_frame(cue: Cue, active_idx: int, size: Tuple[int, int], brand_kit: Dict[str, Any]):
    from PIL import Image, ImageDraw

    width, height = size
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    colors = brand_kit.get("colors", {})
    text_color = colors.get("text", "#ffffff")
    accent_color = colors.get("accent", "#ff7a17")
    stroke_color = colors.get("stroke", "#000000")

    caption_cfg = brand_kit.get("caption", {})
    position = caption_cfg.get("position", "bottom-center")
    margins = brand_kit.get("safe_margins", {"top": 0.12, "bottom": 0.18})

    font_size = max(18, int(height * 0.045))
    font = _resolve_font(brand_kit.get("fonts", {}).get("caption", "Inter"), font_size)

    line = " ".join(w["text"] for w in cue.words)
    bbox = draw.textbbox((0, 0), line, font=font, stroke_width=2)
    text_w = bbox[2] - bbox[0]

    x = max(0, (width - text_w) // 2)
    if position == "bottom-center":
        y = int(height * (1 - margins.get("bottom", 0.18)))
    elif position == "top-center":
        y = int(height * margins.get("top", 0.12))
    else:
        y = int(height * 0.5)

    cursor_x = x
    for i, w in enumerate(cue.words):
        color = accent_color if i == active_idx else text_color
        draw.text((cursor_x, y), w["text"], font=font, fill=color, stroke_width=2, stroke_fill=stroke_color)
        word_bbox = draw.textbbox((cursor_x, y), w["text"] + " ", font=font)
        cursor_x = word_bbox[2]

    return img


def render_cue_pngs(clip_id: str, cues: List[Cue], brand_kit: Dict[str, Any], size: Tuple[int, int],
                     duration_sec: float, fps: int = 12, out_dir: Optional[str] = None) -> str:
    """
    Render one PNG per output frame tick into out_dir (default: system tmp/{clip_id}/),
    reusing the previous frame's bytes whenever the (cue, active_word) state hasn't changed.
    Returns the directory path.
    """
    import tempfile

    if out_dir is None:
        out_dir = os.path.join(tempfile.gettempdir(), "vault_engine_captions", clip_id)
    os.makedirs(out_dir, exist_ok=True)

    total_frames = max(1, int(duration_sec * fps))
    # Sentinel distinct from any real state_key (which is None when no cue is active, or a
    # (cue_idx, word_idx) tuple otherwise) — using None as the initial "not yet rendered"
    # marker collided with the legitimate "no active cue" state on a clip with zero cues
    # (e.g. no detected speech), so the first frame never rendered and last_bytes stayed
    # None, crashing the PNG write below. Verified live via an end-to-end render test.
    _UNRENDERED = object()
    last_state_key: Any = _UNRENDERED
    last_bytes: Optional[bytes] = None

    import io

    for frame_idx in range(total_frames):
        t = frame_idx / fps
        active = _find_active_cue(cues, t)

        if active is None:
            state_key = None
        else:
            cue_idx, cue = active
            word_idx = _active_word_index(cue, t)
            state_key = (cue_idx, word_idx)

        if state_key != last_state_key:
            if active is None:
                from PIL import Image
                img = Image.new("RGBA", size, (0, 0, 0, 0))
            else:
                cue_idx, cue = active
                word_idx = state_key[1]
                img = _draw_frame(cue, word_idx, size, brand_kit)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            last_bytes = buf.getvalue()
            last_state_key = state_key

        frame_path = os.path.join(out_dir, f"cap_{frame_idx:05d}.png")
        with open(frame_path, 'wb') as f:
            f.write(last_bytes)

    return out_dir
