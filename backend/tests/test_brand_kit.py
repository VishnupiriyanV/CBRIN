"""
Tests for brand_kit.py's k-means auto-seeding and edit-protection (ENGINE-PLAN.md Phase 3).

Run with: python -m pytest backend/tests/test_brand_kit.py -v
"""
import copy
import os
import sys

import pytest
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


class TestValidation:
    """PUT /api/engine/brand_kit took an untyped dict and persisted it verbatim, so a bad
    value returned 200 and only failed later inside a background render job — surfacing as a
    raw Python TypeError with no field named. Verified against the real caption renderer."""

    def test_non_numeric_margin_is_rejected(self):
        with pytest.raises(ValueError, match="safe_margins.bottom"):
            bk.apply_edit({"safe_margins": {"bottom": "abc"}})

    def test_out_of_range_margin_is_rejected(self):
        # Renders without raising, but positions every caption off-frame — worse than a crash
        # because the job reports success.
        with pytest.raises(ValueError, match="safe_margins.bottom"):
            bk.apply_edit({"safe_margins": {"bottom": 5.0}})
        with pytest.raises(ValueError):
            bk.apply_edit({"safe_margins": {"top": -0.1}})

    def test_bool_is_not_accepted_as_a_number(self):
        # bool subclasses int, so a naive isinstance check would let True through.
        with pytest.raises(ValueError):
            bk.apply_edit({"safe_margins": {"bottom": True}})

    def test_non_hex_colour_is_rejected(self):
        with pytest.raises(ValueError, match="colors.text"):
            bk.apply_edit({"colors": {"text": "not-a-colour"}})

    def test_valid_values_are_accepted(self):
        assert bk.apply_edit({"colors": {"text": "#fff"}})["colors"]["text"] == "#fff"
        assert bk.apply_edit({"colors": {"accent": "#FF7A17"}})["colors"]["accent"] == "#FF7A17"
        assert bk.apply_edit({"safe_margins": {"bottom": 0.25}})["safe_margins"]["bottom"] == 0.25

    def test_fields_with_safe_fallbacks_stay_permissive(self):
        # caption.size resolves through .get(key, default) and fonts fall back to a bundled
        # face, so a bad value degrades rather than breaks — deliberately not rejected.
        bk.apply_edit({"caption": {"size": "enormous"}})
        bk.apply_edit({"fonts": {"caption": "NoSuchFont"}})


class TestDefaultsAreNotMutated:
    """load() shallow-copied DEFAULT_BRAND_KIT, so every nested dict came back as the SAME
    object as the module constant, and apply_edit's `current[key].update(value)` mutated that
    constant for the life of the process — even when the edit was rejected and nothing was
    written. Any later load() on a machine without bk.json returned the corruption."""

    def test_edit_does_not_mutate_the_module_defaults(self):
        before = copy.deepcopy(bk.DEFAULT_BRAND_KIT)
        bk.apply_edit({"safe_margins": {"bottom": 0.3}})
        bk.apply_edit({"colors": {"accent": "#123456"}})
        assert bk.DEFAULT_BRAND_KIT == before

    def test_rejected_edit_does_not_mutate_the_module_defaults(self):
        before = copy.deepcopy(bk.DEFAULT_BRAND_KIT)
        with pytest.raises(ValueError):
            bk.apply_edit({"safe_margins": {"bottom": "abc"}})
        assert bk.DEFAULT_BRAND_KIT == before

    def test_load_returns_independent_nested_dicts(self):
        a = bk.load()
        b = bk.load()
        assert a["safe_margins"] is not b["safe_margins"]
        assert a["safe_margins"] is not bk.DEFAULT_BRAND_KIT["safe_margins"]
