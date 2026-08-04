"""
Tests for tool_runs.py's STUDIO run-history store.

Run with: python -m pytest backend/tests/test_tool_runs.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tool_runs as tr  # noqa: E402


class TestRecordAndGet:
    def test_record_returns_retrievable_run(self):
        run_id = tr.record("repurposer", {"text": "hello"}, {"linkedin": {"hook": "hi"}})
        run = tr.get(run_id)
        assert run is not None
        assert run.tool_id == "repurposer"
        assert run.inputs == {"text": "hello"}
        assert run.output == {"linkedin": {"hook": "hi"}}

    def test_get_missing_run_returns_none(self):
        assert tr.get("nonexistent") is None


class TestListRuns:
    def test_list_filters_by_tool_id(self):
        tr.record("repurposer", {}, {})
        tr.record("titles", {}, {})
        tr.record("repurposer", {}, {})
        assert len(tr.list_runs(tool_id="repurposer")) == 2
        assert len(tr.list_runs(tool_id="titles")) == 1

    def test_list_most_recent_first(self):
        first = tr.record("repurposer", {}, {"n": 1})
        second = tr.record("repurposer", {}, {"n": 2})
        runs = tr.list_runs(tool_id="repurposer")
        assert runs[0].id == second
        assert runs[1].id == first

    def test_list_respects_limit(self):
        for i in range(5):
            tr.record("repurposer", {}, {"n": i})
        assert len(tr.list_runs(tool_id="repurposer", limit=2)) == 2


class TestDelete:
    def test_delete_removes_run(self):
        run_id = tr.record("repurposer", {}, {})
        assert tr.delete(run_id) is True
        assert tr.get(run_id) is None

    def test_delete_missing_run_returns_false(self):
        assert tr.delete("nonexistent") is False


class TestUpdateOutput:
    def test_update_output_overwrites_in_place(self):
        run_id = tr.record("repurposer", {}, {"linkedin": {"hook": "old"}})
        updated = tr.update_output(run_id, {"linkedin": {"hook": "new"}})
        assert updated.output == {"linkedin": {"hook": "new"}}
        assert tr.get(run_id).output == {"linkedin": {"hook": "new"}}

    def test_update_output_missing_run_returns_none(self):
        assert tr.update_output("nonexistent", {}) is None


class TestRetentionCap:
    def test_retains_only_most_recent_runs(self):
        original_cap = tr.MAX_RETAINED_RUNS
        tr.MAX_RETAINED_RUNS = 3
        try:
            for i in range(5):
                tr.record("repurposer", {}, {"n": i})
            all_runs = tr.list_runs(tool_id="repurposer", limit=100)
            assert len(all_runs) == 3
        finally:
            tr.MAX_RETAINED_RUNS = original_cap
