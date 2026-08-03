"""
Tests for brand_kit.py's k-means auto-seeding and edit-protection (ENGINE-PLAN.md Phase 3).

Run with: python -m pytest backend/tests/test_brand_kit.py -v
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paths  # noqa: E402
import brand_kit as bk  # noqa: E402


def _write_solid_keyframe(name: str, rgb):
    os.makedirs(paths.KEYFRAMES_DIR, exist_ok=True)
    img = Image.new("RGB", (32, 32), rgb)
    img.save(os.path.join(paths.KEYFRAMES_DIR, name))


class TestDefaults:
    def test_load_with_no_file_returns_default(self):
        kit = bk.load()
        assert kit["auto_seeded"] is True
        assert kit["colors"]["accent"] == bk.DEFAULT_BRAND_KIT["colors"]["accent"]


class TestAutoseedDeterminism:
    def test_autoseed_is_deterministic_for_fixed_frame_set(self):
        for i in range(10):
            _write_solid_keyframe(f"frame_{i}.jpg", (200, 30, 30))  # red-ish
        for i in range(10, 15):
            _write_solid_keyframe(f"frame_{i}.jpg", (20, 20, 200))  # blue-ish

        kit1 = bk.autoseed()
        colors1 = dict(kit1["colors"])

        kit2 = bk.autoseed(force=True)
        colors2 = dict(kit2["colors"])

        assert colors1 == colors2

    def test_autoseed_picks_saturated_accent_over_neutral(self):
        for i in range(10):
            _write_solid_keyframe(f"frame_{i}.jpg", (128, 128, 128))  # neutral gray
        for i in range(10, 12):
            _write_solid_keyframe(f"frame_{i}.jpg", (255, 100, 0))  # saturated orange

        kit = bk.autoseed()
        # Accent should not be the dominant neutral gray.
        assert kit["colors"]["accent"].lower() != kit["colors"]["primary"].lower()

    def test_autoseed_with_no_keyframes_falls_back_to_defaults(self):
        kit = bk.autoseed()
        assert kit["colors"] == bk.DEFAULT_BRAND_KIT["colors"]


class TestEditProtection:
    def test_auto_seeded_flips_false_on_edit(self):
        bk.autoseed()
        updated = bk.apply_edit({"colors": {"accent": "#123456"}})
        assert updated["auto_seeded"] is False
        assert updated["colors"]["accent"] == "#123456"

    def test_autoseed_refuses_to_overwrite_edited_kit_without_force(self):
        bk.autoseed()
        bk.apply_edit({"colors": {"accent": "#123456"}})
        try:
            bk.autoseed(force=False)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_autoseed_with_force_overwrites_edited_kit(self):
        bk.autoseed()
        bk.apply_edit({"colors": {"accent": "#123456"}})
        kit = bk.autoseed(force=True)
        assert kit["auto_seeded"] is True


class TestPersistence:
    def test_save_and_load_roundtrip(self):
        kit = bk.load()
        kit["fonts"]["caption"] = "Archivo Black"
        bk.save(kit)
        reloaded = bk.load()
        assert reloaded["fonts"]["caption"] == "Archivo Black"
