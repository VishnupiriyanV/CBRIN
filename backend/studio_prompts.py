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

import platform_rules
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
# Tool 1 — Newsletter/Blog -> Social Repurposer
# --------------------------------------------------------------------------------------- #

_EXTRACT_SYSTEM = (
    "You extract the structural core of a piece of writing before it gets repurposed. "
    "Identify: the core argument, any named frameworks or models the writer coined (these "
    "must survive verbatim into every repurposed output), the single strongest concrete "
    "example, and the most contrarian line. Do not summarize — extract.\n\n"
    'Respond with ONLY a JSON object: {"core_argument": "", "frameworks": [""], '
    '"strongest_example": "", "contrarian_line": ""}. frameworks is an empty array if the '
    "writer coined no named term."
)
_EXTRACT_SCHEMA = {
    "type": "object",
    "required": ["core_argument", "frameworks", "strongest_example", "contrarian_line"],
}

_REPURPOSE_SYSTEM = (
    "You repurpose long-form writing into platform-native social posts. Rules:\n"
    "1. Preserve any named framework verbatim wherever it appears.\n"
    "2. Don't summarize — re-angle. Each output stands alone and gives value.\n"
    "3. Platform-native form: LinkedIn short paragraphs with line breaks and no hashtag "
    "spam; X one idea per post; Notes conversational and opinionated.\n"
    "4. No invented facts, stats, or quotes — only use what's in the source.\n\n"
    "{voice_block}\n\n"
    "Respond with ONLY a JSON object matching this shape:\n"
    '{{"linkedin":{{"hook":"","body":"","cta":""}},'
    '"thread":[{{"n":1,"text":""}}],'
    '"notes":["","",""],'
    '"carousel":{{"title":"","slides":[{{"n":1,"headline":"","body":""}}],"caption":""}}}}'
)
_REPURPOSE_SCHEMA = {"type": "object", "required": ["linkedin", "thread", "notes", "carousel"]}


def _repurpose_run(inputs: Dict[str, Any], voice_block: str):
    text = inputs.get("text", "")
    emphasize = inputs.get("emphasize", "")

    extraction, usage_a = sr.call_llm(_EXTRACT_SYSTEM, text, _EXTRACT_SCHEMA, temperature=0.2)

    user_msg = f"Source text:\n{text}\n\nExtracted structure:\n{json.dumps(extraction)}\n"
    if emphasize:
        user_msg += f"\nEmphasize this angle: {emphasize}\n"

    system = _REPURPOSE_SYSTEM.format(voice_block=voice_block)
    output, usage_b = sr.call_llm(system, user_msg, _REPURPOSE_SCHEMA, temperature=0.7)

    # Guardrail 7: named frameworks must survive verbatim somewhere in the output.
    output_text = " ".join(sr.collect_strings(output))
    frameworks_missing = [
        fw for fw in extraction.get("frameworks", [])
        if fw and not sr.appears_in_source(fw, output_text)
    ]

    output = dict(output)
    output["extraction"] = extraction
    output["guardrail_notes"] = {"frameworks_missing": frameworks_missing}
    return output, sr.merge_usage(usage_a, usage_b)


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
# Tool 3 — YouTube Title & Hook Generator
# --------------------------------------------------------------------------------------- #

TITLE_FORMULAS = [
    "curiosity_gap", "number_list", "contrarian", "transformation", "mistake_warning",
    "comparison", "time_bound_challenge", "question", "authority_credential", "beginner_framing",
]

_TITLES_SYSTEM = (
    "You generate YouTube titles, hooks, and thumbnail-text ideas before a video is filmed. "
    f"Use this exact formula library and tag each title with the formula id used: "
    f"{', '.join(TITLE_FORMULAS)}. Vary formulas across the batch — do not return most of "
    "them in the same formula. Titles should stay under 60 characters where possible "
    "(mobile truncation). No clickbait the video can't deliver on — for each title, state in "
    "\"promise\" what the video must contain to honor it. Hooks: state the payoff or stakes "
    "in the first sentence, never \"hey guys, welcome back\". Thumbnail text is TEXT ONLY, "
    "3–4 words max — no image generation, no A/B-testing claims. If past_titles are supplied "
    "and performed well, mirror their structure.\n\n"
    "{voice_block}\n\n"
    "Respond with ONLY a JSON object:\n"
    '{{"titles":[{{"text":"","formula":"","why":"","promise":""}}],'
    '"hooks":[{{"text":"","style":""}}],'
    '"thumbnail_text":[""]}}'
)
_TITLES_SCHEMA = {"type": "object", "required": ["titles", "hooks", "thumbnail_text"]}


def _postprocess_titles(result: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    titles = []
    formula_counts: Counter = Counter()
    for t in result.get("titles", []):
        formula = t.get("formula") if t.get("formula") in TITLE_FORMULAS else "unclassified"
        text = t.get("text", "")
        titles.append({
            "text": text, "formula": formula, "why": t.get("why", ""),
            "promise": t.get("promise", ""), "char_count": len(text), "over_limit": len(text) > 60,
        })
        formula_counts[formula] += 1

    thumbnails = []
    for tx in result.get("thumbnail_text", []):
        wc = len(tx.split())
        thumbnails.append({"text": tx, "word_count": wc, "over_word_limit": wc > 5})

    notes: Dict[str, Any] = {}
    if titles:
        dominant, count = formula_counts.most_common(1)[0]
        if count / len(titles) > 0.6:
            notes["low_diversity"] = True
            notes["dominant_formula"] = dominant

    return {"titles": titles, "hooks": result.get("hooks", []), "thumbnail_text": thumbnails}, notes


def _titles_run(inputs: Dict[str, Any], voice_block: str):
    topic = inputs.get("topic", "")
    niche = inputs.get("niche", "")
    audience_level = inputs.get("audience_level", "")
    past_titles = inputs.get("past_titles", [])

    system = _TITLES_SYSTEM.format(voice_block=voice_block)
    parts = [f"Topic: {topic}"]
    if niche:
        parts.append(f"Niche: {niche}")
    if audience_level:
        parts.append(f"Audience level: {audience_level}")
    if past_titles:
        parts.append("Past titles that performed well:\n" + "\n".join(past_titles))
    user = "\n".join(parts)

    result, u = sr.call_llm(system, user, _TITLES_SCHEMA, temperature=0.8)
    output, notes = _postprocess_titles(result)

    if notes.get("low_diversity"):
        retry_user = (
            user + f"\n\nYour previous batch leaned too heavily on the "
            f"'{notes['dominant_formula']}' formula. Use a wider spread this time."
        )
        result2, u2 = sr.call_llm(system, retry_user, _TITLES_SCHEMA, temperature=0.85)
        output2, notes2 = _postprocess_titles(result2)
        u = sr.merge_usage(u, u2)
        if not notes2.get("low_diversity"):
            output, notes = output2, notes2

    output = dict(output)
    output["guardrail_notes"] = notes
    return output, u


# --------------------------------------------------------------------------------------- #
# Tool 4 — Comment/DM Reply Assistant
# --------------------------------------------------------------------------------------- #

FLAG_VALUES = {None, "hostile", "sensitive", "business", "spam"}

_CLASSIFY_SYSTEM = (
    "You triage a batch of social media comments before any reply is generated. For each "
    "comment, decide whether it needs a human instead of an AI reply. Flag as:\n"
    "- hostile: attacking, trolling, bad-faith\n"
    "- sensitive: shares something personal, painful, a crisis, or a mental-health topic\n"
    "- business: a business inquiry, sponsorship, or legal/medical question\n"
    "- spam: bot-like, irrelevant, or promotional spam\n"
    "- null: safe for an AI-suggested reply\n\n"
    "Respond with ONLY a JSON array, one object per comment, same order as given:\n"
    '[{"index":0,"flag":null,"flag_reason":""}]'
)
_CLASSIFY_SCHEMA = {"type": "array", "items": {"required": ["index", "flag"]}}

_REPLY_SYSTEM = (
    "You write short, on-brand replies to social media comments for a creator. Never sound "
    "like a support bot. Never invent facts about the creator's life, products, or opinions. "
    "Vary the replies — do not produce near-identical responses across comments. Never argue "
    "with a hostile comment (you will not be shown any — they're filtered before you see "
    "them). Tone: {tone}. Length: {length}.\n\n"
    "{voice_block}\n\n"
    "Respond with ONLY a JSON array, one object per comment, same order as given:\n"
    '[{{"index":0,"suggested_reply":""}}]'
)
_REPLY_SCHEMA = {"type": "array", "items": {"required": ["index", "suggested_reply"]}}


def _replies_run(inputs: Dict[str, Any], voice_block: str):
    comments = inputs.get("comments", [])
    tone = inputs.get("tone", "warm")
    length = inputs.get("length", "one-liner")

    classify_user = "\n".join(f"{i}: {c}" for i, c in enumerate(comments))
    flags_raw, usage_a = sr.call_llm(_CLASSIFY_SYSTEM, classify_user, _CLASSIFY_SCHEMA, temperature=0.1)

    flags_by_index: Dict[int, Dict[str, Any]] = {}
    for item in flags_raw:
        idx = item.get("index")
        flag = item.get("flag")
        if flag not in FLAG_VALUES:
            flag = None
        flags_by_index[idx] = {"flag": flag, "flag_reason": item.get("flag_reason", "")}

    # Guardrail 5, structural: only indices with flag == None ever enter the reply prompt
    # below. A flagged comment's text is never sent to the reply-generation call at all.
    unflagged = [i for i in range(len(comments)) if flags_by_index.get(i, {}).get("flag") is None]

    replies_by_index: Dict[int, str] = {}
    usage_b = {"prompt_tokens": 0, "completion_tokens": 0, "model": ""}
    if unflagged:
        reply_user = "\n".join(f"{i}: {comments[i]}" for i in unflagged)
        reply_system = _REPLY_SYSTEM.format(tone=tone, length=length, voice_block=voice_block)
        replies_raw, usage_b = sr.call_llm(reply_system, reply_user, _REPLY_SCHEMA, temperature=0.7)
        for item in replies_raw:
            idx = item.get("index")
            if idx in unflagged:
                replies_by_index[idx] = item.get("suggested_reply", "")

    results = []
    for i, comment in enumerate(comments):
        info = flags_by_index.get(i, {"flag": None, "flag_reason": ""})
        is_flagged = info["flag"] is not None
        results.append({
            "comment": comment,
            "flag": info["flag"],
            "flag_reason": info["flag_reason"],
            "suggested_reply": None if is_flagged else replies_by_index.get(i),
        })

    return {"replies": results}, sr.merge_usage(usage_a, usage_b)


# --------------------------------------------------------------------------------------- #
# Tool 5 — Multi-Platform Description/Caption + Hashtag Reformatter
# --------------------------------------------------------------------------------------- #

DEFAULT_CAPTION_PLATFORMS = ["tiktok", "instagram", "youtube_short", "youtube_long", "x", "linkedin"]

_CAPTION_SYSTEM = (
    "You reformat one caption/description for {platform_label}. Style: {style}. Hard "
    "character limit: {char_limit} — rewrite to fit, never truncate mid-sentence; a "
    "shortened caption must still be a complete thought. Hashtags: {hashtag_min}-"
    "{hashtag_max}, placement: {hashtag_placement}. No hashtag walls — relevant, not "
    "maximal. Links are {clickable}. Preserve any CTA the user included, adapted in "
    "phrasing for this platform.\n\n{voice_block}\n\n"
    'Respond with ONLY a JSON object: {{"caption":"","hashtags":[""]}}'
)
_CAPTION_SCHEMA = {"type": "object", "required": ["caption", "hashtags"]}


def _generate_one_caption(text: str, cta: str, platform: str, rule: Dict[str, Any], voice_block: str):
    system = _CAPTION_SYSTEM.format(
        platform_label=rule.get("label", platform), style=rule.get("style", ""),
        char_limit=rule.get("char_limit", 2000), hashtag_min=rule.get("hashtag_min", 0),
        hashtag_max=rule.get("hashtag_max", 3), hashtag_placement=rule.get("hashtag_placement", ""),
        clickable="clickable" if rule.get("links_clickable") else "not clickable — don't rely on them",
        voice_block=voice_block,
    )
    user = f"Source content:\n{text}"
    if cta:
        user += f"\n\nCTA to preserve/adapt: {cta}"

    result, u = sr.call_llm(system, user, _CAPTION_SCHEMA, temperature=0.6)
    caption = result.get("caption", "")
    hashtags = result.get("hashtags", [])
    char_limit = rule.get("char_limit", 2000)
    over_limit = len(caption) > char_limit

    if over_limit:
        # Guardrail 14: never truncate — regenerate once, naming the overflow explicitly.
        retry_user = (
            user + f"\n\nYour previous caption was {len(caption)} characters; the hard "
            f"limit is {char_limit}. Rewrite shorter — do not cut it off mid-sentence."
        )
        result2, u2 = sr.call_llm(system, retry_user, _CAPTION_SCHEMA, temperature=0.6)
        if len(result2.get("caption", "")) <= char_limit:
            caption, hashtags = result2.get("caption", ""), result2.get("hashtags", [])
            over_limit = False
        u = sr.merge_usage(u, u2)

    hashtag_max = rule.get("hashtag_max", len(hashtags))
    if len(hashtags) > hashtag_max:
        hashtags = hashtags[:hashtag_max]  # guardrail 15: no hashtag walls

    return {
        "caption": caption, "hashtags": hashtags, "char_count": len(caption),
        "char_limit": char_limit, "over_limit": over_limit,
    }, u


def _captions_run(inputs: Dict[str, Any], voice_block: str):
    text = inputs.get("text", "")
    cta = inputs.get("cta", "")
    platforms = inputs.get("platforms") or DEFAULT_CAPTION_PLATFORMS
    rules = platform_rules.load()

    output: Dict[str, Any] = {}
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "model": ""}
    for platform in platforms:
        rule = rules.get(platform)
        if not rule:
            continue
        result, u = _generate_one_caption(text, cta, platform, rule, voice_block)
        output[platform] = result
        total_usage = sr.merge_usage(total_usage, u)
    return output, total_usage


def _captions_regenerate(inputs: Dict[str, Any], block: str, voice_block: str):
    """Cheaper than the default full-pipeline regenerate: one platform is one call."""
    rule = platform_rules.load().get(block)
    if not rule:
        raise sr.StudioError(f"Unknown platform '{block}'")
    return _generate_one_caption(inputs.get("text", ""), inputs.get("cta", ""), block, rule, voice_block)


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
    "repurposer": ToolSpec(
        id="repurposer", label="Newsletter/Blog → Social Repurposer",
        description="Paste a newsletter or blog post; get a LinkedIn post, an X thread, short-form notes, and a carousel outline.",
        needs_timestamps=False,
        count_words=lambda inputs: sr.word_count(inputs.get("text", "")),
        run_fn=_repurpose_run,
    ),
    "show_notes": ToolSpec(
        id="show_notes", label="Transcript → Show Notes, Timestamps & Titles",
        description="Paste a transcript (or pick an indexed video); get show notes, chapters, and title options.",
        needs_timestamps=False,
        count_words=_transcript_input_word_count,
        run_fn=_show_notes_run,
    ),
    "titles": ToolSpec(
        id="titles", label="YouTube Title & Hook Generator",
        description="Pre-publish title, hook, and thumbnail-text ideas, each tagged with the formula used.",
        needs_timestamps=False,
        count_words=lambda inputs: sr.word_count(inputs.get("topic", "")) + sr.word_count(" ".join(inputs.get("past_titles", []))),
        run_fn=_titles_run,
    ),
    "replies": ToolSpec(
        id="replies", label="Comment/DM Reply Assistant",
        description="Paste a batch of comments; get tone-matched suggested replies with hostile/sensitive/business ones flagged for a human.",
        needs_timestamps=False,
        count_words=lambda inputs: sum(sr.word_count(c) for c in inputs.get("comments", [])),
        run_fn=_replies_run,
    ),
    "captions": ToolSpec(
        id="captions", label="Multi-Platform Caption Reformatter",
        description="One caption or description in; platform-optimized versions out for six platforms.",
        needs_timestamps=False,
        count_words=lambda inputs: sr.word_count(inputs.get("text", "")),
        run_fn=_captions_run,
        regenerate_fn=_captions_regenerate,
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
