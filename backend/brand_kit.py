"""
Brand Kit: auto-seeded from the creator's own frames, then handed to the creator to confirm
or edit (ENGINE-PLAN.md Phase 3 — the "auto-seeded, not auto-decided" design decision).

Palette is k-means over pixels sampled from existing keyframes in paths.KEYFRAMES_DIR.
Rhythm (avg shot length, words per minute) comes from OpenCV scene-cut detection and word
timing. Fonts are NOT auto-detected — a wrong typeface guess from burned-in captions is
worse than asking, so three bundled open-licence fonts are offered instead (see
backend/assets/fonts/README.md for what must be dropped in before rendering will work).
"""
import copy
import json
import os
import random
import re
from typing import Any, Dict, List, Optional

import numpy as np

import atomic_io
import paths

DEFAULT_BRAND_KIT: Dict[str, Any] = {
    "fonts": {"caption": "Anton", "display": "Inter"},
    "colors": {"primary": "#0a0a0a", "accent": "#ff7a17", "text": "#ffffff", "stroke": "#000000"},
    "caption": {
        "position": "bottom-center",
        "case": "upper",
        "size": "medium",
        "max_words_per_cue": 4,
        "highlight_style": "active-word-accent",
        "animation": "pop",
    },
    "rhythm": {"avg_shot_sec": 2.4, "wpm": 168},
    "safe_margins": {"top": 0.12, "bottom": 0.18},
    "auto_seeded": True,
}

MAX_SAMPLE_FRAMES = 40
KMEANS_CLUSTERS = 5
KMEANS_RANDOM_STATE = 42  # pinned for deterministic auto-seeding (test_brand_kit.py depends on it)


def load() -> Dict[str, Any]:
    """
    The persisted kit merged over the defaults.

    DEEP copies the defaults. `dict(DEFAULT_BRAND_KIT)` is shallow, so every nested dict
    ("colors", "caption", "safe_margins", ...) came back as the SAME OBJECT held by the
    module constant — and apply_edit's `current[key].update(value)` then mutated that
    constant in place, for the lifetime of the process. Demonstrated: one edit setting
    safe_margins.bottom left DEFAULT_BRAND_KIT["safe_margins"]["bottom"] permanently changed,
    and it happened even when validate() rejected the edit and nothing was written to disk.
    Every later load() on a machine with no brand_kit.json then returned the corrupted values.
    """
    if not os.path.exists(paths.BRAND_KIT_FILE):
        return copy.deepcopy(DEFAULT_BRAND_KIT)
    try:
        with open(paths.BRAND_KIT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        merged = copy.deepcopy(DEFAULT_BRAND_KIT)
        merged.update(data)
        return merged
    except Exception:
        return copy.deepcopy(DEFAULT_BRAND_KIT)


def save(kit: Dict[str, Any]) -> Dict[str, Any]:
    # Atomic — user-authored brand configuration. load() above falls back to DEFAULT_BRAND_KIT
    # on any parse error, so a truncated write silently reverts the creator's colours, fonts
    # and logo to stock with no error shown.
    atomic_io.write_json(paths.BRAND_KIT_FILE, kit)
    return kit


_HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# A margin is a fraction of the frame. Past this the caption is pushed off-screen; at 0.5 the
# top and bottom margins meet and there is nowhere left to draw.
MAX_SAFE_MARGIN = 0.45

# One cue is a single burned-in caption line. caption_render shrinks the font to fit, but only
# 8 steps down to 14px, so a very long cue eventually overflows the frame regardless.
MAX_WORDS_PER_CUE = 10


def validate(kit: Dict[str, Any]) -> None:
    """
    Raise ValueError on anything caption_render cannot survive.

    PUT /api/engine/brand_kit takes an untyped dict and persisted it as-is, so values that
    look fine at write time blew up much later inside a background render job — with a raw
    Python TypeError in the job's error field and no hint which field caused it. Verified
    against the real renderer: `safe_margins.bottom = "abc"` raises TypeError on the
    `1 - margin` arithmetic, and `colors.text = "not-a-colour"` raises ValueError inside
    Pillow. `safe_margins.bottom = 5.0` does not raise at all — it silently positions every
    caption off-frame, which is worse, because the render "succeeds".

    Only the fields with no safe fallback are checked, audited against every brand-kit read in
    caption_render/clip_renderer: `caption.size` resolves through a lookup default,
    `caption.position` falls through to centre, `fonts.*` falls back to a bundled face, and
    `caption.animation`/`highlight_style` are not read at all. Those stay permissive on
    purpose — a bad value degrades rather than breaks.

    `caption.max_words_per_cue` is the exception: build_cues() feeds it straight to range() as
    the step, with no fallback. 0 raises ValueError, a float or string raises TypeError, and a
    negative value produces zero cues — a render that "succeeds" with no captions at all.
    """
    colors = kit.get("colors")
    if colors is not None:
        if not isinstance(colors, dict):
            raise ValueError("colors must be an object")
        for name, value in colors.items():
            if not isinstance(value, str) or not _HEX_COLOUR.match(value):
                raise ValueError(
                    f"colors.{name} must be a hex colour like '#ffffff', got {value!r}"
                )

    caption = kit.get("caption")
    if caption is not None:
        if not isinstance(caption, dict):
            raise ValueError("caption must be an object")
        words_per_cue = caption.get("max_words_per_cue")
        if words_per_cue is not None:
            if isinstance(words_per_cue, bool) or not isinstance(words_per_cue, int):
                raise ValueError(
                    f"caption.max_words_per_cue must be a whole number between 1 and "
                    f"{MAX_WORDS_PER_CUE}, got {words_per_cue!r}"
                )
            if not (1 <= words_per_cue <= MAX_WORDS_PER_CUE):
                raise ValueError(
                    f"caption.max_words_per_cue must be between 1 and {MAX_WORDS_PER_CUE}, "
                    f"got {words_per_cue}"
                )

    margins = kit.get("safe_margins")
    if margins is not None:
        if not isinstance(margins, dict):
            raise ValueError("safe_margins must be an object")
        for edge, value in margins.items():
            # bool is an int subclass and would sail through the numeric check.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"safe_margins.{edge} must be a number between 0 and {MAX_SAFE_MARGIN}, "
                    f"got {value!r}"
                )
            if not (0.0 <= float(value) <= MAX_SAFE_MARGIN):
                raise ValueError(
                    f"safe_margins.{edge} must be between 0 and {MAX_SAFE_MARGIN} "
                    f"(a fraction of the frame), got {value}"
                )


def apply_edit(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a partial update into the persisted kit. Any edit flips auto_seeded to False so
    a later autoseed() call never silently overwrites a creator's deliberate choice.

    Validated on the MERGED result rather than the patch, so a partial edit cannot combine
    with stored values into something the renderer rejects.
    """
    current = load()
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            current[key].update(value)
        else:
            current[key] = value
    current["auto_seeded"] = False
    validate(current)
    return save(current)


def _rgb_to_hex(rgb) -> str:
    r, g, b = [max(0, min(255, int(round(c)))) for c in rgb]
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb_saturation(rgb) -> float:
    r, g, b = [c / 255.0 for c in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


def _is_neutral(rgb, threshold: float = 0.15) -> bool:
    return _rgb_saturation(rgb) < threshold


def _sample_pixels_from_keyframes(max_frames: int = MAX_SAMPLE_FRAMES) -> Optional[np.ndarray]:
    from PIL import Image

    if not os.path.isdir(paths.KEYFRAMES_DIR):
        return None
    files = sorted(f for f in os.listdir(paths.KEYFRAMES_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png')))
    if not files:
        return None

    # Deterministic sample: evenly spaced through the sorted file list rather than random,
    # so autoseed() is reproducible for a fixed frame set (test_brand_kit.py depends on this).
    if len(files) > max_frames:
        step = len(files) / max_frames
        files = [files[int(i * step)] for i in range(max_frames)]

    all_pixels = []
    for fname in files:
        try:
            img = Image.open(os.path.join(paths.KEYFRAMES_DIR, fname)).convert("RGB")
            img = img.resize((16, 16))  # cheap downsample — palette doesn't need full res
            pixels = np.array(img).reshape(-1, 3)
            all_pixels.append(pixels)
        except Exception:
            continue

    if not all_pixels:
        return None
    return np.vstack(all_pixels)


def _detect_rhythm() -> Dict[str, float]:
    """Mean shot length via OpenCV frame-difference scene detection over the first local
    media file found. Falls back to the default rhythm if no local media / OpenCV frame
    diffs yield no scene cuts."""
    import cv2

    if not os.path.isdir(paths.MEDIA_DIR):
        return dict(DEFAULT_BRAND_KIT["rhythm"])

    media_files = [
        f for f in os.listdir(paths.MEDIA_DIR)
        if os.path.splitext(f)[1].lower() in ('.mp4', '.mov', '.webm', '.mkv', '.avi')
    ]
    if not media_files:
        return dict(DEFAULT_BRAND_KIT["rhythm"])

    path = os.path.join(paths.MEDIA_DIR, media_files[0])
    cap = cv2.VideoCapture(path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        prev_gray = None
        cut_frames = []
        frame_idx = 0
        sample_stride = max(1, int(fps // 2))  # sample twice per second, cheap enough

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % sample_stride == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (64, 36))
                if prev_gray is not None:
                    diff = float(np.mean(np.abs(gray.astype(int) - prev_gray.astype(int))))
                    if diff > 30.0:  # empirical scene-cut threshold on 0-255 grayscale diff
                        cut_frames.append(frame_idx)
                prev_gray = gray
            frame_idx += 1

        if len(cut_frames) < 2:
            return dict(DEFAULT_BRAND_KIT["rhythm"])

        gaps_sec = [(cut_frames[i + 1] - cut_frames[i]) / fps for i in range(len(cut_frames) - 1)]
        avg_shot_sec = round(sum(gaps_sec) / len(gaps_sec), 2)
        return {"avg_shot_sec": avg_shot_sec, "wpm": DEFAULT_BRAND_KIT["rhythm"]["wpm"]}
    finally:
        cap.release()


def autoseed(force: bool = False) -> Dict[str, Any]:
    """
    Auto-seed palette + rhythm from the creator's own keyframes/media. Refuses to overwrite
    an already-edited kit unless force=True (ENGINE-PLAN.md: "auto_seeded flips to false on
    first edit so re-seeding never silently overwrites the creator's choices").
    """
    current = load()
    if not current.get("auto_seeded", True) and not force:
        raise ValueError(
            "Brand kit has been manually edited — re-seeding would overwrite those choices. "
            "Pass force=True to overwrite anyway."
        )

    pixels = _sample_pixels_from_keyframes()
    colors = dict(DEFAULT_BRAND_KIT["colors"])

    if pixels is not None and len(pixels) >= KMEANS_CLUSTERS:
        from sklearn.cluster import KMeans

        km = KMeans(n_clusters=KMEANS_CLUSTERS, random_state=KMEANS_RANDOM_STATE, n_init=10)
        km.fit(pixels)
        centers = km.cluster_centers_
        counts = np.bincount(km.labels_, minlength=KMEANS_CLUSTERS)

        # Sort clusters by population, most common first — the dominant color anchors
        # "primary"; the most saturated non-neutral cluster becomes "accent".
        order = np.argsort(-counts)
        sorted_centers = [centers[i] for i in order]

        primary = sorted_centers[0]
        accent_candidates = [c for c in sorted_centers if not _is_neutral(c)]
        accent = max(accent_candidates, key=_rgb_saturation) if accent_candidates else sorted_centers[-1]

        # Text/stroke: whichever of black/white contrasts more against primary's luminance.
        luminance = 0.299 * primary[0] + 0.587 * primary[1] + 0.114 * primary[2]
        text_color = "#ffffff" if luminance < 140 else "#0a0a0a"
        stroke_color = "#000000" if text_color == "#ffffff" else "#ffffff"

        colors = {
            "primary": _rgb_to_hex(primary),
            "accent": _rgb_to_hex(accent),
            "text": text_color,
            "stroke": stroke_color,
        }

    rhythm = _detect_rhythm()

    new_kit = dict(DEFAULT_BRAND_KIT)
    new_kit["colors"] = colors
    new_kit["rhythm"] = rhythm
    new_kit["fonts"] = current.get("fonts", DEFAULT_BRAND_KIT["fonts"])
    new_kit["caption"] = current.get("caption", DEFAULT_BRAND_KIT["caption"])
    new_kit["safe_margins"] = current.get("safe_margins", DEFAULT_BRAND_KIT["safe_margins"])
    new_kit["auto_seeded"] = True

    return save(new_kit)


AVAILABLE_CAPTION_FONTS = ["Inter", "Anton", "Archivo Black"]
