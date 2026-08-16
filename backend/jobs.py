"""
In-process background job queue shared by ingestion (upload_transcribe / YouTube ingest —
see main.py's _run_upload_job / _run_youtube_ingest_job, IMPROVEMENT-PLAN.md 3.3) and ENGINE's
long-running work (Whisper word-timing re-transcription, ffmpeg renders). All of it used to
either block the request thread for as long as the underlying work took, or still does for
anything not yet migrated onto this queue.

ThreadPoolExecutor(max_workers=1): serial by design. Whisper, CLIP, and ffmpeg all saturate a
single CPU core; running them "in parallel" on a typical dev machine trades one slow success
for two slow failures fighting over the same cores.

STUDIO's text-generation tools are I/O-bound LLM calls, not CPU-bound media work — they must
not queue behind a 40-minute transcription. `submit()` accepts an optional `executor` so
callers with different concurrency needs (see studio_runner.py's own small pool) can opt out
of the single-worker media queue while still getting the same JobRecord/progress/persistence
machinery.
"""
import json
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

import paths
import atomic_io

MAX_RETAINED_JOBS = 200

_executor = ThreadPoolExecutor(max_workers=1)
_lock = threading.Lock()

# Serialises _save_all() end to end. _lock alone only guards the in-memory dict and the
# snapshot; the actual file write used to happen after releasing it, so two writers could
# snapshot in one order and write in the other, and the stale payload won. Demonstrated
# deterministically: a job that had completed persisted to disk as "running", and the next
# _init_from_disk() then reported that successful job as "interrupted by server restart".
#
# Two pools call report() concurrently — the single-worker media queue and studio_runner's
# own pool — so this is reachable in normal use, not just under stress.
#
# Lock order is always _write_lock then _lock, and nothing acquires them the other way round.
_write_lock = threading.Lock()
_jobs: Dict[str, "JobRecord"] = {}


@dataclass
class JobRecord:
    id: str
    kind: str
    video_id: Optional[str]
    status: str = "queued"  # queued | running | done | failed
    stage: str = ""
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _ensure_dir():
    os.makedirs(paths.DATA_DIR, exist_ok=True)


def _load_all() -> Dict[str, JobRecord]:
    if not os.path.exists(paths.JOBS_FILE):
        return {}
    try:
        with open(paths.JOBS_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return {jid: JobRecord(**data) for jid, data in raw.items()}
    except Exception:
        return {}


def _save_all():
    _ensure_dir()
    # Snapshot and write under the same lock, so writes reach disk in the order their
    # snapshots were taken. See the note on _write_lock.
    with _write_lock:
        with _lock:
            # Retain only the most recent MAX_RETAINED_JOBS records.
            ordered = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
            keep = ordered[:MAX_RETAINED_JOBS]
            _jobs.clear()
            for j in keep:
                _jobs[j.id] = j
            payload = {jid: j.to_dict() for jid, j in _jobs.items()}
        atomic_io.write_json(paths.JOBS_FILE, payload)


def _init_from_disk():
    """On process start, any job left 'running' or 'queued' from a prior process is dead —
    mark it failed rather than resurrecting it as in-flight forever."""
    loaded = _load_all()
    changed = False
    for job in loaded.values():
        if job.status in ("running", "queued"):
            job.status = "failed"
            job.error = "interrupted by server restart"
            job.updated_at = time.time()
            changed = True
    with _lock:
        _jobs.clear()
        _jobs.update(loaded)
    if changed:
        _save_all()


_init_from_disk()


def get(job_id: str) -> Optional[JobRecord]:
    with _lock:
        job = _jobs.get(job_id)
        return JobRecord(**job.to_dict()) if job else None


def list_for_video(video_id: str) -> List[JobRecord]:
    with _lock:
        return [JobRecord(**j.to_dict()) for j in _jobs.values() if j.video_id == video_id]


def list_all() -> List[JobRecord]:
    with _lock:
        return [JobRecord(**j.to_dict()) for j in _jobs.values()]


def submit(kind: str, fn: Callable[[Callable[[str, float, str], None]], Dict[str, Any]],
           video_id: Optional[str] = None, executor: Optional[ThreadPoolExecutor] = None) -> str:
    """
    Submit `fn` to run on a background worker thread. `fn` receives a `report`
    callback (stage: str, progress: float, message: str) it should call as it makes
    progress; its return value is stored as the job's `result` on success.

    `executor` defaults to the module's single-worker media queue. Pass a different
    ThreadPoolExecutor (e.g. studio_runner's) to run on a separate pool — JobRecord
    creation, progress reporting, and disk persistence are identical either way.
    """
    job_id = str(uuid.uuid4())
    job = JobRecord(id=job_id, kind=kind, video_id=video_id, status="queued")
    with _lock:
        _jobs[job_id] = job
    _save_all()

    def report(stage: str, progress: float, message: str = ""):
        with _lock:
            j = _jobs.get(job_id)
            if j is None:
                return
            j.stage = stage
            j.progress = max(0.0, min(1.0, progress))
            j.message = message
            j.status = "running"
            j.updated_at = time.time()
        _save_all()

    def _run():
        with _lock:
            j = _jobs.get(job_id)
            if j is None:
                return
            j.status = "running"
            j.updated_at = time.time()
        _save_all()
        try:
            result = fn(report)
            with _lock:
                j = _jobs.get(job_id)
                if j is not None:
                    j.status = "done"
                    j.progress = 1.0
                    j.result = result
                    j.updated_at = time.time()
            _save_all()
        except Exception as e:
            with _lock:
                j = _jobs.get(job_id)
                if j is not None:
                    j.status = "failed"
                    j.error = f"{e}"
                    j.message = traceback.format_exc(limit=3)
                    j.updated_at = time.time()
            _save_all()

    (executor or _executor).submit(_run)
    return job_id
