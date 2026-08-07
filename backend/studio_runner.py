"""
Shared pipeline every STUDIO tool runs through: input-cap + rate-limit checks, LLM calls
via llm_client, generic guardrail helpers (banned words, source-verification, windowing),
and usage/run-history recording. Individual tool logic (prompts, schemas, how many LLM
calls, tool-specific validators) lives in studio_prompts.py as a ToolSpec — this module
owns everything a ToolSpec shouldn't have to repeat.

STUDIO runs on its own small executor (STUDIO_EXECUTOR), not jobs.py's single-worker media
queue: a 5-second LLM call must never queue behind a 40-minute Whisper transcription. Every
run still goes through jobs.py for a uniform job/progress/history code path — main.py calls
`jobs.submit(..., executor=studio_runner.STUDIO_EXECUTOR)`.
"""
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

import llm_client
import tool_runs
import transcript_parser
import usage
import voice_profile

STUDIO_EXECUTOR = ThreadPoolExecutor(max_workers=2)

# Mirrors narrative_engine.py's windowing constants — long pasted transcripts exceed
# comfortable context the same way long videos do, so window with overlap and merge
# rather than truncate.
WINDOW_SENTENCE_COUNT = 60
WINDOW_OVERLAP = 10
WORD_COUNT_WINDOW_THRESHOLD = 6000


class StudioError(Exception):
    """Base for errors that should surface as a clean HTTP response rather than a 500.
    `status_code` lets main.py map this straight onto a FastAPI HTTPException."""
    status_code = 400


class InputRejected(StudioError):
    status_code = 422


class RateLimited(StudioError):
    status_code = 429


class LLMNotConfigured(StudioError):
    status_code = 503


def _translate(exc: Exception) -> StudioError:
    if isinstance(exc, usage.InputTooLong):
        return InputRejected(str(exc))
    if isinstance(exc, usage.RateLimitExceeded):
        return RateLimited(str(exc))
    if isinstance(exc, llm_client.LLMUnavailable):
        return LLMNotConfigured(str(exc))
    if isinstance(exc, StudioError):
        return exc
    return StudioError(str(exc))


def call_llm(system: str, user: str, schema: Dict[str, Any], temperature: float = 0.2,
             max_tokens: Optional[int] = None) -> Tuple[Any, Dict[str, Any]]:
    """Thin wrapper so ToolSpec run_fns never import llm_client directly — keeps the
    provider seam in one place and translates LLMUnavailable into a StudioError."""
    try:
        return llm_client.complete_json_with_usage(
            system, user, schema, temperature=temperature, max_tokens=max_tokens
        )
    except llm_client.LLMUnavailable as e:
        raise LLMNotConfigured(str(e)) from e


def merge_usage(*usages: Dict[str, Any]) -> Dict[str, Any]:
    prompt = sum(u.get("prompt_tokens", 0) for u in usages)
    completion = sum(u.get("completion_tokens", 0) for u in usages)
    model = next((u.get("model") for u in usages if u.get("model")), "")
    return {"prompt_tokens": prompt, "completion_tokens": completion, "model": model}


def word_count(text: str) -> int:
    return len((text or "").split())


def normalize_for_match(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').lower()).strip()


def appears_in_source(candidate: str, source: str) -> bool:
    """Normalized substring check — same technique narrative_engine._validate_and_clean_beats
    uses to verify a quotable_line actually appears in the transcript before trusting it.
    Reused here for guardrail 8 (no invented facts, stats, or quotes): a claim only survives
    if it can be found, whitespace/case-insensitively, in the source text."""
    candidate = (candidate or '').strip()
    if not candidate:
        return False
    return normalize_for_match(candidate) in normalize_for_match(source)


def collect_strings(obj: Any) -> List[str]:
    out: List[str] = []
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(collect_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(collect_strings(v))
    elif isinstance(obj, str):
        out.append(obj)
    return out


def map_strings(obj: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(obj, dict):
        return {k: map_strings(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [map_strings(v, fn) for v in obj]
    if isinstance(obj, str):
        return fn(obj)
    return obj


def strip_banned_words(text: str, banned_words: List[str]) -> Tuple[str, List[str]]:
    """Case-insensitive whole-phrase removal. Returns (cleaned_text, phrases_found)."""
    found: List[str] = []
    cleaned = text
    for phrase in banned_words:
        if not phrase:
            continue
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        if pattern.search(cleaned):
            found.append(phrase)
            cleaned = pattern.sub('', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned, found


def enforce_banned_words(output: Any, banned_words: List[str]) -> Tuple[Any, List[str]]:
    """Walks every string leaf in `output` and strips any banned phrase found (guardrail 9,
    creator-tools-integration-spec.md §0.3). Applied centrally in run_tool()/regenerate_block()
    after every tool's run_fn returns, so no individual tool has to remember to call this."""
    if not banned_words:
        return output, []
    all_found: List[str] = []

    def _clean(s: str) -> str:
        cleaned, found = strip_banned_words(s, banned_words)
        all_found.extend(found)
        return cleaned

    cleaned_output = map_strings(output, _clean)
    return cleaned_output, sorted(set(all_found))


def format_timestamp(seconds: Optional[float]) -> Optional[str]:
    if seconds is None:
        return None
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_sentences(sentences: List[Dict[str, Any]]) -> str:
    """Numbered-line format the model must echo indices back against — the anti-hallucination
    anchor narrative_engine.py uses for beat extraction (`[idx] timestamp text`), reused here
    for show notes / moment finding so every displayed time is derived from real cue data the
    backend already has, never invented by the model (guardrail 1)."""
    lines = []
    for s in sentences:
        idx = s.get("sentence_idx")
        ts = format_timestamp(s.get("start_sec")) or "--:--"
        lines.append(f"[{idx}] {ts}  {s.get('text', '')}")
    return "\n".join(lines)


def window_sentences(sentences: List[Dict[str, Any]], window_size: int = WINDOW_SENTENCE_COUNT,
                      overlap: int = WINDOW_OVERLAP) -> List[List[Dict[str, Any]]]:
    """Splits a sentence-index list into overlapping windows once total length passes
    WORD_COUNT_WINDOW_THRESHOLD, mirroring narrative_engine.py's windowing. Returns a single
    window unchanged when the input is short enough."""
    total_words = sum(word_count(s.get("text", "")) for s in sentences)
    if total_words <= WORD_COUNT_WINDOW_THRESHOLD or len(sentences) <= window_size:
        return [sentences]

    windows = []
    start, n = 0, len(sentences)
    while start < n:
        end = min(start + window_size, n)
        windows.append(sentences[start:end])
        if end >= n:
            break
        start = end - overlap
    return windows


def pseudo_segment_plain_text(text: str, chunk_words: int = 120) -> List[Dict[str, Any]]:
    """Chapter-sized chunks for plain (untimed) pasted text — used only when a transcript
    has no timestamps at all. Each chunk carries None for start/end (guardrail 1: never
    fabricate a timestamp) unless apply_duration_estimate() is called on the result."""
    words = text.split()
    total = len(words)
    chunks = []
    idx = 0
    i = 0
    while i < total:
        piece = words[i:i + chunk_words]
        chunks.append({
            "sentence_idx": idx, "text": " ".join(piece),
            "start_sec": None, "end_sec": None,
            "_word_start": i, "_word_end": i + len(piece),
        })
        idx += 1
        i += chunk_words
    return chunks


def apply_duration_estimate(chunks: List[Dict[str, Any]], duration_sec: float) -> List[Dict[str, Any]]:
    """Only called when the creator explicitly supplies an episode duration for untimed
    text — proportional-to-word-position estimates, always flagged `estimated: True` in the
    tool's output so the UI can badge them (guardrail 2). Never invoked silently."""
    total_words = chunks[-1]["_word_end"] if chunks else 0
    if not total_words:
        return chunks
    for c in chunks:
        c["start_sec"] = round(duration_sec * c["_word_start"] / total_words, 1)
        c["end_sec"] = round(duration_sec * c["_word_end"] / total_words, 1)
    return chunks


def parse_transcript_input(text: str) -> Dict[str, Any]:
    """Exposed for the /api/studio/parse_transcript pre-flight route — same parser tools 2
    and 6 use internally, surfaced standalone so the UI can classify a paste (and warn or
    block) before a run is spent."""
    return transcript_parser.parse_timed_input(text)


def run_tool(tool_id: str, inputs: Dict[str, Any], use_voice_profile: bool = True) -> Dict[str, Any]:
    """
    Entry point main.py submits onto jobs.py. Looks up the ToolSpec, enforces the shared
    guardrails (input cap, rate limit), delegates generation to the spec's own run_fn,
    applies the banned-words backstop, then records usage and run history.
    """
    import studio_prompts  # local import: studio_prompts imports this module at load time

    spec = studio_prompts.get_tool(tool_id)
    if spec is None:
        raise StudioError(f"Unknown tool '{tool_id}'")

    try:
        usage.check_input_words(spec.count_words(inputs))
        usage.check_rate_limit()

        profile = voice_profile.load() if use_voice_profile else None
        voice_block = voice_profile.to_prompt_block(profile) if profile else ""

        output, usage_totals = spec.run_fn(inputs, voice_block)

        if profile and profile.get("banned_words"):
            output, banned_found = enforce_banned_words(output, profile["banned_words"])
            if banned_found:
                output = dict(output)
                output.setdefault("guardrail_notes", {})["banned_words_removed"] = banned_found

        usage.record(tool_id, usage_totals)
        run_id = tool_runs.record(tool_id, inputs, output, meta={"usage": usage_totals})
        output = dict(output)
        output["run_id"] = run_id
        output["tool_id"] = tool_id
        return output
    except StudioError:
        raise
    except Exception as e:
        raise _translate(e) from e


def _default_regenerate(spec, stored_inputs: Dict[str, Any], block: str, voice_block: str):
    """Fallback used by any tool that doesn't define its own regenerate_fn: re-run the full
    pipeline and return just the requested block. Costs the same as a fresh run — tools where
    a block can be regenerated more cheaply (e.g. captions, one platform at a time) should
    define regenerate_fn instead."""
    new_output, usage_totals = spec.run_fn(stored_inputs, voice_block)
    return new_output.get(block), usage_totals


def regenerate_block(run_id: str, block: str) -> Dict[str, Any]:
    """POST /api/studio/regenerate — re-derive one block of a previous run without
    resubmitting source text (guardrail: regenerate one block, not the whole job)."""
    import studio_prompts

    run = tool_runs.get(run_id)
    if run is None:
        raise StudioError(f"Unknown run '{run_id}'")
    spec = studio_prompts.get_tool(run.tool_id)
    if spec is None:
        raise StudioError(f"Unknown tool '{run.tool_id}'")

    try:
        usage.check_rate_limit()
        profile = voice_profile.load()
        voice_block = voice_profile.to_prompt_block(profile)

        regen_fn = spec.regenerate_fn or (
            lambda inputs, blk, vb: _default_regenerate(spec, inputs, blk, vb)
        )
        new_block, usage_totals = regen_fn(run.inputs, block, voice_block)

        if profile.get("banned_words"):
            wrapped, _found = enforce_banned_words({"value": new_block}, profile["banned_words"])
            new_block = wrapped["value"]

        updated_output = dict(run.output)
        updated_output[block] = new_block
        usage.record(run.tool_id, usage_totals)
        tool_runs.update_output(run_id, updated_output)
        updated_output = dict(updated_output)
        updated_output["run_id"] = run_id
        updated_output["tool_id"] = run.tool_id
        return updated_output
    except StudioError:
        raise
    except Exception as e:
        raise _translate(e) from e
