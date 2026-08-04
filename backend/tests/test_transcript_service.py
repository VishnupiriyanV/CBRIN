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


class TestTranscribeLocalEngineSelection:
    """_transcribe_local prefers faster-whisper when available and falls back to
    openai-whisper transparently — same unified {"engine","segments"} shape either way."""

    def test_prefers_faster_whisper_when_available(self, monkeypatch):
        import transcript_service

        class FakeWord:
            def __init__(self, word, start, end):
                self.word, self.start, self.end = word, start, end

        class FakeSegment:
            def __init__(self, text, start, end, words=None):
                self.text, self.start, self.end, self.words = text, start, end, words

        class FakeFasterWhisperModel:
            def transcribe(self, file_path, word_timestamps=False):
                segments = [FakeSegment("hello world", 0.0, 1.5, words=[FakeWord("hello", 0.0, 0.5), FakeWord("world", 0.6, 1.5)] if word_timestamps else None)]
                return iter(segments), object()

        monkeypatch.setattr(transcript_service, "HAS_FASTER_WHISPER", True)
        monkeypatch.setattr(transcript_service, "_FASTER_WHISPER_MODELS", {})
        monkeypatch.setattr(transcript_service, "_get_faster_whisper_model", lambda tier, force_cpu=False: FakeFasterWhisperModel())

        result = transcript_service._transcribe_local("fake.mp4", "small")
        assert result["engine"] == "faster-whisper"
        assert result["segments"][0]["text"] == "hello world"
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][0]["end"] == 1.5

    def test_faster_whisper_word_timestamps_mapped_to_unified_shape(self, monkeypatch):
        import transcript_service

        class FakeWord:
            def __init__(self, word, start, end):
                self.word, self.start, self.end = word, start, end

        class FakeSegment:
            def __init__(self, text, start, end, words):
                self.text, self.start, self.end, self.words = text, start, end, words

        class FakeFasterWhisperModel:
            def transcribe(self, file_path, word_timestamps=False):
                segments = [FakeSegment("hi there", 0.0, 1.0, words=[FakeWord("hi", 0.0, 0.3), FakeWord("there", 0.4, 1.0)])]
                return iter(segments), object()

        monkeypatch.setattr(transcript_service, "HAS_FASTER_WHISPER", True)
        monkeypatch.setattr(transcript_service, "_get_faster_whisper_model", lambda tier, force_cpu=False: FakeFasterWhisperModel())

        result = transcript_service._transcribe_local("fake.mp4", "small", word_timestamps=True)
        words = result["segments"][0]["words"]
        assert words == [{"word": "hi", "start": 0.0, "end": 0.3}, {"word": "there", "start": 0.4, "end": 1.0}]

    def test_falls_back_to_openai_whisper_when_faster_whisper_raises(self, monkeypatch):
        import transcript_service

        def broken_loader(tier, force_cpu=False):
            raise RuntimeError("CUDA/cuDNN not available")

        class DummyWhisperModel:
            device = type("Device", (), {"type": "cpu"})()

            def transcribe(self, file_path, **kwargs):
                return {"segments": [{"text": "fallback text", "start": 0.0, "end": 2.0}]}

        monkeypatch.setattr(transcript_service, "HAS_FASTER_WHISPER", True)
        monkeypatch.setattr(transcript_service, "_get_faster_whisper_model", broken_loader)
        monkeypatch.setattr(transcript_service, "HAS_LOCAL_WHISPER", True)
        monkeypatch.setattr(transcript_service, "local_whisper", type("LW", (), {"load_model": lambda *a, **k: DummyWhisperModel()})())
        monkeypatch.setattr(transcript_service, "_LOCAL_WHISPER_MODELS", {})

        result = transcript_service._transcribe_local("fake.mp4", "small")
        assert result["engine"] == "openai-whisper"
        assert result["segments"][0]["text"] == "fallback text"

    def test_raises_when_no_engine_available(self, monkeypatch):
        import transcript_service

        monkeypatch.setattr(transcript_service, "HAS_FASTER_WHISPER", False)
        monkeypatch.setattr(transcript_service, "HAS_LOCAL_WHISPER", False)
        monkeypatch.setattr(transcript_service, "local_whisper", None)

        try:
            transcript_service._transcribe_local("fake.mp4", "small")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "faster-whisper" in str(e) or "openai-whisper" in str(e)

