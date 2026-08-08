"""
One short, grounded answer on top of search results.

Search is retrieval-only by design: it returns real transcript moments and never invents
prose. This module keeps that property while removing the last manual step — reading several
quotes and inferring the answer yourself — by asking the LLM to state the answer *using only
the quotes that retrieval already found*, and refusing when they don't contain one.

The anti-hallucination contract is the same one STUDIO uses (studio_prompts.py): quotes are
numbered, the model may only refer to them by [idx], and every index it returns is validated
against the real result set before anything reaches the UI. The model never sees or writes a
timestamp — those come from the retrieved results, not from generation.

This is deliberately a separate endpoint from /api/search (see main.py): results must render
whether or not this succeeds, and a slow or unconfigured LLM must never degrade search.
"""
from typing import Any, Dict, List, Optional, Tuple

import llm_client

# Two sentences is the brief. The word cap is the backstop that actually holds — "be concise"
# alone reliably produces a paragraph, so the limit is stated as a number in the prompt AND
# enforced in _validate below, because a prompt constraint is a request, not a guarantee.
MAX_ANSWER_WORDS = 45

# More than this and the answer stops being an answer and becomes a second search results
# page. The best quotes are already ranked first, so the tail adds tokens, not accuracy.
MAX_QUOTES_IN_PROMPT = 5

# Per-quote truncation. `full_text` can be a 90s merged window; the trimmed `text` is what
# the reader sees and is what the answer should be grounded in.
MAX_QUOTE_WORDS = 120

_ANSWER_SYSTEM = (
    "You answer a question using ONLY the numbered quotes provided, which are verbatim "
    "excerpts from one creator's own video transcripts. You have no other knowledge; if the "
    "quotes do not contain the answer, you do not know it.\n\n"
    "Rules:\n"
    "- Two sentences maximum. Hard limit of {max_words} words. Shorter is better.\n"
    "- Answer the question directly. No preamble, no restating the question, no 'based on "
    "the transcript', no 'the speaker mentions that'. Start with the answer itself.\n"
    "- Use only what the quotes actually say. Do not add context, background, caveats, or "
    "advice from your own knowledge, however helpful it would be.\n"
    "- Put the [idx] of every quote you used in citations. An answer with no citation is "
    "not an answer.\n"
    "- Never write a timestamp, duration, or video title — the app supplies those itself.\n"
    "- If the quotes are merely on the same topic but do not answer the question, set "
    "sufficient to false and leave answer as an empty string. Do not stretch a partial "
    "match into an answer, and do not hedge — an honest nothing beats a padded guess.\n"
    "- If the input is not a question at all — a bare keyword or topic like 'english lesson' "
    "or 'camera' — there is nothing to answer. Set sufficient to false. Do not summarize the "
    "quotes, and do not pick an arbitrary fact out of them; the user is browsing for moments, "
    "and the moments are already shown to them.\n\n"
    "Respond with ONLY a JSON object:\n"
    '{{"answer":"","citations":[1],"sufficient":true}}'
)

_ANSWER_SCHEMA = {"type": "object", "required": ["answer", "citations", "sufficient"]}


def format_quotes(results: List[Dict[str, Any]]) -> str:
    """Render results as the numbered [idx] lines the prompt's contract is built on.

    1-based to match how citations read in the UI ("[1]"), so the model's indices and the
    user's visible markers are the same numbers and no off-by-one translation is needed.
    """
    lines = []
    for i, r in enumerate(results[:MAX_QUOTES_IN_PROMPT], start=1):
        text = " ".join((r.get("text") or "").split()[:MAX_QUOTE_WORDS])
        lines.append(f"[{i}] {text}")
    return "\n".join(lines)


def build_user_message(query: str, results: List[Dict[str, Any]]) -> str:
    return f"Question: {query}\n\nQuotes:\n{format_quotes(results)}"


def _validate(parsed: Any, result_count: int) -> Optional[Dict[str, Any]]:
    """Return a clean answer dict, or None meaning 'show no answer at all'.

    Returning None is a first-class outcome, not an error path: the results are a complete
    response on their own, so anything short of a verified, cited, in-range answer is better
    dropped than shown. Mirrors narrative_engine._validate_and_clean_beats, which likewise
    voids model output that can't be tied back to the real source.
    """
    if not isinstance(parsed, dict):
        return None
    if not parsed.get("sufficient"):
        return None

    answer = (parsed.get("answer") or "").strip()
    if not answer:
        return None

    # Drop citations that don't point at a quote we actually sent. A model citing [7] when it
    # was given four quotes is citing something that does not exist, and the UI would render
    # a marker that scrolls nowhere.
    citations = []
    raw = parsed.get("citations")
    if isinstance(raw, list):
        for c in raw:
            try:
                idx = int(c)
            except (TypeError, ValueError):
                continue
            if 1 <= idx <= result_count and idx not in citations:
                citations.append(idx)
    if not citations:
        return None

    words = answer.split()
    truncated = len(words) > MAX_ANSWER_WORDS
    if truncated:
        answer = " ".join(words[:MAX_ANSWER_WORDS]).rstrip(",;:") + "…"

    return {"answer": answer, "citations": sorted(citations), "truncated": truncated}


def generate_answer(query: str, results: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """(answer_or_None, usage). Raises llm_client.LLMUnavailable if the provider is unusable."""
    if not query.strip() or not results:
        return None, {"prompt_tokens": 0, "completion_tokens": 0, "model": ""}

    used = results[:MAX_QUOTES_IN_PROMPT]
    parsed, usage = llm_client.complete_json_with_usage(
        system=_ANSWER_SYSTEM.format(max_words=MAX_ANSWER_WORDS),
        user=build_user_message(query, used),
        schema=_ANSWER_SCHEMA,
        # Low temperature: this is extraction constrained to given text, not writing. Variety
        # here would only mean drifting further from what the quotes actually say.
        temperature=0.1,
        # Generous relative to a 45-word answer — the cap is enforced in _validate, and
        # clipping mid-JSON would just produce an unparseable response and burn the retry.
        max_tokens=250,
    )
    return _validate(parsed, len(used)), usage
