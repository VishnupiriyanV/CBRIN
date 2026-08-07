"""
Run history for STUDIO tools (creator-tools-integration-spec.md §0.2 — "a big retention
lever, cheap to build, users expect it"). Same load-whole-file/write-whole-file/cap-at-N
shape as jobs.py, applied to completed tool outputs instead of in-flight job state.

Storing the full input alongside the output is what makes single-block regenerate
possible: POST /api/studio/regenerate looks up the run, re-derives just the requested
block using the same input, and doesn't require the creator to re-paste source text.
"""
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

import paths
import atomic_io

MAX_RETAINED_RUNS = 200


@dataclass
class ToolRun:
    id: str
    tool_id: str
    inputs: Dict[str, Any]
    output: Dict[str, Any]
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_all() -> Dict[str, ToolRun]:
    if not os.path.exists(paths.TOOL_RUNS_FILE):
        return {}
    try:
        with open(paths.TOOL_RUNS_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return {rid: ToolRun(**data) for rid, data in raw.items()}
    except Exception:
        return {}


def _save_all(runs: Dict[str, ToolRun]) -> Dict[str, ToolRun]:
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    ordered = sorted(runs.values(), key=lambda r: r.created_at, reverse=True)
    trimmed = {r.id: r for r in ordered[:MAX_RETAINED_RUNS]}
    payload = {rid: r.to_dict() for rid, r in trimmed.items()}
    atomic_io.write_json(paths.TOOL_RUNS_FILE, payload)
    return trimmed


def record(tool_id: str, inputs: Dict[str, Any], output: Dict[str, Any],
           meta: Optional[Dict[str, Any]] = None) -> str:
    run_id = str(uuid.uuid4())
    run = ToolRun(id=run_id, tool_id=tool_id, inputs=inputs, output=output, meta=meta or {})
    runs = _load_all()
    runs[run_id] = run
    _save_all(runs)
    return run_id


def get(run_id: str) -> Optional[ToolRun]:
    return _load_all().get(run_id)


def list_runs(tool_id: Optional[str] = None, limit: int = 50) -> List[ToolRun]:
    runs = list(_load_all().values())
    if tool_id:
        runs = [r for r in runs if r.tool_id == tool_id]
    runs.sort(key=lambda r: r.created_at, reverse=True)
    return runs[:limit]


def delete(run_id: str) -> bool:
    runs = _load_all()
    if run_id not in runs:
        return False
    del runs[run_id]
    _save_all(runs)
    return True


def update_output(run_id: str, output: Dict[str, Any]) -> Optional[ToolRun]:
    """Overwrite a run's output in place after a targeted single-block regenerate, so run
    history reflects the latest accepted version instead of accumulating one row per click."""
    runs = _load_all()
    run = runs.get(run_id)
    if run is None:
        return None
    run.output = output
    runs[run_id] = run
    _save_all(runs)
    return run
