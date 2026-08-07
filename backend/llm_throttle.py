"""
Shared RPM (requests-per-minute) throttle for LLM calls, keyed by provider endpoint bucket
rather than by caller. VAULT_LLM_* and VAULT_TOOLS_LLM_* can point at the same provider
account (e.g. both set to Groq), which means they share one real quota even though they are
two separate config slots — keying the bucket on the base_url host means both automatically
share one throttle budget instead of each independently assuming it owns the full budget.

Split out of agent_engine.py (whose inline _throttle_if_needed held its lock across
time.sleep(), serializing every concurrent agent request behind whichever thread happened to
be sleeping) so narrative_engine's per-window beat-extraction loop can share the same pacing
without narrative_engine and agent_engine importing each other. Stdlib only — no import of
llm_client — so both llm_client and agent_engine can depend on this without a cycle.
"""
import os
import threading
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

DEFAULT_RPM = 25  # Groq free tier is 30 req/min; stay comfortably under it.

_lock = threading.Lock()
_calls: Dict[str, List[float]] = {}


def _configured_rpm() -> int:
    raw = os.getenv("VAULT_LLM_RPM")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_RPM


def bucket_key(base_url: str, model: str) -> str:
    """Providers meter per account against an endpoint, not per model — bucket on the host so
    VAULT_LLM_* and VAULT_TOOLS_LLM_* pointed at the same provider automatically share one
    budget instead of each assuming it owns the full quota."""
    host = urlparse(base_url or "").netloc or (base_url or "unknown")
    return host.lower()


def acquire(bucket: str, rpm: Optional[int] = None) -> float:
    """Block until another call on `bucket` won't exceed `rpm` calls in a rolling 60s window.
    Returns the total seconds slept (0.0 if admitted immediately).

    The lock is held ONLY for bookkeeping — never across time.sleep(). Holding it across sleep
    is what the old agent_engine._throttle_if_needed did, which meant every concurrent agent
    request serialized behind whichever single thread was currently sleeping."""
    limit = rpm or _configured_rpm()
    slept = 0.0
    while True:
        with _lock:
            times = _calls.setdefault(bucket, [])
            now = time.time()
            window_start = now - 60.0
            while times and times[0] < window_start:
                times.pop(0)
            if len(times) < limit:
                times.append(now)
                return slept
            wait = 60.0 - (now - times[0]) + 0.05
        if wait > 0:
            time.sleep(wait)
            slept += wait


def snapshot() -> Dict[str, int]:
    """Calls currently counted in each bucket's rolling window — for /api/health or tests."""
    with _lock:
        now = time.time()
        window_start = now - 60.0
        return {b: len([t for t in times if t >= window_start]) for b, times in _calls.items()}


def reset(bucket: Optional[str] = None) -> None:
    """Test seam — clears one bucket's call history, or all of them."""
    with _lock:
        if bucket is None:
            _calls.clear()
        else:
            _calls.pop(bucket, None)
