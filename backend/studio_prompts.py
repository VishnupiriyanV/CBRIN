"""
The six STUDIO tools from creator-tools-integration-spec.md, each as a ToolSpec: prompts,
schema, and a run_fn that studio_runner.run_tool() delegates generation to. Shared plumbing
(input caps, rate limiting, banned-word stripping, usage/run recording) lives in
studio_runner.py and applies to every tool uniformly — this module only holds what's
actually different tool to tool.

Every run_fn returns (output: dict, usage: dict) and raises studio_runner.InputRejected /
StudioError for tool-specific validation failures (e.g. tool 6's hard timestamp requirement).
"""
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import studio_runner as sr
import transcript_parser

RunFn = Callable[[Dict[str, Any], str], Tuple[Dict[str, Any], Dict[str, Any]]]
RegenerateFn = Callable[[Dict[str, Any], str, str], Tuple[Any, Dict[str, Any]]]


@dataclass
class ToolSpec:
    id: str
    label: str
    description: str
    needs_timestamps: bool
    count_words: Callable[[Dict[str, Any]], int]
    run_fn: RunFn
    regenerate_fn: Optional[RegenerateFn] = None


# --------------------------------------------------------------------------------------- #
# Tool 2 — Transcript -> Show Notes, Timestamps & Titles
# --------------------------------------------------------------------------------------- #

_SHOW_NOTES_SYSTEM = (
    "You produce podcast/video show notes from a transcript. The transcript is given as "
    "numbered sentence lines: [idx] timestamp  text. You may ONLY refer to moments by their "
    "[idx] number — never write a time value yourself; the app derives every displayed "
    "timestamp from real cue data, not from you.\n"
    "Chapter on topic shifts, not fixed intervals. Chapter titles: descriptive, 3–7 words, "
    "no clickbait. Show notes capture claims and takeaways, not a play-by-play. Titles: mix "
    "formats — question, number, contrarian claim, guest-name-forward. Attribute guest "
    "statements to the guest by name if one is given. Flag any sentence range that's "
    "obviously clip-worthy in clip_worthy_sentence_indices.\n\n"
    "{voice_block}\n\n"
    "Respond with ONLY a JSON object:\n"
    '{{"summary":"","show_notes":[""],'
    '"chapters":[{{"start_sentence_idx":0,"title":""}}],'
    '"titles":[""],"promo":"","clip_worthy_sentence_indices":[0]}}'
)
_SHOW_NOTES_SCHEMA = {"type": "object", "required": ["summary", "show_notes", "chapters", "titles", "promo"]}


def _transcript_input_word_count(inputs: Dict[str, Any]) -> int:
    if inputs.get("source") == "library":
        return sum(sr.word_count(s.get("text", "")) for s in inputs.get("sentences", []))
    return sr.word_count(inputs.get("transcript_text", ""))


def _resolve_sentences_or_reject(inputs: Dict[str, Any], require_timestamps: bool):
    """Shared by tools 2 and 6: resolve a `sentences` list from either an indexed-library
    selection or a fresh paste, or raise InputRejected when timestamps are mandatory and the
    input has none (guardrail 3, tool 6)."""
    source = inputs.get("source", "paste")
    if source == "library":
        sentences = inputs.get("sentences", [])
        if not sentences:
            raise sr.InputRejected("No sentences were supplied for the selected video.")
        return sentences, True, False

    transcript_text = inputs.get("transcript_text", "")
    parsed = transcript_parser.parse_timed_input(transcript_text)

    if parsed["has_timestamps"]:
        from multimodal_engine import MultimodalEngine
        sentences = MultimodalEngine.segment_transcript_into_sentences(parsed["segments"])
        return sentences, True, False

    if require_timestamps:
        raise sr.InputRejected(
            "This tool needs timestamped input (SRT/VTT, or a timestamped transcript export) "
            "— plain text can't produce a usable moment map. Export captions from Twitch or "
            "YouTube and paste those instead."
        )

    chunks = sr.pseudo_segment_plain_text(transcript_text)
    duration_hint = inputs.get("duration_hint_sec")
    estimated = False
    if duration_hint:
        chunks = sr.apply_duration_estimate(chunks, float(duration_hint))
        estimated = True
    return chunks, False, estimated


def _merge_show_notes_windows(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(results) == 1:
        return results[0]
    merged: Dict[str, Any] = {
        "summary": results[0].get("summary", ""), "show_notes": [], "chapters": [],
        "titles": [], "promo": results[0].get("promo", ""),
    }
    seen_notes, seen_titles = set(), set()
    for r in results:
        for note in r.get("show_notes", []):
            if note not in seen_notes:
                seen_notes.add(note)
                merged["show_notes"].append(note)
        merged["chapters"].extend(r.get("chapters", []))
        for t in r.get("titles", []):
            if t not in seen_titles:
                seen_titles.add(t)
                merged["titles"].append(t)
    merged["chapters"].sort(key=lambda c: c.get("start_sentence_idx", 0))
    return merged


def _show_notes_run(inputs: Dict[str, Any], voice_block: str):
    sentences, has_timestamps, estimated = _resolve_sentences_or_reject(inputs, require_timestamps=False)
    episode_title = inputs.get("episode_title", "")
    guest_name = inputs.get("guest_name", "")

    windows = sr.window_sentences(sentences)
    system = _SHOW_NOTES_SYSTEM.format(voice_block=voice_block)

    per_window, total_usage = [], {"prompt_tokens": 0, "completion_tokens": 0, "model": ""}
    for window in windows:
        user = sr.format_sentences(window)
        if episode_title:
            user = f"Episode title: {episode_title}\n" + user
        if guest_name:
            user = f"Guest: {guest_name}\n" + user
        result, u = sr.call_llm(system, user, _SHOW_NOTES_SCHEMA, temperature=0.3)
        per_window.append(result)
        total_usage = sr.merge_usage(total_usage, u)

    merged = _merge_show_notes_windows(per_window)

    # Guardrail 1: the model never emits a time value — every displayed timestamp is
    # derived here from the sentence it references, or omitted entirely.
    idx_lookup = {s["sentence_idx"]: s for s in sentences}
    chapters_out = []
    for ch in merged.get("chapters", []):
        s = idx_lookup.get(ch.get("start_sentence_idx"))
        if s is None:
            continue  # hallucinated index — drop rather than guess
        start_sec = s.get("start_sec")
        # Whether a chapter gets a time at all depends on the *sentence's* start_sec, not
        # on `has_timestamps` alone — plain text with a duration hint has has_timestamps=False
        # but does carry an estimated start_sec via apply_duration_estimate().
        if start_sec is None:
            chapters_out.append({"time": None, "title": ch.get("title", ""), "estimated": False})
        else:
            chapters_out.append({
                "time": sr.format_timestamp(start_sec),
                "title": ch.get("title", ""),
                "estimated": estimated,
            })

    output = {
        "summary": merged.get("summary", ""),
        "show_notes": merged.get("show_notes", []),
        "chapters": chapters_out,
        "titles": merged.get("titles", []),
        "promo": merged.get("promo", ""),
        "timestamp_mode": "real" if (has_timestamps and not estimated) else ("estimated" if estimated else "none"),
    }
    return output, total_usage


# --------------------------------------------------------------------------------------- #
# Tool 6 — Stream/VOD -> Clip-Moment Finder
# --------------------------------------------------------------------------------------- #

MOMENT_TYPES = ["funny", "insight", "reaction", "story", "hot_take", "tutorial"]
LEAD_IN_SEC = 15.0

_MOMENTS_SYSTEM = (
    "You find clip-worthy moments in a stream/podcast transcript for a creator who will cut "
    "the clips themselves — you do not produce video. The transcript is numbered sentence "
    "lines: [idx] timestamp text. Rank by clip potential; return the top 10–15 for a "
    "multi-hour stream, fewer for a shorter one. Give a real reason per moment, never "
    "\"this was interesting\". Diversify types — do not return mostly one type. Reference "
    "the sentence [idx] range from setup through payoff; the app expands the start further "
    "back for lead-in and derives all times from real cue data, never from you. Note when a "
    "moment depends on visual context the transcript can't confirm (a visual gag, an "
    "on-screen reaction) and mark visual_dependent true for it.\n"
    f"Moment types: {', '.join(MOMENT_TYPES)}.\n\n"
    "{voice_block}\n\n"
    "Respond with ONLY a JSON object:\n"
    '{{"moments":[{{"start_sentence_idx":0,"end_sentence_idx":0,"score":8,"reason":"",'
    '"suggested_title":"","type":"funny","visual_dependent":false}}]}}'
)
_MOMENTS_SCHEMA = {"type": "object", "required": ["moments"]}


def _expand_lead_in(sentences: List[Dict[str, Any]], start_idx: int, lead_in_sec: float) -> Dict[str, Any]:
    """Walk backward from start_idx until ~lead_in_sec of setup is included — guardrail 18:
    clips need setup, not just the punchline."""
    idx_lookup = {s["sentence_idx"]: s for s in sentences}
    target = idx_lookup.get(start_idx)
    if target is None or target.get("start_sec") is None:
        return target or {}
    cutoff = target["start_sec"] - lead_in_sec
    candidate = target
    for s in sorted(sentences, key=lambda s: s["sentence_idx"]):
        if s["sentence_idx"] > start_idx:
            break
        if s.get("start_sec") is not None and s["start_sec"] >= cutoff:
            candidate = s
            break
    return candidate


def _enforce_type_diversity(moments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Guardrail 16: if one type dominates >60% of the batch, drop the weakest excess
    instances of it rather than shipping 15 of the same type."""
    if not moments:
        return moments
    counts = Counter(m.get("type") for m in moments)
    total = len(moments)
    dominant, count = counts.most_common(1)[0]
    if count / total <= 0.6:
        return moments
    cap = max(1, int(total * 0.6))
    kept, dominant_seen = [], 0
    for m in sorted(moments, key=lambda m: -m.get("score", 0)):
        if m.get("type") == dominant:
            dominant_seen += 1
            if dominant_seen > cap:
                continue
        kept.append(m)
    return kept


def _moments_run(inputs: Dict[str, Any], voice_block: str):
    # Guardrail 3: timestamped input is a hard requirement — raises InputRejected (-> 422)
    # rather than producing a silently useless moment map.
    sentences, _has_ts, _estimated = _resolve_sentences_or_reject(inputs, require_timestamps=True)

    stream_topic = inputs.get("stream_topic", "")
    clip_length_target = inputs.get("clip_length_target", "30")

    windows = sr.window_sentences(sentences)
    system = _MOMENTS_SYSTEM.format(voice_block=voice_block)
    idx_lookup = {s["sentence_idx"]: s for s in sentences}

    all_moments, total_usage = [], {"prompt_tokens": 0, "completion_tokens": 0, "model": ""}
    for window in windows:
        user = sr.format_sentences(window)
        if stream_topic:
            user = f"Stream topic: {stream_topic}\n" + user
        user += f"\n\nTarget clip length: ~{clip_length_target}s"
        result, u = sr.call_llm(system, user, _MOMENTS_SCHEMA, temperature=0.5)
        total_usage = sr.merge_usage(total_usage, u)
        for m in result.get("moments", []):
            start_idx, end_idx = m.get("start_sentence_idx"), m.get("end_sentence_idx")
            if start_idx not in idx_lookup or end_idx not in idx_lookup:
                continue  # hallucinated index — dropped, never guessed
            if m.get("type") not in MOMENT_TYPES:
                continue
            all_moments.append({**m, "_key": (start_idx, end_idx)})

    seen, deduped = set(), []
    for m in all_moments:
        if m["_key"] in seen:
            continue
        seen.add(m["_key"])
        deduped.append(m)

    deduped = _enforce_type_diversity(deduped)
    deduped.sort(key=lambda m: -m.get("score", 0))
    deduped = deduped[:15]

    moments_out = []
    for m in deduped:
        end_s = idx_lookup[m["end_sentence_idx"]]
        lead_in = _expand_lead_in(sentences, m["start_sentence_idx"], LEAD_IN_SEC)
        moments_out.append({
            "start": sr.format_timestamp(lead_in.get("start_sec")),
            "end": sr.format_timestamp(end_s.get("end_sec")),
            "score": m.get("score", 0),
            "reason": m.get("reason", ""),
            "suggested_title": m.get("suggested_title", ""),
            "type": m.get("type"),
            "visual_dependent": bool(m.get("visual_dependent", False)),
        })

    return {"moments": moments_out}, total_usage


# --------------------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------------------- #

TOOL_SPECS: Dict[str, ToolSpec] = {
    "show_notes": ToolSpec(
        id="show_notes", label="Transcript → Show Notes, Timestamps & Titles",
        description="Paste a transcript (or pick an indexed video); get show notes, chapters, and title options.",
        needs_timestamps=False,
        count_words=_transcript_input_word_count,
        run_fn=_show_notes_run,
    ),
    "moments": ToolSpec(
        id="moments", label="Stream/VOD → Clip-Moment Finder",
        description="Paste a timestamped transcript; get a ranked moment map with suggested clip titles — no video is produced.",
        needs_timestamps=True,
        count_words=_transcript_input_word_count,
        run_fn=_moments_run,
    ),
}


def get_tool(tool_id: str) -> Optional[ToolSpec]:
    return TOOL_SPECS.get(tool_id)


def list_tools() -> List[Dict[str, Any]]:
    return [
        {"id": s.id, "label": s.label, "description": s.description, "needs_timestamps": s.needs_timestamps}
        for s in TOOL_SPECS.values()
    ]
