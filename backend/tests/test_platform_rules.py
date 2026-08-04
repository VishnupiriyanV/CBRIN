"""
Tests for platform_rules.py's editable per-platform config (creator-tools-integration-spec.md
§5 — limits and hashtag conventions must live in config, not the prompt).

Run with: python -m pytest backend/tests/test_platform_rules.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import platform_rules as pr  # noqa: E402


class TestDefaults:
    def test_load_with_no_file_returns_all_six_platforms(self):
        rules = pr.load()
        for platform in ["tiktok", "instagram", "youtube_short", "youtube_long", "x", "linkedin"]:
            assert platform in rules
            assert "char_limit" in rules[platform]


class TestApplyEdit:
    def test_edit_updates_one_platform_without_touching_others(self):
        pr.apply_edit({"x": {"char_limit": 200}})
        rules = pr.load()
        assert rules["x"]["char_limit"] == 200
        assert rules["tiktok"]["char_limit"] == pr.DEFAULT_PLATFORM_RULES["tiktok"]["char_limit"]

    def test_edit_persists_across_reload(self):
        pr.apply_edit({"linkedin": {"hashtag_max": 5}})
        assert pr.load()["linkedin"]["hashtag_max"] == 5


class TestGet:
    def test_get_known_platform(self):
        assert pr.get("tiktok")["label"] == "TikTok"

    def test_get_unknown_platform_returns_empty(self):
        assert pr.get("myspace") == {}
