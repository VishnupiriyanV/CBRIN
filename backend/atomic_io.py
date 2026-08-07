"""
Crash-safe writes for every persisted file in this backend.

Why this exists: every store here (chunks/videos index, tool runs, usage, jobs) used the
same pattern — `open(real_path, 'w')` then `json.dump` — which truncates the real file
before the new bytes exist. A crash, power loss, or Ctrl-C in that window leaves a
zero-length or half-written JSON file, and for chunks.json that is the entire searchable
library. `media_service._download_youtube` already used the temp-then-os.replace pattern
for downloads (see its comment on atomicity); this generalizes it to the data layer.

The guarantee: readers of `path` only ever see the complete previous version or the
complete new one, never a partial write. os.replace() is atomic on both POSIX and Windows
as long as source and destination are on the same filesystem — hence the temp file is
created in the destination's own directory rather than in the system temp dir.
"""
import json
import os
import tempfile
from typing import Any, Callable


def _write_atomic(path: str, write_body: Callable[[Any], None], binary: bool = False) -> None:
    """Write via a sibling temp file, fsync, then atomically rename over `path`.

    fsync before replace matters: without it the rename can reach disk before the data,
    which on an unclean shutdown yields an intact filename pointing at garbage — the exact
    corruption this is meant to prevent.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)

    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8", "newline": ""}
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp")
    os.close(fd)

    try:
        with open(tmp_path, mode, **kwargs) as f:
            write_body(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Leave `path` untouched on any failure, and don't orphan the temp file.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_json(path: str, obj: Any, indent: int = 2) -> None:
    """Serialize `obj` to `path` as UTF-8 JSON, atomically."""
    _write_atomic(path, lambda f: json.dump(obj, f, indent=indent, ensure_ascii=False))


def save_npy(path: str, array: Any) -> None:
    """np.save to `path`, atomically.

    np.save appends '.npy' when the filename lacks it, which would defeat the rename — so
    the array is written through the already-open handle instead of by filename.
    """
    import numpy as np
    _write_atomic(path, lambda f: np.save(f, array), binary=True)
