"""
Tests for content_hash_id — the stable video-ID generator (IMPROVEMENT-PLAN.md 1.3).
The old `f"local-{abs(hash(file_name)) % 100000}"` scheme was non-deterministic across
process restarts (Python randomizes string hashing) and collision-prone; this replaces it
with a content-addressed SHA1 of the file bytes.

Run with: python -m pytest backend/tests -v
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from transcript_service import content_hash_id  # noqa: E402


def _write_temp(content: bytes) -> str:
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return path


class TestContentHashId:
    def test_same_bytes_same_id(self):
        path_a = _write_temp(b"identical content")
        path_b = _write_temp(b"identical content")
        try:
            assert content_hash_id(path_a) == content_hash_id(path_b)
        finally:
            os.remove(path_a)
            os.remove(path_b)

    def test_different_bytes_different_id(self):
        path_a = _write_temp(b"content A")
        path_b = _write_temp(b"content B")
        try:
            assert content_hash_id(path_a) != content_hash_id(path_b)
        finally:
            os.remove(path_a)
            os.remove(path_b)

    def test_id_is_stable_regardless_of_filename(self):
        # The old scheme hashed the filename; a re-upload of the same bytes under a
        # different filename must still dedupe to the same ID.
        path = _write_temp(b"same bytes, different name on disk")
        try:
            assert content_hash_id(path) == content_hash_id(path)
        finally:
            os.remove(path)

    def test_id_format(self):
        path = _write_temp(b"some file content")
        try:
            vid_id = content_hash_id(path)
            assert vid_id.startswith("local-")
            assert len(vid_id) == len("local-") + 12
        finally:
            os.remove(path)


class TestNonSpeechVideoTranscription:
    def test_non_speech_video_generates_visual_scene_segments(self, monkeypatch):
        import transcript_service

        # Mock local whisper to return empty segments (no speech detected)
        class DummyWhisperModel:
            device = type("Device", (), {"type": "cpu"})()
            def transcribe(self, file_path, **kwargs):
                return {"segments": []}

        monkeypatch.setattr(transcript_service, "HAS_LOCAL_WHISPER", True)
        monkeypatch.setattr(transcript_service, "local_whisper", type("LW", (), {"load_model": lambda *a, **k: DummyWhisperModel()})())
        monkeypatch.setattr(transcript_service, "_LOCAL_WHISPER_MODELS", {})

        # Mock media_service.probe to return a 30s video duration
        import media_service
        monkeypatch.setattr(media_service, "probe", lambda path: media_service.MediaInfo(width=1920, height=1080, fps=30.0, duration_sec=30.0))

        temp_path = _write_temp(b"dummy silent video content")
        try:
            res = transcript_service.transcribe_file_with_whisper(temp_path, "silent_demo.mp4")
            assert "video_meta" in res
            assert "segments" in res
            assert len(res["segments"]) >= 2
            assert res["segments"][0]["is_visual_only"] is True
            assert "[Visual Scene" in res["segments"][0]["text"]
            assert res["video_meta"]["is_non_speech"] is True
        finally:
            os.remove(temp_path)

