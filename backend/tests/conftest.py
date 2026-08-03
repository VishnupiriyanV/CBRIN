"""
Every test in this suite must write to a throwaway directory, never to the real
backend/data/. See ENGINE-PLAN.md Phase 0 / risk #1: test_vector_store.py used to
monkeypatch only KEYFRAMES_DIR/MEDIA_DIR and left CHUNKS_FILE/VIDEOS_FILE/EMBEDDINGS_FILE
pointed at the real data dir, so _save_to_disk() calls during tests silently corrupted the
live library.

paths.use_root() is the one seam that redirects every path constant at once (see
backend/paths.py). This fixture is autouse so no future test can forget to call it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
import paths  # noqa: E402

_REAL_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
_REAL_DATA_DIR = os.path.normcase(os.path.normpath(os.path.abspath(_REAL_DATA_DIR)))


@pytest.fixture(autouse=True)
def redirect_data(tmp_path):
    """Repoint every paths.* constant at a per-test tmp_path for the duration of the test."""
    original_root = paths.DATA_DIR
    paths.use_root(str(tmp_path))
    try:
        assert os.path.normcase(os.path.normpath(os.path.abspath(paths.DATA_DIR))) != _REAL_DATA_DIR, (
            "redirect_data fixture failed to move paths.DATA_DIR away from the real "
            "backend/data/ directory — refusing to let a test run against it."
        )
        yield
    finally:
        paths.use_root(original_root)


def test_redirect_data_guard_is_active(tmp_path):
    """
    Regression guard for risk #1: if a future refactor breaks the paths.use_root() seam
    (e.g. a module reverts to `from paths import CHUNKS_FILE`), this test fails loudly
    instead of tests silently writing through to the real library again.
    """
    assert os.path.normcase(os.path.normpath(os.path.abspath(paths.DATA_DIR))) != _REAL_DATA_DIR
    assert os.path.normcase(os.path.normpath(os.path.abspath(paths.CHUNKS_FILE))).startswith(
        os.path.normcase(os.path.normpath(os.path.abspath(str(tmp_path))))
    )
