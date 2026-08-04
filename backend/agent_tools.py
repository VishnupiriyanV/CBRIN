"""
Agent Tools Registry for CreatorBrain Studio Copilot.
Exposes Vault semantic search, ENGINE narrative clip extraction, Studio tools,
and Voice Profile / Platform Rules as callable OpenAI-wire tools for LLM agents.
"""

import json
from typing import Any, Dict, List, Optional

# OpenAI Tool Schemas
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": "Search across the creator's video and audio transcript library for specific topics, quotes, or keywords.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query, phrase, or topic to search for"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of matching chunks to return (default 5)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_library_videos",
            "description": "List all indexed videos and audio files currently in the creator's Vault library.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_video_transcript",
            "description": "Retrieve transcript chunks/sentences for a specific video in the library by video ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "The unique ID of the video"
                    }
                },
                "required": ["video_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_video_clips",
            "description": "Analyze narrative structure and extract top clip candidates for a video using ENGINE.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "The video ID. If unknown, leave empty to analyze the primary library video."
                    },
                    "count": {
                        "type": "integer",
                        "description": "Maximum number of clips to extract (default 3)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_studio_tool",
            "description": "Execute one of the six Studio text generation tools: 'repurposer' (full multi-platform campaign package), 'show_notes' (summary, chapters & key takeaways), 'titles' (high-CTR viral titles), 'replies' (thoughtful community responses), 'captions' (social captions with hashtags), 'moments' (highlight timestamps).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "enum": ["repurposer", "show_notes", "titles", "replies", "captions", "moments"],
                        "description": "The specific Studio tool to run"
                    },
                    "input_text": {
                        "type": "string",
                        "description": "The source transcript, quote, topic, or text content to process. For 'replies', one comment per line."
                    },
                    "platform": {
                        "type": "string",
                        "description": "Target social platform if applicable (e.g. 'twitter', 'linkedin', 'youtube', 'instagram')"
                    },
                    "video_id": {
                        "type": "string",
                        "description": "For 'show_notes' or 'moments': the indexed library video ID to pull real timestamped sentences from, instead of using input_text. Leave empty to use the active video."
                    }
                },
                "required": ["tool_id", "input_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_creator_context",
            "description": "Retrieve the configured Voice Profile (brand tone, banned words, bio) and Platform Rules constraints.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "deep_research",
            "description": "Answer a question that may span the creator's whole library. Expands the query into several paraphrases, searches the Vault with each, and fuses the results so you get broader, better-ranked coverage than a single search_vault call. Use this for open-ended or synthesis questions (e.g. 'what have I said about pricing?'), not for a single known quote lookup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The research question to investigate across the library"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of fused passages to return (default 8)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_content_pack",
            "description": "Autonomously turn one video into a ready-to-post content pack: real-timestamp clip candidates, a multi-platform repurpose (LinkedIn/X/notes/carousel), title options, show notes with chapters, and platform captions. Use this whenever the user wants a video 'turned into content', a 'content pack', or a batch of posts rather than a single tool output. Runs all the Studio tools in one call — do not call run_studio_tool separately after this.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "The video ID. If unknown, leave empty to use the active/primary library video."
                    },
                    "goal": {
                        "type": "string",
                        "description": "What the creator wants out of this video (e.g. 'a week of LinkedIn and X content'), used to angle the titles and repurposed posts."
                    },
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Target caption platforms, e.g. ['linkedin','x','instagram']. Defaults to a standard set if omitted."
                    }
                },
                "required": []
            }
        }
    }
]

# --------------------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------------------- #

PLATFORM_ALIASES = {
    "twitter": "x",
    "youtube": "youtube_long",
    "shorts": "youtube_short",
}

DEFAULT_PACK_PLATFORMS = ["linkedin", "x", "instagram"]


def _format_search_hit(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "video_id": item.get("video_id"),
        "title": item.get("title"),
        "start_time": item.get("start_time"),
        "end_time": item.get("end_time"),
        "start_sec": item.get("start_time"),
        "end_sec": item.get("end_time"),
        "start_formatted": item.get("start_formatted"),
        "text": item.get("text"),
        "score": round(float(item.get("final_score", 0)), 3)
    }


def _sentences_for_video(store: Any, video_id: str) -> List[Dict[str, Any]]:
    """Mirrors main.py's _sentences_for_video: real cue data (sentence_idx/text/start_sec/
    end_sec) for a video, sorted. Used so Studio tools get real timestamps instead of
    fabricated ones."""
    sentences = [
        {
            "sentence_idx": c["sentence_idx"],
            "text": c.get("text", ""),
            "start_sec": c.get("start_sec"),
            "end_sec": c.get("end_sec"),
        }
        for c in getattr(store, "chunks", [])
        if c.get("video_id") == video_id and c.get("sentence_idx") is not None
    ]
    sentences.sort(key=lambda s: s["sentence_idx"])
    return sentences


def _resolve_video_id(store: Any, video_id: str) -> str:
    if not store or not getattr(store, "videos", None):
        return video_id
    if video_id in store.videos:
        return video_id
    return list(store.videos.keys())[0]


def _studio_inputs_for(
    tool_id: str, input_text: str, platform: str, store: Any, video_id: str
) -> Dict[str, Any]:
    """Maps a plain input_text/platform pair onto the exact keys each Studio tool actually
    reads (studio_prompts.py). The old shotgun approach (transcript_text/source_text/
    input_text) silently no-ops for repurposer/titles/replies/captions, which read text/
    topic/comments respectively."""
    platform = PLATFORM_ALIASES.get((platform or "").lower(), (platform or "").lower())

    if tool_id in ("show_notes", "moments"):
        sentences = _sentences_for_video(store, video_id) if video_id else []
        if sentences:
            return {"source": "library", "sentences": sentences}
        # No indexed video available — fall back to plain pasted text (no fabricated times).
        return {"source": "paste", "transcript_text": input_text}

    if tool_id == "titles":
        return {"topic": input_text}

    if tool_id == "replies":
        comments = [line.strip() for line in input_text.split("\n") if line.strip()]
        return {"comments": comments}

    if tool_id == "captions":
        inputs: Dict[str, Any] = {"text": input_text}
        if platform:
            inputs["platforms"] = [platform]
        return inputs

    # repurposer and anything else: plain source text
    return {"text": input_text}


def _deep_research(args: Dict[str, Any], store: Any) -> Dict[str, Any]:
    """Multi-query expansion: ask the LLM for paraphrases of `query`, search the Vault with
    the original + each paraphrase, and fuse results via Reciprocal Rank Fusion keyed on
    (video_id, start_time). Broader recall than a single search_vault call for open-ended
    or synthesis questions."""
    import llm_client

    query = args.get("query", "")
    top_k = int(args.get("top_k", 8))

    if not store or not hasattr(store, "search"):
        return {"error": "Vault vector store is not available"}
    if not query:
        return {"error": "query is required"}

    queries = [query]
    if llm_client.is_configured():
        try:
            schema = {"type": "object", "required": ["queries"]}
            system = (
                "You expand a search query into 2-3 short paraphrases that would surface "
                "different relevant passages in a semantic search over a creator's own "
                "video/audio transcripts. Keep each paraphrase concise and on-topic."
            )
            parsed = llm_client.complete_json(
                system, f"Original query: {query}", schema, temperature=0.4
            )
            extra = [q for q in parsed.get("queries", []) if isinstance(q, str) and q.strip()]
            queries.extend(extra[:3])
        except Exception:
            pass  # paraphrase expansion is best-effort; fall back to the single query

    # Rank lists per query, fused via RRF (k=60)
    K = 60
    fused_scores: Dict[tuple, float] = {}
    hit_by_key: Dict[tuple, Dict[str, Any]] = {}

    for q in queries:
        try:
            res = store.search(query=q, top_k=top_k)
        except Exception:
            continue
        for rank, item in enumerate(res.get("results", []), start=1):
            key = (item.get("video_id"), item.get("start_time"))
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (K + rank)
            if key not in hit_by_key:
                hit_by_key[key] = _format_search_hit(item)

    ranked_keys = sorted(fused_scores.keys(), key=lambda k: -fused_scores[k])[:top_k]
    results = [hit_by_key[k] for k in ranked_keys]

    return {
        "query": query,
        "expanded_queries": queries,
        "count": len(results),
        "results": results
    }


def _generate_content_pack(args: Dict[str, Any], store: Any) -> Dict[str, Any]:
    """Deterministically orchestrates clip extraction + the relevant Studio tools for one
    video into a single downloadable pack. Runs sequentially — tool_runs.py/usage.py do
    unlocked whole-file read-modify-write, so parallel Studio calls risk clobbering each
    other's writes."""
    import studio_runner

    if not store:
        return {"error": "Vault store unavailable"}

    video_id = _resolve_video_id(store, args.get("video_id", ""))
    if not video_id:
        return {"error": "No videos in the library to build a content pack from"}

    video_meta = store.videos.get(video_id, {"title": video_id})
    goal = args.get("goal", "")
    platforms = args.get("platforms") or DEFAULT_PACK_PLATFORMS
    platforms = [PLATFORM_ALIASES.get(p.lower(), p.lower()) for p in platforms]

    pack: Dict[str, Any] = {
        "video_id": video_id,
        "video_title": video_meta.get("title", video_id),
        "goal": goal,
        "clips": [],
        "repurposed": None,
        "titles": None,
        "show_notes": None,
        "captions": None,
        "sources": [],
        "errors": {},
    }

    # 1. Clips (real timestamps via extract_video_clips)
    clip_result = execute_tool("extract_video_clips", {"video_id": video_id, "count": 3}, store)
    if "error" in clip_result:
        pack["errors"]["clips"] = clip_result["error"]
    else:
        pack["clips"] = clip_result.get("clips", [])

    sentences = _sentences_for_video(store, video_id)
    transcript_text = " ".join(s.get("text", "") for s in sentences)[:6000]

    # 2. Repurposer (long-form -> multi-platform posts)
    try:
        repurpose_inputs = {"text": transcript_text, "emphasize": goal}
        pack["repurposed"] = studio_runner.run_tool("repurposer", repurpose_inputs, use_voice_profile=True)
    except Exception as e:
        pack["errors"]["repurposed"] = str(e)

    # 3. Titles
    try:
        titles_inputs = {"topic": goal or video_meta.get("title", video_id)}
        pack["titles"] = studio_runner.run_tool("titles", titles_inputs, use_voice_profile=True)
    except Exception as e:
        pack["errors"]["titles"] = str(e)

    # 4. Show notes (real cue data if available)
    try:
        if sentences:
            show_notes_inputs = {"source": "library", "sentences": sentences}
        else:
            show_notes_inputs = {"source": "paste", "transcript_text": transcript_text}
        pack["show_notes"] = studio_runner.run_tool("show_notes", show_notes_inputs, use_voice_profile=True)
    except Exception as e:
        pack["errors"]["show_notes"] = str(e)

    # 5. Captions (per requested platform)
    try:
        captions_inputs = {"text": transcript_text[:2000], "platforms": platforms}
        pack["captions"] = studio_runner.run_tool("captions", captions_inputs, use_voice_profile=True)
    except Exception as e:
        pack["errors"]["captions"] = str(e)

    pack["sources"] = [
        {"video_id": video_id, "title": video_meta.get("title", video_id)}
    ]
    return pack


def execute_tool(name: str, args: Dict[str, Any], store: Any) -> Dict[str, Any]:
    """
    Executes the specified tool with arguments against the system's backend services.
    Returns a JSON-serializable dictionary with tool execution results.
    """
    try:
        if name == "search_vault":
            query = args.get("query", "")
            top_k = int(args.get("top_k", 5))
            if not store or not hasattr(store, "search"):
                return {"error": "Vault vector store is not available"}
            
            search_res = store.search(query=query, top_k=top_k)
            results = [_format_search_hit(item) for item in search_res.get("results", [])]

            # If default relevance threshold returns 0 items, retry with relaxed relevance threshold
            if not results and query:
                search_res = store.search(query=query, top_k=top_k, relevance_threshold=0.001)
                results = [_format_search_hit(item) for item in search_res.get("results", [])]

            return {
                "query": query,
                "count": len(results),
                "results": results
            }

        elif name == "deep_research":
            return _deep_research(args, store)

        elif name == "list_library_videos":
            if not store or not hasattr(store, "videos"):
                return {"error": "Vault video index unavailable"}
            videos = []
            for vid_id, meta in store.videos.items():
                videos.append({
                    "id": vid_id,
                    "title": meta.get("title", vid_id),
                    "channel": meta.get("channel", ""),
                    "duration_formatted": meta.get("duration_formatted", ""),
                    "total_seconds": meta.get("total_seconds", 0),
                    "source": "youtube" if meta.get("youtube_id") else "local"
                })
            return {
                "total_videos": len(videos),
                "videos": videos[:20]
            }

        elif name == "get_video_transcript":
            video_id = args.get("video_id", "")
            if not store:
                return {"error": "Vault store unavailable"}

            # If no video_id provided, pick first available video
            if not video_id and getattr(store, "videos", None):
                video_id = list(store.videos.keys())[0]

            matching_chunks = [c for c in getattr(store, "chunks", []) if c.get("video_id") == video_id]
            if not matching_chunks:
                return {"error": f"No transcript found for video_id '{video_id}'"}
            
            text_lines = [f"[{c.get('start_formatted', '00:00')}] {c.get('text', '')}" for c in matching_chunks]
            full_text = "\n".join(text_lines)
            if len(full_text) > 4000:
                full_text = full_text[:4000] + "\n...[truncated for length]"
                
            return {
                "video_id": video_id,
                "sentence_count": len(matching_chunks),
                "transcript": full_text
            }

        elif name == "extract_video_clips":
            video_id = args.get("video_id", "")
            count = int(args.get("count", 3))
            import narrative_engine
            import clip_scoring
            from vector_store import get_cross_encoder

            if not store:
                return {"error": "Vault store unavailable"}

            # Auto-resolve video_id if not specified
            if not video_id and getattr(store, "videos", None):
                video_id = list(store.videos.keys())[0]

            chunks = [c for c in getattr(store, "chunks", []) if c.get("video_id") == video_id]
            if not chunks:
                return {"error": f"No transcript chunks found for video_id '{video_id}'"}
                
            video_meta = store.videos.get(video_id, {"title": video_id})
            
            # Analyze video narrative and score clip candidates
            analysis = narrative_engine.analyze_video(chunks, max_clips=count)
            candidates = analysis.get("candidates", [])

            if not candidates:
                # Fallback: create candidate blocks directly from sentence chunks
                for i in range(0, min(len(chunks), count * 3), 3):
                    chunk_slice = chunks[i:i+3]
                    txt = " ".join([c.get("text", "") for c in chunk_slice])
                    s_idx = chunk_slice[0].get("sentence_idx", i)
                    e_idx = chunk_slice[-1].get("sentence_idx", i + len(chunk_slice) - 1)
                    candidates.append({
                        "id": f"clip_{i}",
                        "title": f"Highlight {i//3 + 1}",
                        "hook": chunk_slice[0].get("text", "") if chunk_slice else "",
                        "start_time": chunk_slice[0].get("start_formatted", "00:00") if chunk_slice else "00:00",
                        "end_time": chunk_slice[-1].get("end_formatted", "00:00") if chunk_slice else "00:00",
                        "duration": float(chunk_slice[-1].get("end_sec", 0)) - float(chunk_slice[0].get("start_sec", 0)) if chunk_slice else 15.0,
                        "transcript": txt,
                        "sentences": chunk_slice,
                        "start_idx": s_idx,
                        "end_idx": e_idx
                    })

            sentences_by_idx = {s.get("sentence_idx", idx): s for idx, s in enumerate(chunks)}
            corpus_texts = [c.get("text", "") for c in getattr(store, "chunks", [])]
            taste_centroid = clip_scoring.compute_taste_centroid()

            ranked_clips = clip_scoring.rank(
                candidates,
                sentences_by_idx,
                video_id,
                corpus_texts,
                get_cross_encoder,
                max_clips=count,
                taste_centroid=taste_centroid
            )

            clip_summaries = []
            for idx, c in enumerate(ranked_clips, 1):
                clip_summaries.append({
                    "rank": idx,
                    "title": c.get("title", f"Clip {idx}"),
                    "hook": c.get("hook", ""),
                    "start_time": c.get("start_time"),
                    "end_time": c.get("end_time"),
                    "duration": c.get("duration"),
                    "score": round(float(c.get("composite", 0)), 2),
                    "transcript": c.get("transcript", "")[:250] + "..."
                })

            return {
                "video_id": video_id,
                "video_title": video_meta.get("title"),
                "clips_found": len(clip_summaries),
                "clips": clip_summaries
            }

        elif name == "run_studio_tool":
            tool_id = args.get("tool_id", "repurposer")
            input_text = args.get("input_text", "")
            platform = args.get("platform", "")
            video_id = args.get("video_id", "") or ""

            import studio_runner

            if not video_id and getattr(store, "videos", None):
                video_id = list(store.videos.keys())[0]

            tool_inputs = _studio_inputs_for(tool_id, input_text, platform, store, video_id)

            result = studio_runner.run_tool(tool_id=tool_id, inputs=tool_inputs, use_voice_profile=True)
            return {
                "tool_id": tool_id,
                "output": result
            }

        elif name == "get_creator_context":
            import voice_profile
            import platform_rules

            prof = voice_profile.load()
            rules = platform_rules.load()

            return {
                "voice_profile": {
                    "bio": prof.get("bio", ""),
                    "tone": prof.get("tone", ""),
                    "banned_words": prof.get("banned_words", []),
                    "examples": prof.get("examples", [])
                },
                "platform_rules": rules
            }

        elif name == "generate_content_pack":
            return _generate_content_pack(args, store)

        else:
            return {"error": f"Unknown tool name '{name}'"}

    except Exception as exc:
        return {"error": f"Tool execution failed ({name}): {str(exc)}"}
