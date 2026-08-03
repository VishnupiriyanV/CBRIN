"""
Tests for media_service.py's ensure_media/probe (ENGINE-PLAN.md Phase 1). Network calls
(yt-dlp) are mocked — this suite never hits the real network.

Run with: python -m pytest backend/tests/test_media_service.py -v
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paths  # noqa: E402
import media_service as ms  # noqa: E402


class TestEnsureMediaCacheHit:
    def test_existing_local_file_is_returned_without_download(self):
        os.makedirs(paths.MEDIA_DIR, exist_ok=True)
        existing = os.path.join(paths.MEDIA_DIR, "local-abc123.mp4")
        with open(existing, 'wb') as f:
            f.write(b"fake-mp4-bytes")

        with patch("media_service._download_youtube") as mock_download:
            result = ms.ensure_media("local-abc123")
            assert result == existing
            mock_download.assert_not_called()

    def test_zero_byte_file_is_not_treated_as_cached(self):
        os.makedirs(paths.MEDIA_DIR, exist_ok=True)
        empty = os.path.join(paths.MEDIA_DIR, "yt-empty.mp4")
        with open(empty, 'wb') as f:
            pass  # zero bytes

        with patch("media_service._download_youtube", return_value="downloaded.mp4") as mock_download:
            result = ms.ensure_media("yt-empty", youtube_id="abc12345678")
            mock_download.assert_called_once()
            assert result == "downloaded.mp4"


class TestEnsureMediaNoSource:
    def test_no_local_file_and_no_youtube_id_raises_actionable_error(self):
        with pytest_raises_media_unavailable():
            ms.ensure_media("local-missing-file")


def pytest_raises_media_unavailable():
    import pytest
    return pytest.raises(ms.MediaUnavailable)


class TestYoutubeDownloadFailureIsActionable:
    def test_ytdlp_exception_raises_media_unavailable_with_context(self):
        fake_yt_dlp = MagicMock()
        fake_ydl_instance = MagicMock()
        fake_ydl_instance.download.side_effect = RuntimeError("HTTP Error 403: Forbidden")
        fake_yt_dlp.YoutubeDL.return_value.__enter__.return_value = fake_ydl_instance

        with patch.dict("sys.modules", {"yt_dlp": fake_yt_dlp}):
            with patch("media_service.ffmpeg_exe", return_value="C:/fake/ffmpeg.exe"):
                with pytest_raises_media_unavailable() as exc_info:
                    ms.ensure_media("yt-somevideo", youtube_id="dQw4w9WgXcQ")

        assert "yt-somevideo" in str(exc_info.value)
        assert "dQw4w9WgXcQ" in str(exc_info.value)
