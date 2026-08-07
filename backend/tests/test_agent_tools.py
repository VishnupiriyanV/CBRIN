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
        fake_profile = {
            "niche": "productivity", "audience": "founders", "tone": ["direct"],
            "banned_words": [], "sample_content": [], "cta_style": "", "default_platforms": [],
        }
        with patch("voice_profile.load", return_value=fake_profile), \
             patch("voice_profile.to_prompt_block", return_value="Voice Profile — match this creator's tone:\n- Niche: productivity"), \
             patch("platform_rules.load", return_value=fake_rules):
            result = agent_tools.execute_tool("get_creator_context", {}, store)
        assert result["platform_rules"] == fake_rules
        assert result["platform_rules"] != {}

    def test_returns_real_voice_profile_keys_not_nonexistent_bio_examples(self):
        # voice_profile.DEFAULT_VOICE_PROFILE has niche/audience/tone/banned_words/
        # sample_content/cta_style/default_platforms — never bio/examples. The old code read
        # bio/examples, which were always empty, and never surfaced niche/audience/cta_style.
        store = FakeStore()
        fake_profile = {
            "niche": "AI tooling", "audience": "developers", "tone": ["direct", "witty"],
            "banned_words": ["delve"], "sample_content": ["a sample line long enough"],
            "cta_style": "soft", "default_platforms": ["x"],
        }
        with patch("voice_profile.load", return_value=fake_profile), \
             patch("platform_rules.load", return_value={}):
            result = agent_tools.execute_tool("get_creator_context", {}, store)
        vp = result["voice_profile"]
        assert vp["niche"] == "AI tooling"
        assert vp["audience"] == "developers"
        assert vp["cta_style"] == "soft"
        assert vp["sample_content"] == ["a sample line long enough"]
        assert "bio" not in vp
        assert "examples" not in vp
        assert "voice_profile_prompt" in result
        assert "AI tooling" in result["voice_profile_prompt"] or result["voice_profile_prompt"]


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


class TestSearchVaultFieldMapping:
    def test_search_hit_carries_real_title_and_timestamp(self):
        # search_vault used to read title/start_time/end_time/start_formatted/final_score off
        # search() hits, none of which exist on the real vector_store.search() result shape —
        # every field came back None/0, breaking the agent's citation instruction
        # ("cite as [video title @ mm:ss] using start_formatted/start_time").
        results = {"results": [
            {"video_id": "v1", "video_title": "Safari Tips", "start_sec": 83.0, "end_sec": 91.0,
             "start_timestamp": "01:23", "end_timestamp": "01:31", "text": "Safari can tame your tabs.",
             "score": 0.42, "confidence": "strong", "match_reason": "Matched: tabs & safari"},
        ]}
        store = FakeStore(search_results=results)
        result = agent_tools.execute_tool("search_vault", {"query": "safari tabs"}, store)
        assert result["count"] == 1
        hit = result["results"][0]
        assert hit["title"] == "Safari Tips"
        assert hit["start_time"] == "01:23"
        assert hit["start_formatted"] == "01:23"
        assert hit["start_sec"] == 83.0
        assert hit["score"] == 0.42
        assert hit["confidence"] == "strong"


class TestDeepResearch:
    def test_fuses_single_query_results_when_llm_not_configured(self):
        # Real VectorStore.search() result shape (vector_store.py:846-866): video_title/
        # start_sec/end_sec/start_timestamp/score — NOT title/start_time/final_score.
        results = {"results": [
            {"video_id": "v1", "video_title": "Video 1", "start_sec": 10.0, "end_sec": 12.0,
             "start_timestamp": "00:10", "text": "about pricing", "score": 0.9},
        ]}
        store = FakeStore(search_results=results)
        with patch("llm_client.is_configured", return_value=False):
            result = agent_tools.execute_tool("deep_research", {"query": "pricing"}, store)
        assert result["count"] == 1
        assert result["results"][0]["video_id"] == "v1"
        assert result["results"][0]["title"] == "Video 1"
        assert result["results"][0]["start_time"] == "00:10"
        assert result["results"][0]["score"] == 0.9
        assert result["expanded_queries"] == ["pricing"]

    def test_expands_and_fuses_with_paraphrases(self):
        results_a = {"results": [{"video_id": "v1", "video_title": "V1", "start_sec": 5.0, "end_sec": 7.0, "start_timestamp": "00:05", "text": "a", "score": 0.8}]}
        results_b = {"results": [{"video_id": "v2", "video_title": "V2", "start_sec": 20.0, "end_sec": 22.0, "start_timestamp": "00:20", "text": "b", "score": 0.7}]}

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

    def test_does_not_collapse_hits_from_one_video(self):
        # RRF used to key on (video_id, start_time), which is always None on the real search()
        # shape — every hit from the same video collapsed into a single fused entry regardless
        # of which passage it came from. Two distinct passages from the same video, same query
        # (so no paraphrase expansion muddies the count), must both survive.
        results = {"results": [
            {"video_id": "v1", "video_title": "V1", "start_sec": 5.0, "end_sec": 7.0, "start_timestamp": "00:05", "text": "first passage", "score": 0.9},
            {"video_id": "v1", "video_title": "V1", "start_sec": 42.0, "end_sec": 44.0, "start_timestamp": "00:42", "text": "second passage", "score": 0.8},
        ]}
        store = FakeStore(search_results=results)
        with patch("llm_client.is_configured", return_value=False):
            result = agent_tools.execute_tool("deep_research", {"query": "topic"}, store)
        assert result["count"] == 2
        starts = {r["start_sec"] for r in result["results"]}
        assert starts == {5.0, 42.0}


class TestExtractVideoClipsFallback:
    def test_fallback_candidates_are_rankable_not_a_keyerror(self):
        # When narrative_engine finds no beats/candidates, extract_video_clips builds fallback
        # candidates directly from chunks. They used to carry start_idx/end_idx — keys
        # clip_scoring.rank() never reads (it reads start_sentence_idx/end_sentence_idx),
        # guaranteeing a KeyError swallowed into a generic "Tool execution failed" string.
        # Run the REAL (unmocked) clip_scoring.rank against the fallback shape.
        chunks = [
            _sentence(0, "This is the first sentence of the video.", 0.0, 3.0),
            _sentence(1, "This is the second sentence, a bit longer than the first one.", 3.0, 7.0),
            _sentence(2, "Third sentence wraps up this short highlight block nicely.", 7.0, 11.0),
            _sentence(3, "Fourth sentence starts a brand new highlight block here.", 11.0, 14.0),
            _sentence(4, "Fifth sentence continues the second highlight block onward.", 14.0, 18.0),
            _sentence(5, "Sixth sentence closes out the second highlight block cleanly.", 18.0, 22.0),
        ]
        store = FakeStore(videos={"vid1": {"title": "My Video"}}, chunks=chunks)

        with patch("narrative_engine.analyze_video", return_value={"beats": [], "candidates": [], "degraded": False}):
            result = agent_tools.execute_tool(
                "extract_video_clips", {"video_id": "vid1", "count": 2}, store
            )

        assert "error" not in result, result.get("error")
        assert result["clips_found"] >= 1
        clip = result["clips"][0]
        assert clip["start_time"] is not None
        assert clip["duration"] is not None
        assert clip["transcript"]


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
