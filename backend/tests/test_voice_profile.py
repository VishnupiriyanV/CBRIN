"""
Tests for voice_profile.py's load/save/apply_edit/autoseed and prompt-block rendering
(creator-tools-integration-spec.md §0.3 — the Voice Profile is "the main differentiator
against people just using raw ChatGPT").

Run with: python -m pytest backend/tests/test_voice_profile.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import voice_profile as vp  # noqa: E402


class TestDefaults:
    def test_load_with_no_file_returns_default(self):
        profile = vp.load()
        assert profile["auto_seeded"] is True
        assert profile["niche"] == ""
        assert "delve" in profile["banned_words"]


class TestSaveAndLoad:
    def test_save_then_load_roundtrips(self):
        profile = vp.load()
        profile["niche"] = "b2b saas"
        vp.save(profile)
        reloaded = vp.load()
        assert reloaded["niche"] == "b2b saas"


class TestApplyEdit:
    def test_edit_merges_and_flips_auto_seeded_false(self):
        vp.apply_edit({"niche": "fitness coaching", "audience": "beginners"})
        profile = vp.load()
        assert profile["niche"] == "fitness coaching"
        assert profile["audience"] == "beginners"
        assert profile["auto_seeded"] is False

    def test_edit_preserves_untouched_fields(self):
        vp.apply_edit({"niche": "cooking"})
        profile = vp.load()
        assert profile["tone"] == vp.DEFAULT_VOICE_PROFILE["tone"]


class TestAutoseed:
    def test_autoseed_derives_niche_from_chunk_texts(self):
        texts = [
            "kubernetes orchestration patterns for microservices at scale",
            "kubernetes orchestration patterns for microservices at scale",
            "database indexing strategies for high throughput systems",
        ]
        profile = vp.autoseed(chunk_texts=texts)
        assert profile["niche"] != ""
        assert profile["auto_seeded"] is True

    def test_autoseed_with_no_texts_leaves_niche_blank(self):
        profile = vp.autoseed(chunk_texts=[])
        assert profile["niche"] == ""

    def test_autoseed_refuses_to_overwrite_edited_profile(self):
        vp.apply_edit({"niche": "manual choice"})
        try:
            vp.autoseed(chunk_texts=["some long enough sentence about testing " * 5])
            assert False, "expected ValueError"
        except ValueError:
            pass
        assert vp.load()["niche"] == "manual choice"

    def test_autoseed_force_overwrites_edited_profile(self):
        vp.apply_edit({"niche": "manual choice"})
        vp.autoseed(chunk_texts=[], force=True)
        assert vp.load()["auto_seeded"] is True


class TestToPromptBlock:
    def test_empty_profile_returns_generic_instruction(self):
        block = vp.to_prompt_block({"niche": "", "audience": "", "tone": [], "banned_words": [],
                                     "sample_content": [], "cta_style": ""})
        assert "clear, direct" in block

    def test_populated_profile_includes_all_fields(self):
        profile = dict(vp.DEFAULT_VOICE_PROFILE)
        profile.update({
            "niche": "b2b saas",
            "audience": "founders",
            "tone": ["witty", "direct"],
            "cta_style": "soft ask",
            "banned_words": ["delve"],
            "sample_content": ["This is a long enough sample sentence for the block."],
        })
        block = vp.to_prompt_block(profile)
        assert "b2b saas" in block
        assert "founders" in block
        assert "witty" in block
        assert "soft ask" in block
        assert "delve" in block
        assert "long enough sample sentence" in block
