"""
Single-user usage meter for STUDIO — the reconciliation of
creator-tools-integration-spec.md §0.5's guardrails ("hard input cap ~15k words, rate limit
per user per hour, and a monthly spend alert on the API key") with the fact that this app
has no accounts (backend/main.py has zero auth anywhere; every route is open). There is
exactly one creator using this install, so "per user" collapses to "per install" — a flat
JSON log of every run, no user_id column.

No billing follows from this. It exists so cost is visible (studio_runner.py checks the
caps before spending a call; GET /api/studio/usage feeds a header badge), not so it can be
metered against a plan.
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

import paths

MAX_INPUT_WORDS = 15_000
MAX_RUNS_PER_HOUR = 60
MAX_RETAINED_ENTRIES = 5_000

_HOUR = 3600.0
_DAY = 86400.0
_MONTH = 30 * _DAY


class InputTooLong(Exception):
    """Raised before any LLM call is made — the whole point is to reject oversized input
    for free, not after paying for a partial generation."""


class RateLimitExceeded(Exception):
    """More than MAX_RUNS_PER_HOUR runs recorded in the trailing 60 minutes."""


def _load_all() -> List[Dict[str, Any]]:
    if not os.path.exists(paths.TOOL_USAGE_FILE):
        return []
    try:
        with open(paths.TOOL_USAGE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_all(entries: List[Dict[str, Any]]) -> None:
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    entries = sorted(entries, key=lambda e: e.get("ts", 0))[-MAX_RETAINED_ENTRIES:]
    with open(paths.TOOL_USAGE_FILE, 'w', encoding='utf-8') as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def check_input_words(word_count: int) -> None:
    if word_count > MAX_INPUT_WORDS:
        raise InputTooLong(
            f"Input is {word_count} words; STUDIO's cap is {MAX_INPUT_WORDS}. Trim it and try again."
        )


def check_rate_limit(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    entries = _load_all()
    recent = [e for e in entries if e.get("ts", 0) >= now - _HOUR]
    if len(recent) >= MAX_RUNS_PER_HOUR:
        raise RateLimitExceeded(
            f"Rate limit reached: {MAX_RUNS_PER_HOUR} STUDIO runs per hour. Try again shortly."
        )


def record(tool_id: str, usage: Dict[str, Any], now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    entries = _load_all()
    entries.append({
        "ts": now,
        "tool_id": tool_id,
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "model": usage.get("model", ""),
    })
    _save_all(entries)


def summary(now: Optional[float] = None) -> Dict[str, Any]:
    now = now if now is not None else time.time()
    entries = _load_all()

    def _since(cutoff: float) -> List[Dict[str, Any]]:
        return [e for e in entries if e.get("ts", 0) >= cutoff]

    month_entries = _since(now - _MONTH)
    model = entries[-1]["model"] if entries else ""

    return {
        "runs_this_hour": len(_since(now - _HOUR)),
        "runs_today": len(_since(now - _DAY)),
        "runs_this_month": len(month_entries),
        "tokens_in_month": sum(e.get("prompt_tokens", 0) for e in month_entries),
        "tokens_out_month": sum(e.get("completion_tokens", 0) for e in month_entries),
        "model": model,
        "limits": {
            "max_input_words": MAX_INPUT_WORDS,
            "max_runs_per_hour": MAX_RUNS_PER_HOUR,
        },
    }
