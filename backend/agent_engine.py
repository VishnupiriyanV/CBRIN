"""
ReAct Agent Execution Engine for CreatorBrain Studio Copilot.
Handles multi-turn conversational reasoning and tool execution loop.
Includes robust fallback parsing for Llama-3 / Groq provider tool_use_failed errors.
"""

import json
import re
import uuid
from typing import Any, Dict, Iterator, List, Optional
import llm_client
import agent_tools

SYSTEM_PROMPT = """You are CreatorBrain Studio Copilot — an expert AI content strategist and producer integrated directly into the creator's workspace.

You help creators turn their long-form video/audio library into viral clips, multi-platform post campaigns, show notes, and repurposing packages.

Guidelines:
- When the user wants a video turned into a batch of content (posts, titles, show notes, captions), call generate_content_pack ONCE — it orchestrates everything. Do not call run_studio_tool separately after it.
- When a question could be answered from anywhere in the creator's library (a synthesis or "what have I said about X" question), prefer deep_research over a single search_vault call.
- Whenever you state a fact, quote, or claim that came from the creator's own content, cite it inline as [video title @ mm:ss] using the start_formatted/start_time you were given by the tool. Never state a timestamp you were not given by a tool.
- Always adhere strictly to the creator's Voice Profile and banned words if available (call get_creator_context when relevant).
- Keep your answers structured, actionable, and formatted in clean markdown.
"""

MAX_AGENT_TURNS = 8

FINAL_ANSWER_NUDGE = (
    "You've used all available tool turns. Give your final answer now, using only the "
    "tool results already gathered above. Do not attempt to call any more tools."
)


def _try_parse_failed_generation(error_str: str) -> Optional[tuple[str, Dict[str, Any]]]:
    """
    Parses malformed tool calls emitted by Llama-3 / Groq when `tool_use_failed` occurs.
    Example input string:
    "... 'failed_generation': '<function=search_vault {\"query\": \"grammar\", \"top_k\": 5}</function>\\n' ..."
    Returns (tool_name, args_dict) or None.
    """
    match = re.search(r'<function=([a-zA-Z0-9_]+)\s*(\{[\s\S]*?\})(?:</function>|>|\n|$)', error_str)
    if not match:
        match = re.search(r'<function=([a-zA-Z0-9_]+)>?\s*(\{[\s\S]*?\})', error_str)

    if match:
        tool_name = match.group(1).strip()
        args_raw = match.group(2).strip()
        try:
            args = json.loads(args_raw)
            return tool_name, args
        except json.JSONDecodeError:
            pass
    return None


def _is_rate_limit_error(err_msg: str) -> bool:
    lowered = err_msg.lower()
    return "rate_limit" in lowered or "429" in err_msg or "rate limit" in lowered


def _build_formatted_messages(
    messages: List[Dict[str, Any]], store: Any, video_id: Optional[str]
) -> List[Dict[str, Any]]:
    formatted_messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if video_id and store and hasattr(store, "videos"):
        video_meta = store.videos.get(video_id)
        if video_meta:
            ctx_msg = (
                f"Context note: The user currently has video_id '{video_id}' "
                f"('{video_meta.get('title', video_id)}') active in the Studio workspace."
            )
            formatted_messages.append({"role": "system", "content": ctx_msg})

    for m in messages:
        formatted_messages.append({
            "role": m.get("role", "user"),
            "content": m.get("content", "")
        })

    return formatted_messages


def _run_tool_call(tool_name: str, args: Dict[str, Any], store: Any) -> Dict[str, Any]:
    """Executes a tool and returns the execution-step record (tool/args/summary/data)."""
    tool_result = agent_tools.execute_tool(tool_name, args, store)
    summary = _format_step_summary(tool_name, args, tool_result)
    return {"tool": tool_name, "args": args, "summary": summary, "data": tool_result}


def run_agent_turn(
    messages: List[Dict[str, Any]],
    store: Any,
    video_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a single conversational agent turn, resolving tool calls in a ReAct loop.
    Supports native tool calling and automatic fallback parsing if Groq throws 400 tool_use_failed.
    """
    if not llm_client.is_configured():
        raise llm_client.LLMUnavailable("VAULT_LLM_API_KEY is not configured in .env.")

    client = llm_client._get_client()
    formatted_messages = _build_formatted_messages(messages, store, video_id)

    execution_steps: List[Dict[str, Any]] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "model": llm_client.MODEL}
    last_fallback_signature = None

    for turn in range(MAX_AGENT_TURNS):
        response = None
        fallback_tool_call = None

        try:
            response = client.chat.completions.create(
                model=llm_client.MODEL,
                messages=formatted_messages,
                tools=agent_tools.TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.3
            )
        except Exception as exc:
            err_msg = str(exc)
            parsed_fallback = _try_parse_failed_generation(err_msg)
            if parsed_fallback:
                fallback_tool_call = parsed_fallback
            elif _is_rate_limit_error(err_msg):
                try:
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=formatted_messages,
                        tools=agent_tools.TOOL_SCHEMAS,
                        tool_choice="auto",
                        temperature=0.3
                    )
                except Exception as fallback_exc:
                    raise llm_client.LLMUnavailable(f"LLM provider rate limit reached: {fallback_exc}")
            else:
                raise RuntimeError(f"LLM API request failed during agent loop: {exc}")

        if fallback_tool_call:
            tool_name, args = fallback_tool_call
            signature = (tool_name, json.dumps(args, sort_keys=True))
            if signature == last_fallback_signature:
                # The provider is emitting the identical malformed call again — stop
                # looping and fall through to the final-answer pass below instead of
                # burning every remaining turn on the same failure.
                break
            last_fallback_signature = signature

            step = _run_tool_call(tool_name, args, store)
            execution_steps.append(step)

            # Real tool-role message (not synthetic assistant/user text) so the next
            # turn sees this exactly like a native tool call, preserving coherence.
            synthetic_call_id = f"fallback_{uuid.uuid4().hex[:12]}"
            formatted_messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": synthetic_call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)}
                }]
            })
            formatted_messages.append({
                "role": "tool",
                "tool_call_id": synthetic_call_id,
                "name": tool_name,
                "content": json.dumps(step["data"], ensure_ascii=False)
            })
            continue

        if not response:
            break

        if hasattr(response, "usage") and response.usage:
            total_usage["prompt_tokens"] += response.usage.prompt_tokens or 0
            total_usage["completion_tokens"] += response.usage.completion_tokens or 0

        choice = response.choices[0]
        msg = choice.message

        if msg.tool_calls:
            formatted_messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    }
                    for tc in msg.tool_calls
                ]
            })

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}

                step = _run_tool_call(tool_name, args, store)
                execution_steps.append(step)

                formatted_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tool_name,
                    "content": json.dumps(step["data"], ensure_ascii=False)
                })
        else:
            return {
                "reply": msg.content or "Task completed.",
                "steps": execution_steps,
                "usage": total_usage
            }

    # Turns exhausted while still calling tools — force one final no-tools completion
    # from the gathered context instead of returning a generic placeholder.
    final_reply = "Task completed, but the agent ran out of turns before producing a final summary."
    try:
        final_response = client.chat.completions.create(
            model=llm_client.MODEL,
            messages=formatted_messages + [{"role": "user", "content": FINAL_ANSWER_NUDGE}],
            temperature=0.3
        )
        if hasattr(final_response, "usage") and final_response.usage:
            total_usage["prompt_tokens"] += final_response.usage.prompt_tokens or 0
            total_usage["completion_tokens"] += final_response.usage.completion_tokens or 0
        final_reply = final_response.choices[0].message.content or final_reply
    except Exception:
        pass

    return {
        "reply": final_reply,
        "steps": execution_steps,
        "usage": total_usage
    }


def run_agent_turn_stream(
    messages: List[Dict[str, Any]],
    store: Any,
    video_id: Optional[str] = None
) -> Iterator[Dict[str, Any]]:
    """
    Streaming counterpart to run_agent_turn. Yields typed event dicts:
      {"type": "token", "content": str}
      {"type": "tool_start", "tool": str, "args": dict}
      {"type": "tool_result", "tool": str, "args": dict, "summary": str, "data": dict}
      {"type": "step", "summary": str}
      {"type": "usage", "usage": dict}
      {"type": "done", "reply": str}
      {"type": "error", "message": str}
    Same ReAct loop and turn-exhaustion/fallback handling as run_agent_turn, but streams
    assistant text token-by-token and surfaces tool execution incrementally.
    """
    try:
        if not llm_client.is_configured():
            raise llm_client.LLMUnavailable("VAULT_LLM_API_KEY is not configured in .env.")

        client = llm_client._get_client()
        formatted_messages = _build_formatted_messages(messages, store, video_id)

        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "model": llm_client.MODEL}
        last_fallback_signature = None

        for turn in range(MAX_AGENT_TURNS):
            accumulated_content = ""
            tool_call_buffers: Dict[int, Dict[str, Any]] = {}
            finish_reason = None
            fallback_tool_call = None
            stream_usage = None

            try:
                stream = client.chat.completions.create(
                    model=llm_client.MODEL,
                    messages=formatted_messages,
                    tools=agent_tools.TOOL_SCHEMAS,
                    tool_choice="auto",
                    temperature=0.3,
                    stream=True
                )
                for chunk in stream:
                    if getattr(chunk, "usage", None):
                        stream_usage = chunk.usage
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    if delta and delta.content:
                        accumulated_content += delta.content
                        yield {"type": "token", "content": delta.content}
                    if delta and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            buf = tool_call_buffers.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                            if tc_delta.id:
                                buf["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    buf["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    buf["arguments"] += tc_delta.function.arguments
            except Exception as exc:
                err_msg = str(exc)
                parsed_fallback = _try_parse_failed_generation(err_msg)
                if parsed_fallback:
                    fallback_tool_call = parsed_fallback
                elif _is_rate_limit_error(err_msg):
                    yield {"type": "error", "message": "LLM provider rate limit reached — try again shortly."}
                    return
                else:
                    yield {"type": "error", "message": f"LLM API request failed during agent loop: {exc}"}
                    return

            if stream_usage:
                total_usage["prompt_tokens"] += getattr(stream_usage, "prompt_tokens", 0) or 0
                total_usage["completion_tokens"] += getattr(stream_usage, "completion_tokens", 0) or 0

            if fallback_tool_call:
                tool_name, args = fallback_tool_call
                signature = (tool_name, json.dumps(args, sort_keys=True))
                if signature == last_fallback_signature:
                    break
                last_fallback_signature = signature

                yield {"type": "tool_start", "tool": tool_name, "args": args}
                step = _run_tool_call(tool_name, args, store)
                yield {"type": "tool_result", **step}
                yield {"type": "step", "summary": step["summary"]}

                synthetic_call_id = f"fallback_{uuid.uuid4().hex[:12]}"
                formatted_messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": synthetic_call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)}
                    }]
                })
                formatted_messages.append({
                    "role": "tool",
                    "tool_call_id": synthetic_call_id,
                    "name": tool_name,
                    "content": json.dumps(step["data"], ensure_ascii=False)
                })
                continue

            if tool_call_buffers:
                tool_calls_sorted = [tool_call_buffers[i] for i in sorted(tool_call_buffers.keys())]
                formatted_messages.append({
                    "role": "assistant",
                    "content": accumulated_content or "",
                    "tool_calls": [
                        {
                            "id": tc["id"] or f"call_{uuid.uuid4().hex[:12]}",
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]}
                        }
                        for tc in tool_calls_sorted
                    ]
                })

                for tc in tool_calls_sorted:
                    tool_name = tc["name"]
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}

                    yield {"type": "tool_start", "tool": tool_name, "args": args}
                    step = _run_tool_call(tool_name, args, store)
                    yield {"type": "tool_result", **step}
                    yield {"type": "step", "summary": step["summary"]}

                    tool_call_id = tc["id"] or f"call_{uuid.uuid4().hex[:12]}"
                    formatted_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps(step["data"], ensure_ascii=False)
                    })
                continue

            # No tool calls this turn — the streamed content is the final reply.
            yield {"type": "usage", "usage": total_usage}
            yield {"type": "done", "reply": accumulated_content or "Task completed."}
            return

        # Turns exhausted while still calling tools — force a final no-tools pass.
        final_reply = "Task completed, but the agent ran out of turns before producing a final summary."
        try:
            final_stream = client.chat.completions.create(
                model=llm_client.MODEL,
                messages=formatted_messages + [{"role": "user", "content": FINAL_ANSWER_NUDGE}],
                temperature=0.3,
                stream=True
            )
            collected = ""
            for chunk in final_stream:
                if getattr(chunk, "usage", None):
                    total_usage["prompt_tokens"] += getattr(chunk.usage, "prompt_tokens", 0) or 0
                    total_usage["completion_tokens"] += getattr(chunk.usage, "completion_tokens", 0) or 0
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    piece = chunk.choices[0].delta.content
                    collected += piece
                    yield {"type": "token", "content": piece}
            final_reply = collected or final_reply
        except Exception:
            pass

        yield {"type": "usage", "usage": total_usage}
        yield {"type": "done", "reply": final_reply}
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}


def _format_step_summary(name: str, args: Dict[str, Any], result: Dict[str, Any]) -> str:
    """Generates human-readable summary for tool execution steps shown in UI."""
    if "error" in result:
        return f"Error executing {name}: {result['error']}"

    if name == "search_vault":
        count = result.get("count", 0)
        query = args.get("query", "")
        return f"Searched Vault for '{query}' ({count} matching passages found)"
    elif name == "deep_research":
        count = result.get("count", 0)
        query = args.get("query", "")
        return f"Researched '{query}' across the library ({count} fused passages found)"
    elif name == "list_library_videos":
        total = result.get("total_videos", 0)
        return f"Fetched creator video library ({total} videos indexed)"
    elif name == "get_video_transcript":
        sentences = result.get("sentence_count", 0)
        return f"Loaded video transcript ({sentences} sentences)"
    elif name == "extract_video_clips":
        clips = result.get("clips_found", 0)
        return f"Extracted {clips} narrative clip candidates with ENGINE"
    elif name == "run_studio_tool":
        tool_id = args.get("tool_id", "tool")
        return f"Executed Studio Tool '{tool_id}'"
    elif name == "generate_content_pack":
        n_clips = len(result.get("clips", []))
        n_errors = len(result.get("errors", {}))
        suffix = f", {n_errors} section(s) failed" if n_errors else ""
        return f"Generated content pack for '{result.get('video_title', 'video')}' ({n_clips} clips{suffix})"
    elif name == "get_creator_context":
        return "Loaded Voice Profile & Platform Rules"
    return f"Executed {name}"
