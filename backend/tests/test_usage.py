"""
Tests for usage.py's input cap, hourly rate limit, and monthly token summary
(creator-tools-integration-spec.md §0.5 guardrails, reconciled with this app's no-auth model).

Run with: python -m pytest backend/tests/test_usage.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import usage  # noqa: E402


class TestInputWordCap:
    def test_under_cap_passes(self):
        usage.check_input_words(100)  # no raise

    def test_over_cap_raises(self):
        with pytest.raises(usage.InputTooLong):
            usage.check_input_words(usage.MAX_INPUT_WORDS + 1)

    def test_over_cap_message_names_the_limit(self):
        with pytest.raises(usage.InputTooLong) as exc:
            usage.check_input_words(20_000)
        assert str(usage.MAX_INPUT_WORDS) in str(exc.value)


class TestRateLimit:
    def test_under_limit_passes(self, ):
        now = 1_000_000.0
        for _ in range(usage.MAX_RUNS_PER_HOUR - 1):
            usage.record("repurposer", {"prompt_tokens": 10, "completion_tokens": 5}, now=now)
        usage.check_rate_limit(now=now)  # no raise

    def test_at_limit_raises(self):
        now = 2_000_000.0
        for _ in range(usage.MAX_RUNS_PER_HOUR):
            usage.record("repurposer", {"prompt_tokens": 10, "completion_tokens": 5}, now=now)
        with pytest.raises(usage.RateLimitExceeded):
            usage.check_rate_limit(now=now)

    def test_entries_older_than_an_hour_do_not_count(self):
        now = 3_000_000.0
        old = now - 7200  # 2 hours ago
        for _ in range(usage.MAX_RUNS_PER_HOUR):
            usage.record("repurposer", {"prompt_tokens": 10, "completion_tokens": 5}, now=old)
        usage.check_rate_limit(now=now)  # no raise — all entries are outside the trailing hour


class TestSummary:
    def test_summary_counts_recent_runs_and_tokens(self):
        now = 4_000_000.0
        usage.record("repurposer", {"prompt_tokens": 100, "completion_tokens": 50, "model": "llama"}, now=now)
        usage.record("titles", {"prompt_tokens": 200, "completion_tokens": 80, "model": "llama"}, now=now)
        result = usage.summary(now=now)
        assert result["runs_this_hour"] == 2
        assert result["runs_today"] == 2
        assert result["runs_this_month"] == 2
        assert result["tokens_in_month"] == 300
        assert result["tokens_out_month"] == 130
        assert result["model"] == "llama"
        assert result["limits"]["max_input_words"] == usage.MAX_INPUT_WORDS
        assert result["limits"]["max_runs_per_hour"] == usage.MAX_RUNS_PER_HOUR

    def test_summary_with_no_runs(self):
        result = usage.summary()
        assert result["runs_today"] == 0
        assert result["model"] == ""

    def test_old_runs_excluded_from_monthly_totals(self):
        now = 5_000_000.0
        old = now - (40 * 86400)  # 40 days ago
        usage.record("repurposer", {"prompt_tokens": 999, "completion_tokens": 999}, now=old)
        result = usage.summary(now=now)
        assert result["runs_this_month"] == 0
        assert result["tokens_in_month"] == 0


class TestConcurrentRecordingIsSafe:
    """record() is load-append-save with no lock, called from STUDIO_EXECUTOR's 2 workers and
    from /api/answer's request threads. Two failures were reproduced: concurrent writers each
    read the same N entries so the last save wins and spend vanishes; and on Windows two
    simultaneous os.replace() calls onto the same file raise PermissionError — already seen in
    production, which is why POST /api/answer wraps its record() in a try/except."""

    def test_concurrent_records_all_survive(self, monkeypatch):
        import threading
        import time

        real_load = usage._load_all

        def slow_load():
            entries = real_load()
            time.sleep(0.03)  # widen the read-then-write window
            return entries

        monkeypatch.setattr(usage, "_load_all", slow_load)

        errors = []

        def work(i):
            try:
                usage.record(f"tool{i}", {"prompt_tokens": 100, "completion_tokens": 10})
            except Exception as e:  # pragma: no cover - only on a regression
                errors.append(e)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        monkeypatch.setattr(usage, "_load_all", real_load)

        assert errors == [], f"concurrent writes raised: {errors}"
        summary = usage.summary()
        assert summary["runs_this_month"] == 5
        assert summary["tokens_in_month"] == 500
        assert summary["tokens_out_month"] == 50
