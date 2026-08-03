#!/usr/bin/env python
"""
Detect and (optionally) repair damage to backend/data/ caused by the test-suite data-clobber
bug fixed in ENGINE-PLAN.md Phase 0 (backend/tests/test_vector_store.py used to monkeypatch
only KEYFRAMES_DIR/MEDIA_DIR, leaving CHUNKS_FILE/VIDEOS_FILE/EMBEDDINGS_FILE pointed at the
real data dir — so running the test suite could silently overwrite the live library with
test fixtures, or leave chunks.json and the embedding .npy files out of sync).

Usage (from backend/):
    python scripts/repair_index.py            # report only, no changes
    python scripts/repair_index.py --rebuild   # drop orphan embedding rows, re-derive
                                                # videos.json from surviving chunks

This does NOT recover deleted content — if chunks.json was wiped by a test run, the original
transcripts are gone. --rebuild only makes the on-disk state internally consistent again
(chunks.json / embeddings.npy / visual_embeddings.npy / videos.json all agreeing with each
other) so the app boots cleanly instead of hitting a length-mismatch reindex on every start.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np  # noqa: E402
import paths  # noqa: E402


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ! Could not parse {path}: {e}")
        return default


def _load_npy(path):
    if not os.path.exists(path):
        return None
    try:
        return np.load(path)
    except Exception as e:
        print(f"  ! Could not load {path}: {e}")
        return None


def diagnose():
    chunks = _load_json(paths.CHUNKS_FILE, [])
    videos = _load_json(paths.VIDEOS_FILE, {})
    dense = _load_npy(paths.EMBEDDINGS_FILE)
    visual = _load_npy(paths.VISUAL_EMBEDDINGS_FILE)

    print(f"chunks.json:            {len(chunks)} chunk(s)")
    print(f"videos.json:            {len(videos)} video(s)")
    print(f"embeddings.npy:         {0 if dense is None else len(dense)} row(s)")
    print(f"visual_embeddings.npy:  {0 if visual is None else len(visual)} row(s)")

    chunk_video_ids = {c.get('video_id') for c in chunks if c.get('video_id')}
    orphan_video_ids = chunk_video_ids - set(videos.keys())
    missing_chunks_for_video = set(videos.keys()) - chunk_video_ids

    problems = []
    if dense is not None and len(dense) != len(chunks):
        problems.append(f"embeddings.npy has {len(dense)} rows but chunks.json has {len(chunks)} — out of sync")
    if visual is not None and len(visual) != len(chunks):
        problems.append(f"visual_embeddings.npy has {len(visual)} rows but chunks.json has {len(chunks)} — out of sync")
    if orphan_video_ids:
        problems.append(f"{len(orphan_video_ids)} video_id(s) appear in chunks.json but have no entry in videos.json: {sorted(orphan_video_ids)[:5]}")
    if missing_chunks_for_video:
        problems.append(f"{len(missing_chunks_for_video)} video(s) in videos.json have zero chunks: {sorted(missing_chunks_for_video)[:5]}")

    if not problems:
        print("\nNo inconsistencies detected.")
    else:
        print("\nProblems found:")
        for p in problems:
            print(f"  - {p}")

    return chunks, videos, dense, visual, problems


def rebuild(chunks, videos, dense, visual):
    print("\nRebuilding...")

    # Re-derive videos.json entries for orphan video_ids from surviving chunks, so at least
    # the library listing doesn't silently omit content that chunks.json still has.
    chunk_video_ids = {c.get('video_id') for c in chunks if c.get('video_id')}
    for vid in chunk_video_ids - set(videos.keys()):
        video_chunks = [c for c in chunks if c.get('video_id') == vid]
        first = video_chunks[0]
        last_end = max(c.get('end_sec', 0) for c in video_chunks)
        videos[vid] = {
            "id": vid,
            "youtube_id": first.get('youtube_id'),
            "is_local": first.get('is_local', False),
            "title": first.get('video_title', vid),
            "channel": first.get('channel', 'Creator Library'),
            "duration_formatted": "",
            "total_seconds": last_end,
            "thumbnail_url": first.get('thumbnail_url', ''),
            "uploaded_at": first.get('indexed_at', ''),
            "category": "Recovered",
            "status": "fully_indexed",
            "error_message": None,
        }
        print(f"  + re-derived videos.json entry for '{vid}' from {len(video_chunks)} surviving chunk(s)")

    # Drop videos.json entries with zero surviving chunks — nothing to serve for them.
    for vid in list(videos.keys()):
        if vid not in chunk_video_ids:
            del videos[vid]
            print(f"  - removed videos.json entry for '{vid}' (no surviving chunks)")

    # Embeddings out of sync with chunks: safest fix is to drop them and let the app's
    # normal reindex() path on next boot regenerate dense embeddings from chunks.json (and
    # regenerate visual embeddings lazily via reindex_visual_embeddings()).
    if dense is not None and len(dense) != len(chunks):
        os.remove(paths.EMBEDDINGS_FILE)
        print(f"  - removed embeddings.npy ({len(dense)} rows vs {len(chunks)} chunks) — will be regenerated on next boot")
    if visual is not None and len(visual) != len(chunks):
        os.remove(paths.VISUAL_EMBEDDINGS_FILE)
        print(f"  - removed visual_embeddings.npy ({len(visual)} rows vs {len(chunks)} chunks) — will be regenerated on next boot")

    with open(paths.VIDEOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(videos, f, indent=2, ensure_ascii=False)

    print("\nDone. Start the backend normally — it will reindex/reindex_visual_embeddings on boot.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="Apply fixes instead of just reporting them.")
    args = parser.parse_args()

    print(f"Inspecting {paths.DATA_DIR}\n")
    chunks, videos, dense, visual, problems = diagnose()

    if problems and args.rebuild:
        rebuild(chunks, videos, dense, visual)
    elif problems:
        print("\nRun with --rebuild to apply fixes.")


if __name__ == "__main__":
    main()
