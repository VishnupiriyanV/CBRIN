"""
Tests for the search-answer validation layer (backend/answer_prompts.py).

The prompt asks the model for a short, cited answer, but a prompt constraint is a request,
not a guarantee — every rule that matters (in-range citations, word cap, refusal when the
quotes don't answer) is enforced here, after generation. These tests cover that enforcement,
because it is the only thing standing between a confidently-wrong model response and the UI.

Run with: python -m pytest backend/tests/test_answer_prompts.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import answer_prompts as ap  # noqa: E402


class TestValidate:
    def test_accepts_a_well_formed_answer(self):
        out = ap._validate({"answer": "They cancelled the lesson.", "citations": [1, 2], "sufficient": True}, 3)
        assert out["answer"] == "They cancelled the lesson."
        assert out["citations"] == [1, 2]
        assert out["truncated"] is False

    def test_rejects_when_model_says_insufficient(self):
        assert ap._validate({"answer": "Maybe something about rain.", "citations": [1], "sufficient": False}, 3) is None

    def test_rejects_empty_or_whitespace_answer(self):
        assert ap._validate({"answer": "", "citations": [1], "sufficient": True}, 3) is None
        assert ap._validate({"answer": "   ", "citations": [1], "sufficient": True}, 3) is None

    def test_drops_out_of_range_citations(self):
        # Model given 2 quotes cites [5] — that quote does not exist, and a marker for it
        # would scroll nowhere.
        out = ap._validate({"answer": "An answer.", "citations": [1, 5, 99], "sufficient": True}, 2)
        assert out["citations"] == [1]

    def test_rejects_when_every_citation_was_out_of_range(self):
        assert ap._validate({"answer": "An answer.", "citations": [7, 8], "sufficient": True}, 2) is None

    def test_rejects_uncited_answer(self):
        assert ap._validate({"answer": "An answer.", "citations": [], "sufficient": True}, 3) is None

    def test_ignores_non_integer_citations(self):
        out = ap._validate({"answer": "An answer.", "citations": ["1", None, "abc", 2.0], "sufficient": True}, 3)
        assert out["citations"] == [1, 2]

    def test_deduplicates_and_sorts_citations(self):
        out = ap._validate({"answer": "An answer.", "citations": [3, 1, 3, 1], "sufficient": True}, 3)
        assert out["citations"] == [1, 3]

    def test_enforces_word_cap_the_prompt_only_requests(self):
        long_answer = " ".join(f"word{i}" for i in range(200))
        out = ap._validate({"answer": long_answer, "citations": [1], "sufficient": True}, 1)
        assert out["truncated"] is True
        # +1 for the appended ellipsis token, which rides on the last word.
        assert len(out["answer"].split()) == ap.MAX_ANSWER_WORDS
        assert out["answer"].endswith("…")

    def test_rejects_non_dict(self):
        assert ap._validate(["not", "a", "dict"], 3) is None
        assert ap._validate(None, 3) is None

    def test_missing_citations_key_is_rejected_not_crashed(self):
        assert ap._validate({"answer": "An answer.", "sufficient": True}, 3) is None


class TestFormatQuotes:
    def test_numbers_quotes_from_one(self):
        rendered = ap.format_quotes([{"text": "first"}, {"text": "second"}])
        assert rendered == "[1] first\n[2] second"

    def test_caps_quote_count(self):
        results = [{"text": f"quote {i}"} for i in range(20)]
        rendered = ap.format_quotes(results)
        assert len(rendered.splitlines()) == ap.MAX_QUOTES_IN_PROMPT

    def test_truncates_individual_long_quotes(self):
        rendered = ap.format_quotes([{"text": "word " * 500}])
        assert len(rendered.split()) <= ap.MAX_QUOTE_WORDS + 1  # +1 for the [1] marker

    def test_handles_missing_text_field(self):
        assert ap.format_quotes([{}]) == "[1] "


class TestGenerateAnswerGuards:
    def test_no_llm_call_for_empty_query(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must not call the LLM when there is nothing to answer")
        monkeypatch.setattr(ap.llm_client, "complete_json_with_usage", _boom)

        assert ap.generate_answer("  ", [{"text": "something"}])[0] is None

    def test_no_llm_call_without_results(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must not call the LLM with no quotes to ground in")
        monkeypatch.setattr(ap.llm_client, "complete_json_with_usage", _boom)

        assert ap.generate_answer("a real question", [])[0] is None

    def test_citations_are_validated_against_quotes_actually_sent(self, monkeypatch):
        # 10 results exist, but only MAX_QUOTES_IN_PROMPT are sent — a citation beyond what
        # was sent must be dropped even though that index exists in the caller's list.
        monkeypatch.setattr(
            ap.llm_client, "complete_json_with_usage",
            lambda **k: ({"answer": "An answer.", "citations": [1, 9], "sufficient": True}, {}),
        )
        answer, _ = ap.generate_answer("q", [{"text": f"quote {i}"} for i in range(10)])
        assert answer["citations"] == [1]
