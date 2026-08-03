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
