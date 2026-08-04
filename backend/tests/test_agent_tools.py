"""
Tests for agent_tools.py — covers the bugs found during the agentic pivot audit:
  1. get_creator_context used to call a nonexistent platform_rules.load_rules() and
     silently return {} for platform_rules.
  2. run_studio_tool used to shotgun the same text into transcript_text/source_text/
     input_text, which only show_notes/moments actually read — repurposer/titles/replies/
     captions received no usable input.
  3. moments/show_notes used to fabricate fake 15s/line timestamps for untimed paste input.

Run with: python -m pytest backend/tests/test_agent_tools.py -v
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent_tools  # noqa: E402


class FakeStore:
    def __init__(self, videos=None, chunks=None, search_results=None):
        self.videos = videos or {}
        self.chunks = chunks or []
        self._search_results = search_results if search_results is not None else {"results": []}

    def search(self, query, top_k=5, relevance_threshold=None):
        return self._search_results


def _sentence(idx, text, start, end, video_id="vid1"):
    return {"video_id": video_id, "sentence_idx": idx, "text": text, "start_sec": start, "end_sec": end}


class TestGetCreatorContext:
    def test_returns_real_platform_rules_not_empty_dict(self):
        store = FakeStore()
        fake_rules = {"tiktok": {"label": "TikTok", "char_limit": 150}}
        with patch("voice_profile.load", return_value={"bio": "b", "tone": "t", "banned_words": [], "examples": []}), \
             patch("platform_rules.load", return_value=fake_rules):
            result = agent_tools.execute_tool("get_creator_context", {}, store)
        assert result["platform_rules"] == fake_rules
        assert result["platform_rules"] != {}


class TestRunStudioToolInputMapping:
    def test_titles_maps_input_text_to_topic(self):
        store = FakeStore()
        with patch("studio_runner.run_tool") as mock_run:
            mock_run.return_value = {"titles": [], "hooks": [], "thumbnail_text": []}
            agent_tools.execute_tool(
                "run_studio_tool", {"tool_id": "titles", "input_text": "AI safety trends"}, store
            )
        _, kwargs = mock_run.call_args
        assert kwargs["inputs"] == {"topic": "AI safety trends"}

    def test_replies_splits_lines_into_comments_list(self):
        store = FakeStore()
        with patch("studio_runner.run_tool") as mock_run:
            mock_run.return_value = {"replies": []}
            agent_tools.execute_tool(
                "run_studio_tool",
                {"tool_id": "replies", "input_text": "great video!\nwhen is part 2?"},
                store,
            )
        _, kwargs = mock_run.call_args
        assert kwargs["inputs"] == {"comments": ["great video!", "when is part 2?"]}

    def test_captions_maps_to_text_and_platforms(self):
        store = FakeStore()
        with patch("studio_runner.run_tool") as mock_run:
            mock_run.return_value = {}
            agent_tools.execute_tool(
                "run_studio_tool",
                {"tool_id": "captions", "input_text": "Check out my new video", "platform": "twitter"},
                store,
            )
        _, kwargs = mock_run.call_args
        # 'twitter' must normalize to the platform_rules key 'x'
        assert kwargs["inputs"] == {"text": "Check out my new video", "platforms": ["x"]}

    def test_repurposer_maps_to_text(self):
        store = FakeStore()
        with patch("studio_runner.run_tool") as mock_run:
            mock_run.return_value = {}
            agent_tools.execute_tool(
                "run_studio_tool", {"tool_id": "repurposer", "input_text": "My newsletter body"}, store
            )
        _, kwargs = mock_run.call_args
        assert kwargs["inputs"] == {"text": "My newsletter body"}


class TestNoFabricatedTimestamps:
    def test_moments_uses_real_library_sentences_when_video_id_given(self):
        chunks = [_sentence(0, "hello", 0.0, 2.0), _sentence(1, "world", 2.0, 4.0)]
        store = FakeStore(videos={"vid1": {"title": "V"}}, chunks=chunks)
        with patch("studio_runner.run_tool") as mock_run:
            mock_run.return_value = {"moments": []}
            agent_tools.execute_tool(
                "run_studio_tool",
                {"tool_id": "moments", "input_text": "ignored when video_id given", "video_id": "vid1"},
                store,
            )
        _, kwargs = mock_run.call_args
        assert kwargs["inputs"]["source"] == "library"
        assert kwargs["inputs"]["sentences"][0]["start_sec"] == 0.0
        assert kwargs["inputs"]["sentences"][1]["start_sec"] == 2.0

    def test_moments_falls_back_to_paste_without_fabricating_timestamps(self):
        store = FakeStore()
        with patch("studio_runner.run_tool") as mock_run:
            mock_run.return_value = {"moments": []}
            agent_tools.execute_tool(
                "run_studio_tool",
                {"tool_id": "moments", "input_text": "line one\nline two\nline three"},
                store,
            )
        _, kwargs = mock_run.call_args
        # Must pass the raw paste through untouched — no invented [00:15]/[00:30] cues.
        assert kwargs["inputs"] == {"source": "paste", "transcript_text": "line one\nline two\nline three"}
        assert "00:15" not in kwargs["inputs"]["transcript_text"]
        assert "00:30" not in kwargs["inputs"]["transcript_text"]


class TestDeepResearch:
    def test_fuses_single_query_results_when_llm_not_configured(self):
        results = {"results": [
            {"video_id": "v1", "title": "Video 1", "start_time": 10.0, "text": "about pricing", "final_score": 0.9},
        ]}
        store = FakeStore(search_results=results)
        with patch("llm_client.is_configured", return_value=False):
            result = agent_tools.execute_tool("deep_research", {"query": "pricing"}, store)
        assert result["count"] == 1
        assert result["results"][0]["video_id"] == "v1"
        assert result["expanded_queries"] == ["pricing"]

    def test_expands_and_fuses_with_paraphrases(self):
        results_a = {"results": [{"video_id": "v1", "title": "V1", "start_time": 5.0, "text": "a", "final_score": 0.8}]}
        results_b = {"results": [{"video_id": "v2", "title": "V2", "start_time": 20.0, "text": "b", "final_score": 0.7}]}

        store = FakeStore()
        call_count = {"n": 0}

        def fake_search(query, top_k=5, relevance_threshold=None):
            call_count["n"] += 1
            return results_a if call_count["n"] == 1 else results_b

        store.search = fake_search

        with patch("llm_client.is_configured", return_value=True), \
             patch("llm_client.complete_json", return_value={"queries": ["pricing model"]}):
            result = agent_tools.execute_tool("deep_research", {"query": "pricing"}, store)

        assert result["expanded_queries"] == ["pricing", "pricing model"]
        returned_video_ids = {r["video_id"] for r in result["results"]}
        assert returned_video_ids == {"v1", "v2"}


class TestGenerateContentPack:
    def test_returns_well_formed_pack_with_all_sections(self):
        chunks = [_sentence(0, "hello world", 0.0, 2.0), _sentence(1, "second sentence", 2.0, 4.0)]
        store = FakeStore(videos={"vid1": {"title": "My Video"}}, chunks=chunks)

        with patch("narrative_engine.analyze_video", return_value={"candidates": []}), \
             patch("clip_scoring.compute_taste_centroid", return_value=None), \
             patch("clip_scoring.rank", return_value=[]), \
             patch("vector_store.get_cross_encoder", return_value=None), \
             patch("studio_runner.run_tool") as mock_run:
            mock_run.side_effect = lambda tool_id, inputs, use_voice_profile=True: {"tool_id": tool_id, "ok": True}

            result = agent_tools.execute_tool(
                "generate_content_pack", {"video_id": "vid1", "goal": "week of content"}, store
            )

        assert result["video_id"] == "vid1"
        assert result["video_title"] == "My Video"
        assert result["repurposed"] == {"tool_id": "repurposer", "ok": True}
        assert result["titles"] == {"tool_id": "titles", "ok": True}
        assert result["show_notes"] == {"tool_id": "show_notes", "ok": True}
        assert result["captions"] == {"tool_id": "captions", "ok": True}
        assert result["errors"] == {}
        assert result["sources"] == [{"video_id": "vid1", "title": "My Video"}]

    def test_partial_failure_still_returns_a_pack(self):
        chunks = [_sentence(0, "hello world", 0.0, 2.0)]
        store = FakeStore(videos={"vid1": {"title": "My Video"}}, chunks=chunks)

        def flaky_run_tool(tool_id, inputs, use_voice_profile=True):
            if tool_id == "titles":
                raise RuntimeError("LLM timeout")
            return {"tool_id": tool_id, "ok": True}

        with patch("narrative_engine.analyze_video", return_value={"candidates": []}), \
             patch("clip_scoring.compute_taste_centroid", return_value=None), \
             patch("clip_scoring.rank", return_value=[]), \
             patch("vector_store.get_cross_encoder", return_value=None), \
             patch("studio_runner.run_tool", side_effect=flaky_run_tool):
            result = agent_tools.execute_tool("generate_content_pack", {"video_id": "vid1"}, store)

        assert result["titles"] is None
        assert "titles" in result["errors"]
        assert result["repurposed"] == {"tool_id": "repurposer", "ok": True}

    def test_no_videos_returns_error_not_exception(self):
        store = FakeStore()
        result = agent_tools.execute_tool("generate_content_pack", {}, store)
        assert "error" in result
