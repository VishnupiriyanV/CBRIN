"""
The upload endpoint builds a temp path for the incoming file. `file.filename` is the
multipart filename — entirely client-controlled, and Starlette passes it through verbatim.

It used to be sanitised with `filename.replace(" ", "_")` and joined onto the temp dir, which
is an arbitrary-path WRITE with attacker-chosen content: multipart/form-data is a
CORS-safelisted content type, so a page the user merely visits can POST here with no
preflight. It cannot read the response, but the write still lands.

Run with: python -m pytest backend/tests/test_upload_paths.py -v
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HOSTILE = [
    "../../../evil.mp4",
    r"..\..\..\evil.exe",
    "/etc/cron.d/evil",
    r"C:\Windows\System32\evil.dll",
    "....//....//evil.mp4",
]
BENIGN = ["normal.mp4", "a b.mp4", "no_ext", "x.MP4", "clip.final.v2.mov"]


def _temp_path_for(filename):
    """Mirrors main.py's upload path construction."""
    ext = os.path.splitext(filename)[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", ext or ""):
        ext = ""
    fd, path = tempfile.mkstemp(prefix="cbrin_upload_", suffix=ext, dir=tempfile.gettempdir())
    os.close(fd)
    return path


def _contained(path):
    root = os.path.realpath(tempfile.gettempdir())
    return os.path.commonpath([os.path.realpath(path), root]) == root


class TestUploadTempPath:
    def test_hostile_filenames_stay_inside_the_temp_directory(self):
        made = []
        try:
            for name in HOSTILE:
                path = _temp_path_for(name)
                made.append(path)
                assert _contained(path), f"{name!r} escaped to {path}"
        finally:
            for p in made:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def test_benign_filenames_still_work_and_keep_their_extension(self):
        made = []
        try:
            for name in BENIGN:
                path = _temp_path_for(name)
                made.append(path)
                assert _contained(path)
                expected = os.path.splitext(name)[1].lower()
                if re.fullmatch(r"\.[a-z0-9]{1,8}", expected or ""):
                    assert path.endswith(expected)
        finally:
            for p in made:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def test_concurrent_uploads_of_the_same_name_do_not_collide(self):
        # The old scheme derived the temp name from the filename alone, so two uploads of
        # "video.mp4" wrote to the same path and clobbered each other mid-copy.
        made = [_temp_path_for("video.mp4") for _ in range(20)]
        try:
            assert len(set(made)) == len(made)
        finally:
            for p in made:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def test_the_old_sanitiser_would_have_failed_these(self):
        # Pins why the change was needed rather than just that the new code passes.
        root = os.path.realpath(tempfile.gettempdir())
        for name in ["../../../evil.mp4", r"..\..\..\evil.exe"]:
            old = os.path.join(tempfile.gettempdir(), name.replace(" ", "_"))
            assert os.path.commonpath([os.path.realpath(old), root]) != root
