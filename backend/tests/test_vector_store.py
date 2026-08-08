"""
Tests for VectorStore.search()'s relevance-gating fallback and delete_video's cleanup —
covering two bugs found in review after the improvement-plan implementation:

1. When the cross-encoder reranker is unavailable (fails to load, or raises during
   .predict()), search() used to gate 'spoken' results against RERANK_RELEVANCE_THRESHOLD
   (calibrated for sigmoid(cross-encoder logit) scores) while `score` was actually still the
   retrieval-stage score (RRF-fused, maxing out around 0.03) — so every query silently
   returned zero results despite good candidates existing. Confirmed live in this repo when
   the cross-encoder failed to load from a transient network failure. Fixed by falling back
   to unranked top-K with confidence='unranked' and a `degraded: true` response flag instead
   of comparing incompatible scales.
2. delete_video() removed a video's source media file but never its per-chunk keyframe
   JPGs, leaking them on disk forever. Confirmed live: 67 orphaned keyframe files were found
   in backend/data/keyframes/ from earlier deletes.

Run with: python -m pytest backend/tests/test_vector_store.py -v
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paths  # noqa: E402
import vector_store as vs  # noqa: E402


def _make_chunk(video_id: str, idx: int, text: str, start: int, end: int) -> dict:
    return {
        "id": f"chunk-{video_id}-{idx + 1}",
        "video_id": video_id,
        "video_title": f"Test Video {video_id}",
        "channel": "Test Channel",
        "youtube_id": None,
        "is_local": True,
        "sentence_idx": idx,
        "start_sec": start,
        "end_sec": end,
        "start_timestamp": f"00:{start:02d}",
        "end_timestamp": f"00:{end:02d}",
        "text": text,
        "enriched_text": text,
        "section_topic": "Test Topic",
        "questions_answered": ["What is the test about?"],
        "implicit_concepts": ["testing"],
        "thumbnail_url": "",
        "has_visual_embedding": False,
        "visual_status": "failed",
        "keyframe_url": None,
        "indexed_at": "2026-01-01T00:00:00",
    }


def _build_store_with_chunks() -> vs.VectorStore:
    store = vs.VectorStore.__new__(vs.VectorStore)
    store.chunks = []
    store.videos = {}
    store.highlights = {}
    store.is_fitted = False
    store.dense_embeddings = None
    store.visual_embeddings = None
    store.bm25_index = None
    store._suggested_queries_cache = None
    store.pending_rechunk = []
    store.pending_rechunk_meta = {}

    chunks = [
        _make_chunk("vid-a", 0, "Today we talk about kubernetes and container orchestration.", 0, 10),
        _make_chunk("vid-a", 1, "Kubernetes schedules pods across a cluster of machines.", 10, 20),
        _make_chunk("vid-a", 2, "Now let's switch topics to baking sourdough bread at home.", 20, 30),
        _make_chunk("vid-b", 0, "This video covers python testing frameworks like pytest.", 0, 10),
    ]
    store.chunks = chunks
    store.reindex()
    return store


class TestRerankerUnavailableFallback:
    def test_reranker_none_returns_unranked_results_not_empty(self):
        store = _build_store_with_chunks()
        with patch.object(vs, "get_cross_encoder", return_value=None):
            resp = store.search(query="kubernetes container orchestration", top_k=5, search_mode="spoken")

        assert resp["degraded"] is True
        assert len(resp["results"]) > 0, (
            "reranker-unavailable fallback must still return best-effort results, "
            "not silently empty everything against an incompatible threshold"
        )
        for item in resp["results"]:
            assert item["confidence"] == "unranked"
        assert "message" in resp

    def test_reranker_predict_exception_also_falls_back(self):
        class ExplodingReranker:
            def predict(self, pairs):
                raise RuntimeError("simulated model failure")

        store = _build_store_with_chunks()
        with patch.object(vs, "get_cross_encoder", return_value=ExplodingReranker()):
            resp = store.search(query="kubernetes container orchestration", top_k=5, search_mode="spoken")

        assert resp["degraded"] is True
        assert len(resp["results"]) > 0

    def test_reranker_working_normally_is_not_degraded(self):
        store = _build_store_with_chunks()
        reranker = vs.get_cross_encoder()
        if reranker is None:
            import pytest
            pytest.skip("CrossEncoder model unavailable in this environment")

        resp = store.search(query="kubernetes container orchestration", top_k=5, search_mode="spoken")
        assert resp["degraded"] is False
        for item in resp["results"]:
            assert item["confidence"] in ("strong", "possible")

    def test_visual_scenes_mode_untouched_by_degraded_flag(self):
        # visual_scenes has no chunks with visual_status == 'ok' here, so it should return
        # the informative empty message (fix #5), not degraded=True (that flag is spoken-only).
        store = _build_store_with_chunks()
        resp = store.search(query="anything", top_k=5, search_mode="visual_scenes")
        assert resp["degraded"] is False
        assert resp["results"] == []
        assert "per-moment visual data" in resp.get("message", "")


class TestDisplayGates:
    """The second, stricter pass that decides what's worth SHOWING among what's plausible.

    Covers the failure this was written for: a query whose signal is spread across one video
    returned every above-threshold moment from it (six results, all one video, ~100+ words
    each), which reads as six answers to one question.
    """

    @staticmethod
    def _cands(*scores_and_vids):
        return [
            {"score": s, "video_id": v, "id": f"c{i}", "start_sec": i * 100.0, "end_sec": i * 100.0 + 10.0}
            for i, (s, v) in enumerate(scores_and_vids)
        ]

    def test_per_video_cap_limits_one_video_from_filling_every_slot(self):
        cands = self._cands((0.99, "vid-a"), (0.98, "vid-a"), (0.97, "vid-a"), (0.96, "vid-a"))
        kept = vs.VectorStore._apply_display_gates(cands, absolute_floor=0.10)
        assert len(kept) == vs.MAX_RESULTS_PER_VIDEO
        assert [c["score"] for c in kept] == [0.99, 0.98], "must keep the highest-scoring ones"

    def test_per_video_cap_is_per_video_not_global(self):
        cands = self._cands((0.99, "vid-a"), (0.98, "vid-a"), (0.97, "vid-a"), (0.96, "vid-b"))
        kept = vs.VectorStore._apply_display_gates(cands, absolute_floor=0.10)
        assert len(kept) == 3
        assert {c["video_id"] for c in kept} == {"vid-a", "vid-b"}

    def test_relative_floor_drops_the_weak_tail(self):
        # Real shape from the "weather" query: a clear top hit and a distant second that only
        # qualified because it happened to clear the permissive recall floor.
        cands = self._cands((0.518, "vid-a"), (0.123, "vid-a"))
        kept = vs.VectorStore._apply_display_gates(cands, absolute_floor=0.10)
        assert [c["score"] for c in kept] == [0.518]

    def test_relative_floor_keeps_genuinely_close_scores(self):
        cands = self._cands((0.90, "vid-a"), (0.85, "vid-b"))
        kept = vs.VectorStore._apply_display_gates(cands, absolute_floor=0.10)
        assert len(kept) == 2, "results of comparable quality must all survive"

    def test_absolute_floor_can_be_skipped_for_visual_mode(self):
        # visual_scenes passes absolute_floor=None because VISUAL_RELEVANCE_THRESHOLD (a
        # different, CLIP-scale number) has already gated it upstream.
        cands = self._cands((0.05, "vid-a"),)
        assert vs.VectorStore._apply_display_gates(cands, absolute_floor=0.10) == []
        assert len(vs.VectorStore._apply_display_gates(cands, absolute_floor=None)) == 1

    def test_empty_input_returns_empty(self):
        assert vs.VectorStore._apply_display_gates([], absolute_floor=0.10) == []

    def test_candidates_below_display_bar_become_near_misses_not_empty(self):
        """"Nothing confident enough to lead with" must not collapse into "nothing matched"."""
        store = _build_store_with_chunks()
        if vs.get_cross_encoder() is None:
            import pytest
            pytest.skip("CrossEncoder model unavailable in this environment")

        # Floor above any achievable score: everything clears the recall gate, nothing
        # clears the display gate.
        with patch.object(vs, "RERANK_DISPLAY_THRESHOLD", 1.1):
            resp = store.search(query="kubernetes container orchestration", top_k=5, search_mode="spoken")

        assert resp["results"] == []
        assert len(resp["near_misses"]) > 0, (
            "candidates that cleared the relevance bar but not the display bar must be "
            "demoted to near_misses, not silently dropped into the empty state"
        )
        assert all(nm["confidence"] == "weak" for nm in resp["near_misses"])

    def test_degraded_path_ignores_display_gates(self):
        """Degraded scores are on an entirely different scale — these gates are meaningless
        there and must not be applied, or the degraded fallback returns nothing."""
        store = _build_store_with_chunks()
        with patch.object(vs, "get_cross_encoder", return_value=None), \
             patch.object(vs, "RERANK_DISPLAY_THRESHOLD", 1.1), \
             patch.object(vs, "MAX_RESULTS_PER_VIDEO", 0):
            resp = store.search(query="kubernetes container orchestration", top_k=5, search_mode="spoken")

        assert resp["degraded"] is True
        assert len(resp["results"]) > 0


class TestFocusQuote:
    """Trimming the displayed quote to the sentences that actually matched."""

    def test_short_windows_are_left_alone(self):
        store = _build_store_with_chunks()
        if vs.get_cross_encoder() is None:
            import pytest
            pytest.skip("CrossEncoder model unavailable in this environment")

        resp = store.search(query="kubernetes container orchestration", top_k=5, search_mode="spoken")
        for r in resp["results"]:
            if len(r["text"].split()) <= vs.FOCUS_MAX_WORDS:
                assert "full_text" not in r, (
                    "full_text is the signal that trimming happened — it must be absent when "
                    "the quote was already short, or the UI offers an expand that does nothing"
                )

    def test_long_window_is_trimmed_and_full_text_preserved(self):
        store = _build_store_with_chunks()
        long_sentences = [
            _make_chunk("vid-long", i, f"Sentence number {i} about kubernetes " + "padding word " * 20, i * 10, i * 10 + 10)
            for i in range(8)
        ]
        store.chunks = store.chunks + long_sentences
        store.reindex()

        video_map = {"vid-long": long_sentences}
        cand = {
            "video_id": "vid-long",
            "sentence_range": (0, 7),
            "is_legacy_window": False,
            "text": " ".join(s["text"] for s in long_sentences),
            "matched_sentence": long_sentences[3]["text"],
        }
        original = cand["text"]
        store._focus_quote("kubernetes", cand, video_map)

        assert cand["full_text"] == original
        assert len(cand["text"].split()) < len(original.split())
        assert len(cand["text"].split()) <= vs.FOCUS_MAX_WORDS
        assert cand["text"] in original, "the trimmed quote must be a verbatim span of the window"
        assert "focus_start_sec" in cand and "focus_end_sec" in cand

    def test_focus_does_not_move_playback_range(self):
        """start_sec/end_sec drive Jump and the copied citation — trimming must not touch them."""
        store = _build_store_with_chunks()
        long_sentences = [
            _make_chunk("vid-long", i, f"Sentence {i} about kubernetes " + "filler " * 20, i * 10, i * 10 + 10)
            for i in range(8)
        ]
        video_map = {"vid-long": long_sentences}
        cand = {
            "video_id": "vid-long",
            "sentence_range": (0, 7),
            "is_legacy_window": False,
            "text": " ".join(s["text"] for s in long_sentences),
            "matched_sentence": long_sentences[3]["text"],
            "start_sec": 0.0,
            "end_sec": 80.0,
        }
        store._focus_quote("kubernetes", cand, video_map)
        assert cand["start_sec"] == 0.0
        assert cand["end_sec"] == 80.0

    def test_legacy_windows_are_skipped(self):
        store = _build_store_with_chunks()
        cand = {
            "video_id": "vid-x",
            "sentence_range": (0, 0),
            "is_legacy_window": True,
            "text": "word " * 200,
        }
        store._focus_quote("anything", cand, {})
        assert "full_text" not in cand, "legacy chunks have no sentence index to trim against"


class TestDeleteVideoCleansUpKeyframes:
    def test_delete_video_removes_keyframe_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "KEYFRAMES_DIR", str(tmp_path))
        monkeypatch.setattr(paths, "MEDIA_DIR", str(tmp_path))

        store = _build_store_with_chunks()

        keyframe_paths = []
        for c in store.chunks:
            if c["video_id"] == "vid-a":
                p = tmp_path / f"{c['id']}.jpg"
                p.write_bytes(b"fake-jpeg-bytes")
                keyframe_paths.append(p)

        assert all(p.exists() for p in keyframe_paths)

        store.delete_video("vid-a")

        assert not any(p.exists() for p in keyframe_paths), (
            "delete_video must remove every deleted chunk's keyframe file, not just the "
            "source media file — otherwise keyframes for deleted videos leak on disk forever"
        )
        assert all(c["video_id"] != "vid-a" for c in store.chunks)


class TestVisualOnlyChunksSuppressionInSpokenSearch:
    def test_visual_only_chunks_suppressed_in_spoken_search(self):
        from vector_store import VectorStore
        store = VectorStore()
        store.chunks = [
            {
                "id": "chunk-1",
                "video_id": "vid-visual",
                "text": "[Visual Scene 00:00 - 00:15]",
                "is_visual_only": True,
                "visual_status": "ok",
                "start_sec": 0.0,
                "end_sec": 15.0
            },
            {
                "id": "chunk-2",
                "video_id": "vid-speech",
                "text": "This is a real spoken sentence about artificial intelligence.",
                "is_visual_only": False,
                "visual_status": "failed",
                "start_sec": 0.0,
                "end_sec": 10.0
            }
        ]
        store.is_fitted = True

        resp = store.search(query="Visual Scene", search_mode="spoken")
        # Visual Scene synthetic chunk must not appear in spoken search results
        for r in resp["results"]:
            assert r.get("text") != "[Visual Scene 00:00 - 00:15]"
            assert r.get("is_visual_only") is not True

