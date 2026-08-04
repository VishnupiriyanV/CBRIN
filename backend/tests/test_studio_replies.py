"""
Tests for the Reply Assistant's two-pass classify-then-reply pipeline. The central claim is
structural, not a prompt instruction: a flagged comment's text is never included in the
reply-generation call at all (creator-tools-integration-spec.md §4, guardrail 5 in the
STUDIO plan).

Run with: python -m pytest backend/tests/test_studio_replies.py -v
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import studio_prompts as sp  # noqa: E402

_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "model": "test-model"}


class TestFlaggedCommentsNeverReachReplyGeneration:
    def test_hostile_comment_gets_no_reply_and_is_excluded_from_second_call(self):
        comments = ["you are terrible and everything you make is garbage", "love this, thank you!"]
        classify_result = [
            {"index": 0, "flag": "hostile", "flag_reason": "attacking"},
            {"index": 1, "flag": None, "flag_reason": ""},
        ]
        reply_result = [{"index": 1, "suggested_reply": "Thank you so much!"}]

        with patch("studio_runner.call_llm", side_effect=[(classify_result, _USAGE), (reply_result, _USAGE)]) as mock_call:
            output, _u = sp._replies_run({"comments": comments}, "")

        assert mock_call.call_count == 2
        reply_call_user_arg = mock_call.call_args_list[1][0][1]
        assert "garbage" not in reply_call_user_arg  # the hostile comment's text never made it into the prompt

        replies = output["replies"]
        assert replies[0]["flag"] == "hostile"
        assert replies[0]["suggested_reply"] is None
        assert replies[1]["flag"] is None
        assert replies[1]["suggested_reply"] == "Thank you so much!"

    def test_all_comments_flagged_skips_the_reply_call_entirely(self):
        comments = ["a business inquiry about sponsorship"]
        classify_result = [{"index": 0, "flag": "business", "flag_reason": "sponsorship ask"}]

        with patch("studio_runner.call_llm", side_effect=[(classify_result, _USAGE)]) as mock_call:
            output, _u = sp._replies_run({"comments": comments}, "")

        assert mock_call.call_count == 1  # no reply-generation call made at all
        assert output["replies"][0]["suggested_reply"] is None

    def test_unknown_flag_value_defaults_to_none(self):
        comments = ["a normal comment"]
        classify_result = [{"index": 0, "flag": "not_a_real_flag", "flag_reason": ""}]
        reply_result = [{"index": 0, "suggested_reply": "thanks!"}]

        with patch("studio_runner.call_llm", side_effect=[(classify_result, _USAGE), (reply_result, _USAGE)]):
            output, _u = sp._replies_run({"comments": comments}, "")

        assert output["replies"][0]["flag"] is None
        assert output["replies"][0]["suggested_reply"] == "thanks!"

    def test_reply_indices_map_back_to_correct_original_comment(self):
        comments = ["flagged one", "safe one", "flagged two"]
        classify_result = [
            {"index": 0, "flag": "spam", "flag_reason": ""},
            {"index": 1, "flag": None, "flag_reason": ""},
            {"index": 2, "flag": "sensitive", "flag_reason": ""},
        ]
        reply_result = [{"index": 1, "suggested_reply": "reply to safe one"}]

        with patch("studio_runner.call_llm", side_effect=[(classify_result, _USAGE), (reply_result, _USAGE)]):
            output, _u = sp._replies_run({"comments": comments}, "")

        replies = output["replies"]
        assert replies[0]["suggested_reply"] is None
        assert replies[1]["suggested_reply"] == "reply to safe one"
        assert replies[2]["suggested_reply"] is None
