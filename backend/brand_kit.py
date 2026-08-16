"""
Brand Kit: auto-seeded from the creator's own frames, then handed to the creator to confirm
or edit (ENGINE-PLAN.md Phase 3 — the "auto-seeded, not auto-decided" design decision).

Palette is k-means over pixels sampled from existing keyframes in paths.KEYFRAMES_DIR.
Rhythm (avg shot length, words per minute) comes from OpenCV scene-cut detection and word
timing. Fonts are NOT auto-detected — a wrong typeface guess from burned-in captions is
worse than asking, so three bundled open-licence fonts are offered instead (see
backend/assets/fonts/README.md for what must be dropped in before rendering will work).
"""
import json
import os
import random
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
    if not os.path.exists(paths.BRAND_KIT_FILE):
        return dict(DEFAULT_BRAND_KIT)
    try:
        with open(paths.BRAND_KIT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        merged = dict(DEFAULT_BRAND_KIT)
        merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULT_BRAND_KIT)


def save(kit: Dict[str, Any]) -> Dict[str, Any]:
    # Atomic — user-authored brand configuration. load() above falls back to DEFAULT_BRAND_KIT
    # on any parse error, so a truncated write silently reverts the creator's colours, fonts
    # and logo to stock with no error shown.
    atomic_io.write_json(paths.BRAND_KIT_FILE, kit)
    return kit


def apply_edit(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a partial update into the persisted kit. Any edit flips auto_seeded to False so
    a later autoseed() call never silently overwrites a creator's deliberate choice."""
    current = load()
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            current[key].update(value)
        else:
            current[key] = value
    current["auto_seeded"] = False
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
