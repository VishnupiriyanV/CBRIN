"""
Tests for backend/jobs.py's background job queue (ENGINE-PLAN.md Phase 0).

Run with: python -m pytest backend/tests/test_jobs.py -v
"""
import importlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paths  # noqa: E402


def _fresh_jobs_module():
    """jobs.py reads paths.JOBS_FILE and loads state at import time via _init_from_disk(),
    so each test needs its own fresh import against the (already-redirected) tmp_path."""
    sys.modules.pop("jobs", None)
    return importlib.import_module("jobs")


def _wait_for(predicate, timeout=10.0):
    start = time.time()
    while time.time() - start < timeout:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class TestJobLifecycle:
    def test_stage_reporting_and_terminal_state(self):
        jobs = _fresh_jobs_module()

        seen_stages = []

        def work(report):
            report("stage-one", 0.3, "doing stage one")
            seen_stages.append("stage-one")
            report("stage-two", 0.7, "doing stage two")
            seen_stages.append("stage-two")
            return {"ok": True}

        job_id = jobs.submit("test-kind", work, video_id="vid-1")
        assert _wait_for(lambda: jobs.get(job_id).status in ("done", "failed"))

        record = jobs.get(job_id)
        assert record.status == "done"
        assert record.progress == 1.0
        assert record.result == {"ok": True}
        assert seen_stages == ["stage-one", "stage-two"]

    def test_submit_accepts_a_separate_executor(self):
        from concurrent.futures import ThreadPoolExecutor

        jobs = _fresh_jobs_module()
        own_pool = ThreadPoolExecutor(max_workers=1)
        try:
            job_id = jobs.submit("test-kind", lambda report: {"ok": True}, executor=own_pool)
            assert _wait_for(lambda: jobs.get(job_id).status in ("done", "failed"))
            assert jobs.get(job_id).status == "done"
        finally:
            own_pool.shutdown(wait=True)

    def test_failure_is_captured_not_raised(self):
        jobs = _fresh_jobs_module()

        def work(report):
            raise ValueError("boom")

        job_id = jobs.submit("test-kind", work)
        assert _wait_for(lambda: jobs.get(job_id).status in ("done", "failed"))

        record = jobs.get(job_id)
        assert record.status == "failed"
        assert "boom" in record.error

    def test_list_for_video_filters_by_video_id(self):
        jobs = _fresh_jobs_module()

        def noop(report):
            return {}

        jid_a = jobs.submit("k", noop, video_id="vid-a")
        jid_b = jobs.submit("k", noop, video_id="vid-b")
        assert _wait_for(lambda: jobs.get(jid_a).status == "done" and jobs.get(jid_b).status == "done")

        for_a = jobs.list_for_video("vid-a")
        assert all(j.video_id == "vid-a" for j in for_a)
        assert any(j.id == jid_a for j in for_a)
        assert not any(j.id == jid_b for j in for_a)

    def test_running_job_marked_failed_on_reimport(self):
        """Simulates a process restart while a job was mid-flight: a job persisted as
        'running' must come back as 'failed' rather than resurrected as in-flight forever."""
        jobs = _fresh_jobs_module()

        def slow(report):
            time.sleep(2)
            return {}

        job_id = jobs.submit("k", slow)
        assert _wait_for(lambda: jobs.get(job_id).status == "running", timeout=2)

        # Simulate restart: re-import the module, which runs _init_from_disk() again
        # against the same (redirected) JOBS_FILE.
        jobs2 = _fresh_jobs_module()
        record = jobs2.get(job_id)
        assert record.status == "failed"
        assert "restart" in record.error
