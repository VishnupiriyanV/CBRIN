"""
Tests for llm_throttle.py's shared RPM budget.

Covers the bug this module fixes: agent_engine's old inline _throttle_if_needed held its lock
across time.sleep(), serializing every concurrent agent request behind whichever single thread
happened to be sleeping. acquire() must release the lock before sleeping.

Run with: python -m pytest backend/tests/test_llm_throttle.py -v
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import llm_throttle  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_throttle():
    llm_throttle.reset()
    yield
    llm_throttle.reset()


class TestBucketKey:
    def test_same_host_shares_a_bucket_regardless_of_model(self):
        # VAULT_LLM_* and VAULT_TOOLS_LLM_* can point at the same provider account with
        # different model names — they must share ONE throttle bucket since they share one
        # real quota, not one bucket per model.
        a = llm_throttle.bucket_key("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")
        b = llm_throttle.bucket_key("https://api.groq.com/openai/v1", "llama-3.1-8b-instant")
        assert a == b

    def test_different_hosts_get_different_buckets(self):
        a = llm_throttle.bucket_key("https://api.groq.com/openai/v1", "m")
        b = llm_throttle.bucket_key("https://api.sambanova.ai/v1", "m")
        assert a != b


class TestRollingWindowAdmission:
    def test_admits_up_to_limit_without_sleeping(self, monkeypatch):
        fake_now = [1000.0]
        monkeypatch.setattr(llm_throttle.time, "time", lambda: fake_now[0])
        monkeypatch.setattr(llm_throttle.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("should not sleep")))

        for _ in range(5):
            slept = llm_throttle.acquire("bucket-a", rpm=5)
            assert slept == 0.0

    def test_blocks_the_6th_call_until_window_clears(self, monkeypatch):
        fake_now = [1000.0]

        def fake_time():
            return fake_now[0]

        def fake_sleep(seconds):
            fake_now[0] += seconds

        monkeypatch.setattr(llm_throttle.time, "time", fake_time)
        monkeypatch.setattr(llm_throttle.time, "sleep", fake_sleep)

        for _ in range(5):
            llm_throttle.acquire("bucket-b", rpm=5)

        slept = llm_throttle.acquire("bucket-b", rpm=5)
        assert slept > 0.0
        # The window advanced far enough that the bucket now shows exactly one call
        # (the one we just admitted) within the rolling 60s window.
        assert llm_throttle.snapshot()["bucket-b"] == 1

    def test_buckets_are_independent(self, monkeypatch):
        fake_now = [1000.0]
        monkeypatch.setattr(llm_throttle.time, "time", lambda: fake_now[0])
        monkeypatch.setattr(llm_throttle.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("should not sleep")))

        for _ in range(5):
            llm_throttle.acquire("bucket-c", rpm=5)
        # A DIFFERENT bucket at its own limit must not be affected by bucket-c being full.
        slept = llm_throttle.acquire("bucket-d", rpm=5)
        assert slept == 0.0


class TestSnapshotAndReset:
    def test_snapshot_reports_calls_in_window(self, monkeypatch):
        fake_now = [1000.0]
        monkeypatch.setattr(llm_throttle.time, "time", lambda: fake_now[0])
        for _ in range(3):
            llm_throttle.acquire("bucket-e", rpm=10)
        assert llm_throttle.snapshot()["bucket-e"] == 3

    def test_reset_clears_one_bucket_without_touching_others(self, monkeypatch):
        fake_now = [1000.0]
        monkeypatch.setattr(llm_throttle.time, "time", lambda: fake_now[0])
        llm_throttle.acquire("bucket-f", rpm=10)
        llm_throttle.acquire("bucket-g", rpm=10)
        llm_throttle.reset("bucket-f")
        snap = llm_throttle.snapshot()
        assert "bucket-f" not in snap or snap["bucket-f"] == 0
        assert snap["bucket-g"] == 1


class TestLockNotHeldAcrossSleep:
    def test_two_buckets_do_not_serialize_behind_one_sleeping_thread(self, monkeypatch):
        """acquire() must release its lock before sleeping. The old agent_engine
        implementation held its lock across time.sleep(), so ANY other caller's acquire() —
        even on a completely unrelated bucket — blocked behind whichever thread happened to
        be sleeping out its own window.

        fake_sleep blocks on a real threading.Event so the test can deterministically prove
        the lock was already released before the sleeping thread entered time.sleep(): if it
        weren't, the main thread's acquire() on a different bucket below would itself block
        trying to acquire _lock, and would only complete after release_sleep.set() — but the
        assertion runs and passes BEFORE that call, which is only possible if it never
        contended the lock at all."""
        fake_now = [1000.0]
        sleep_started = threading.Event()
        release_sleep = threading.Event()

        def fake_time():
            return fake_now[0]

        def fake_sleep(seconds):
            sleep_started.set()
            release_sleep.wait(timeout=2.0)
            fake_now[0] += seconds

        monkeypatch.setattr(llm_throttle.time, "time", fake_time)
        monkeypatch.setattr(llm_throttle.time, "sleep", fake_sleep)

        llm_throttle.acquire("slow-bucket", rpm=1)  # fills slow-bucket's budget of 1

        t = threading.Thread(target=lambda: llm_throttle.acquire("slow-bucket", rpm=1), daemon=True)
        t.start()
        assert sleep_started.wait(timeout=2.0), "sleeping thread never entered sleep"

        start = time.time()
        fast_slept = llm_throttle.acquire("fast-bucket", rpm=10)
        elapsed = time.time() - start

        release_sleep.set()
        t.join(timeout=2.0)

        assert fast_slept == 0.0
        assert elapsed < 0.5, "fast-bucket acquire() was blocked by the sleeping thread's lock"
