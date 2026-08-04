"""
Tests for agent_engine.py's ReAct loop hardening:
  1. Turn exhaustion used to return a generic "Execution finished." placeholder, discarding
     any gathered context — it should now force a real final-answer completion.
  2. The tool_use_failed fallback parser used to append synthetic assistant/user text
     messages instead of a proper role="tool" message.
  3. run_agent_turn_stream should stream tokens and end with a "done" event carrying the
     full reply.

Run with: python -m pytest backend/tests/test_agent_engine.py -v
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent_engine  # noqa: E402


class FakeStore:
    videos = {}
    chunks = []


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message, usage=None):
        self.choices = [FakeChoice(message)]
        self.usage = usage


class FakeUsage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeStreamChoice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class FakeChunk:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


@pytest.fixture(autouse=True)
def configured_llm():
    with patch.object(agent_engine.llm_client, "is_configured", return_value=True):
        yield


class TestTurnExhaustion:
    def test_forces_real_final_answer_instead_of_placeholder(self):
        # Every turn the model calls a tool, forever — simulates a model that never stops
        # tool-calling within MAX_AGENT_TURNS.
        tool_call_response = FakeResponse(
            FakeMessage(content=None, tool_calls=[FakeToolCall("call_1", "list_library_videos", "{}")]),
            usage=FakeUsage(10, 5),
        )
        final_response = FakeResponse(FakeMessage(content="Here is your real summary."))

        mock_client = MagicMock()
        # MAX_AGENT_TURNS tool-calling responses, then the final no-tools nudge call.
        mock_client.chat.completions.create.side_effect = (
            [tool_call_response] * agent_engine.MAX_AGENT_TURNS + [final_response]
        )

        with patch.object(agent_engine.llm_client, "_get_client", return_value=mock_client), \
             patch.object(agent_engine.agent_tools, "execute_tool", return_value={"total_videos": 0, "videos": []}):
            result = agent_engine.run_agent_turn(messages=[{"role": "user", "content": "hi"}], store=FakeStore())

        assert result["reply"] == "Here is your real summary."
        assert result["reply"] != "Execution finished."
        assert mock_client.chat.completions.create.call_count == agent_engine.MAX_AGENT_TURNS + 1


class TestFallbackParserUsesProperToolMessage:
    def test_fallback_tool_call_appends_role_tool_message(self):
        failed_gen_error = Exception(
            "Error: tool_use_failed. 'failed_generation': "
            '\'<function=search_vault {"query": "grammar", "top_k": 5}</function>\\n\''
        )
        final_response = FakeResponse(FakeMessage(content="Found it."))

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [failed_gen_error, final_response]

        with patch.object(agent_engine.llm_client, "_get_client", return_value=mock_client), \
             patch.object(agent_engine.agent_tools, "execute_tool", return_value={"count": 1, "results": []}):
            result = agent_engine.run_agent_turn(messages=[{"role": "user", "content": "search for grammar"}], store=FakeStore())

        assert result["reply"] == "Found it."

        # Inspect the messages passed into the second (recovery) call.
        _, second_call_kwargs = mock_client.chat.completions.create.call_args_list[1]
        messages = second_call_kwargs["messages"]
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["name"] == "search_vault"
        assert json.loads(tool_messages[0]["content"]) == {"count": 1, "results": []}

        assistant_messages_with_calls = [m for m in messages if m.get("role") == "assistant" and m.get("tool_calls")]
        assert len(assistant_messages_with_calls) == 1
        assert assistant_messages_with_calls[0]["tool_calls"][0]["id"] == tool_messages[0]["tool_call_id"]

        # No synthetic plain user/assistant text messages should exist for this recovery.
        synthetic_user_msgs = [
            m for m in messages
            if m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].startswith("Tool '")
        ]
        assert synthetic_user_msgs == []

    def test_identical_repeated_failure_does_not_loop_forever(self):
        failed_gen_error = Exception(
            "Error: tool_use_failed. 'failed_generation': "
            '\'<function=search_vault {"query": "same"}</function>\\n\''
        )
        final_response = FakeResponse(FakeMessage(content="Gave up gracefully."))

        mock_client = MagicMock()
        # Same failure twice (turn 0, turn 1) breaks the loop; the 3rd call is the final
        # no-tools nudge, which succeeds. If the loop didn't break early, this side_effect
        # queue would run dry well before MAX_AGENT_TURNS and raise StopIteration instead.
        mock_client.chat.completions.create.side_effect = [failed_gen_error, failed_gen_error, final_response]

        with patch.object(agent_engine.llm_client, "_get_client", return_value=mock_client), \
             patch.object(agent_engine.agent_tools, "execute_tool", return_value={"count": 0, "results": []}):
            result = agent_engine.run_agent_turn(messages=[{"role": "user", "content": "search"}], store=FakeStore())

        assert result["reply"] == "Gave up gracefully."
        # Should have broken after the 2nd identical failure, not burned all MAX_AGENT_TURNS.
        assert mock_client.chat.completions.create.call_count == 3


class TestRateLimitHandling:
    """A direct Groq 429 bypasses llm_client's own retry/LLMUnavailable wrapping (agent_engine
    calls client.chat.completions.create directly) — without this, it fell through to a bare
    RuntimeError, which main.py maps to a generic 500 instead of the 503 'try again shortly'
    it deserves."""

    def test_buffered_turn_raises_llm_unavailable_not_runtime_error(self):
        rate_limit_error = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
            "`llama-3.3-70b-versatile`', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = rate_limit_error

        with patch.object(agent_engine.llm_client, "_get_client", return_value=mock_client):
            with pytest.raises(agent_engine.llm_client.LLMUnavailable):
                agent_engine.run_agent_turn(messages=[{"role": "user", "content": "hi"}], store=FakeStore())

    def test_streaming_turn_yields_clean_error_event_not_raw_exception_text(self):
        rate_limit_error = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit reached', 'code': 'rate_limit_exceeded'}}"
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = rate_limit_error

        with patch.object(agent_engine.llm_client, "_get_client", return_value=mock_client):
            events = list(agent_engine.run_agent_turn_stream(messages=[{"role": "user", "content": "hi"}], store=FakeStore()))

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "rate limit" in events[0]["message"].lower()
        assert "rate_limit_exceeded" not in events[0]["message"]  # no raw provider JSON leaking through


class TestStreaming:
    def test_streams_tokens_then_emits_done_with_full_reply(self):
        chunks = [
            FakeChunk(choices=[FakeStreamChoice(delta=FakeDelta(content="Hel"), finish_reason=None)]),
            FakeChunk(choices=[FakeStreamChoice(delta=FakeDelta(content="lo!"), finish_reason=None)]),
            FakeChunk(choices=[FakeStreamChoice(delta=FakeDelta(content=None), finish_reason="stop")]),
        ]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter(chunks)

        with patch.object(agent_engine.llm_client, "_get_client", return_value=mock_client):
            events = list(agent_engine.run_agent_turn_stream(messages=[{"role": "user", "content": "hi"}], store=FakeStore()))

        token_events = [e for e in events if e["type"] == "token"]
        assert "".join(e["content"] for e in token_events) == "Hello!"

        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["reply"] == "Hello!"

    def test_streams_tool_calls_and_result_events(self):
        tool_call_delta = MagicMock()
        tool_call_delta.index = 0
        tool_call_delta.id = "call_1"
        tool_call_delta.function = MagicMock(name="list_library_videos")
        tool_call_delta.function.name = "list_library_videos"
        tool_call_delta.function.arguments = "{}"

        first_turn_chunks = [
            FakeChunk(choices=[FakeStreamChoice(
                delta=FakeDelta(content=None, tool_calls=[tool_call_delta]), finish_reason=None
            )]),
            FakeChunk(choices=[FakeStreamChoice(delta=FakeDelta(content=None), finish_reason="tool_calls")]),
        ]
        second_turn_chunks = [
            FakeChunk(choices=[FakeStreamChoice(delta=FakeDelta(content="Done."), finish_reason=None)]),
            FakeChunk(choices=[FakeStreamChoice(delta=FakeDelta(content=None), finish_reason="stop")]),
        ]

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [iter(first_turn_chunks), iter(second_turn_chunks)]

        with patch.object(agent_engine.llm_client, "_get_client", return_value=mock_client), \
             patch.object(agent_engine.agent_tools, "execute_tool", return_value={"total_videos": 2, "videos": []}):
            events = list(agent_engine.run_agent_turn_stream(messages=[{"role": "user", "content": "list my videos"}], store=FakeStore()))

        assert any(e["type"] == "tool_start" and e["tool"] == "list_library_videos" for e in events)
        assert any(e["type"] == "tool_result" and e["tool"] == "list_library_videos" for e in events)
        assert events[-1] == {"type": "done", "reply": "Done."}
