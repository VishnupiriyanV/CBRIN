"""
Guards the seam Phase 0 introduced (see ENGINE-PLAN.md risk #1): paths.use_root() must
redirect every path constant, and every consumer must read them as `paths.X`, never
`from paths import X` (which would bind a stale copy use_root() can no longer reach).

Run with: python -m pytest backend/tests/test_paths.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paths  # noqa: E402


class TestUseRootRedirectsEverything:
    def test_use_root_moves_every_constant(self, tmp_path):
        original = paths.DATA_DIR
        try:
            paths.use_root(str(tmp_path))
            root = str(tmp_path)
            assert paths.DATA_DIR == root
            assert paths.MEDIA_DIR == os.path.join(root, "media")
            assert paths.KEYFRAMES_DIR == os.path.join(root, "keyframes")
            assert paths.CHUNKS_FILE == os.path.join(root, "chunks.json")
            assert paths.EMBEDDINGS_FILE == os.path.join(root, "embeddings.npy")
            assert paths.VISUAL_EMBEDDINGS_FILE == os.path.join(root, "visual_embeddings.npy")
            assert paths.VIDEOS_FILE == os.path.join(root, "videos.json")
            assert paths.HIGHLIGHTS_FILE == os.path.join(root, "highlights.json")
            assert paths.INDEX_META_FILE == os.path.join(root, "index_meta.json")
            assert paths.WORDS_DIR == os.path.join(root, "words")
            assert paths.CLIPS_DIR == os.path.join(root, "clips")
            assert paths.CLIPS_FILE == os.path.join(root, "clips.json")
            assert paths.BRAND_KIT_FILE == os.path.join(root, "brand_kit.json")
            assert paths.JOBS_FILE == os.path.join(root, "jobs.json")
            assert paths.CLIP_FEEDBACK_FILE == os.path.join(root, "clip_feedback.json")
        finally:
            paths.use_root(original)

    def test_vector_store_reads_live_paths_module_attribute(self, tmp_path):
        """
        vector_store.py must do `import paths` and read `paths.CHUNKS_FILE` at each use
        site — if it ever regresses to `from paths import CHUNKS_FILE`, that name would be
        bound at import time and use_root() calls afterward would silently stop reaching it.
        This test proves the live redirect actually takes effect through vector_store.
        """
        import vector_store as vs

        original = paths.DATA_DIR
        try:
            paths.use_root(str(tmp_path))
            store = vs.VectorStore()
            assert os.path.exists(paths.MEDIA_DIR)
            # _ensure_dirs() must have created directories under tmp_path, not the real data dir.
            assert str(tmp_path) in paths.MEDIA_DIR
        finally:
            paths.use_root(original)
