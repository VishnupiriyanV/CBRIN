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

    def test_no_file_actually_produced_raises_actionable_error(self):
        """yt-dlp's download() can return without raising even when nothing was written
        (e.g. every format candidate got filtered out) — must not be mistaken for success."""
        fake_yt_dlp = MagicMock()
        fake_ydl_instance = MagicMock()
        fake_ydl_instance.download.return_value = None  # "succeeds" but writes nothing
        fake_yt_dlp.YoutubeDL.return_value.__enter__.return_value = fake_ydl_instance

        with patch.dict("sys.modules", {"yt_dlp": fake_yt_dlp}):
            with patch("media_service.ffmpeg_exe", return_value="C:/fake/ffmpeg.exe"):
                with pytest_raises_media_unavailable() as exc_info:
                    ms.ensure_media("yt-nofile", youtube_id="dQw4w9WgXcQ")

        assert "yt-nofile" in str(exc_info.value)

    def test_merge_postprocessor_renamed_file_is_still_picked_up(self):
        """Regression for the real failure hit in production: yt-dlp's merge_output_format
        postprocessor renames the downloaded file by swapping its last extension segment, so
        a fixed "{video_id}.mp4.part" outtmpl could come out on disk as "{video_id}.mp4.mp4"
        instead — "yt-dlp reported success but produced no output file" even though a real
        file existed, just not at the literal path the old code assumed. Downloading into a
        throwaway temp dir and picking up whatever landed there (regardless of exact name)
        must still resolve to the expected final_path."""
        def fake_download(urls):
            # Simulate yt-dlp writing to *some* filename inside the outtmpl's directory,
            # deliberately not matching any literal path the caller might have assumed.
            outtmpl = fake_ydl_instance._last_opts["outtmpl"]
            tmp_dir = os.path.dirname(outtmpl)
            produced_name = "dQw4w9WgXcQ.mp4"  # yt-dlp's own %(id)s.%(ext)s naming
            with open(os.path.join(tmp_dir, produced_name), "wb") as f:
                f.write(b"fake-merged-mp4-bytes")

        fake_yt_dlp = MagicMock()
        fake_ydl_instance = MagicMock()
        fake_ydl_instance.download.side_effect = fake_download

        def capture_opts(opts):
            fake_ydl_instance._last_opts = opts
            return fake_ydl_instance

        fake_yt_dlp.YoutubeDL.side_effect = capture_opts
        fake_ydl_instance.__enter__ = MagicMock(return_value=fake_ydl_instance)
        fake_ydl_instance.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"yt_dlp": fake_yt_dlp}):
            with patch("media_service.ffmpeg_exe", return_value="C:/fake/ffmpeg.exe"):
                result = ms.ensure_media("yt-dQw4w9WgXcQ", youtube_id="dQw4w9WgXcQ")

        assert result == os.path.join(paths.MEDIA_DIR, "yt-dQw4w9WgXcQ.mp4")
        assert os.path.exists(result)
        with open(result, "rb") as f:
            assert f.read() == b"fake-merged-mp4-bytes"
        # The temp download directory must not be left behind.
        leftover_tmp_dirs = [
            name for name in os.listdir(paths.MEDIA_DIR)
            if name.startswith("ytdl-yt-dQw4w9WgXcQ-")
        ]
        assert leftover_tmp_dirs == []
