"""
Voice Profile: the per-creator tone/niche settings injected into every STUDIO tool prompt
(creator-tools-integration-spec.md §0.3 — "the main differentiator against people just using
raw ChatGPT"). Same load/save/apply_edit/autoseed shape as brand_kit.py, applied to text
generation instead of visual rendering.

Auto-seed pulls a niche hint and sample content straight from the creator's own indexed
library via the same corpus-IDF machinery narrative_engine already uses for quotability
(MultimodalEngine.compute_corpus_idf), rather than asking the creator to fill in a blank
form on first run. Any manual edit flips auto_seeded to False, so a later autoseed() call
never silently overwrites a deliberate choice.
"""
import json
import os
from typing import Any, Dict, List, Optional

import atomic_io
import paths

DEFAULT_VOICE_PROFILE: Dict[str, Any] = {
    "niche": "",
    "audience": "",
    "tone": ["conversational", "direct"],
    "banned_words": ["delve", "unlock", "game-changer", "in today's world"],
    "sample_content": [],
    "default_platforms": ["linkedin", "x", "instagram"],
    "cta_style": "",
    "auto_seeded": True,
}

MAX_NICHE_TERMS = 5
MAX_SAMPLE_CONTENT = 3
MIN_SAMPLE_CHARS = 120  # skip throwaway one-liners when picking sample_content


def load() -> Dict[str, Any]:
    if not os.path.exists(paths.VOICE_PROFILE_FILE):
        return dict(DEFAULT_VOICE_PROFILE)
    try:
        with open(paths.VOICE_PROFILE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        merged = dict(DEFAULT_VOICE_PROFILE)
        merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULT_VOICE_PROFILE)


def save(profile: Dict[str, Any]) -> Dict[str, Any]:
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    # Atomic — user-authored voice profile; unrecoverable if truncated.
    atomic_io.write_json(paths.VOICE_PROFILE_FILE, profile)
    return profile


def apply_edit(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a partial update into the persisted profile. Any edit flips auto_seeded to
    False so a later autoseed() call never silently overwrites a creator's deliberate
    choice (same idiom as brand_kit.apply_edit)."""
    current = load()
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            current[key].update(value)
        else:
            current[key] = value
    current["auto_seeded"] = False
    return save(current)


def autoseed(chunk_texts: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
    """
    Derive a starting niche hint + sample_content from the creator's own indexed library.
    `chunk_texts` is the caller-supplied list of spoken sentence texts across the library
    (main.py passes `[c['text'] for c in store.chunks]`) — voice_profile.py does not import
    vector_store itself, keeping this module's dependency surface at just `paths` + stdlib.

    Refuses to overwrite an already-edited profile unless force=True, mirroring
    brand_kit.autoseed's "auto-seeded, not auto-decided" guarantee.
    """
    current = load()
    if not current.get("auto_seeded", True) and not force:
        raise ValueError(
            "Voice profile has been manually edited — re-seeding would overwrite those "
            "choices. Pass force=True to overwrite anyway."
        )

    niche = ""
    sample_content: List[str] = []

    texts = chunk_texts or []
    if texts:
        from multimodal_engine import MultimodalEngine

        idf = MultimodalEngine.compute_corpus_idf(texts)
        # Distinctive-for-this-library terms, ranked by IDF weight — the same "uninformative
        # if common across the corpus" logic used for concept extraction, repurposed as a
        # niche hint rather than a search filter.
        ranked = sorted(idf.items(), key=lambda kv: -kv[1])
        top_terms = [w for w, _score in ranked if len(w) >= 5][:MAX_NICHE_TERMS]
        niche = ", ".join(top_terms)

        # Longest sentences make the most useful tone samples; a one-word "yeah" chunk
        # teaches the model nothing about cadence.
        candidates = [t.strip() for t in texts if len(t.strip()) >= MIN_SAMPLE_CHARS]
        candidates.sort(key=len, reverse=True)
        sample_content = candidates[:MAX_SAMPLE_CONTENT]

    new_profile = dict(DEFAULT_VOICE_PROFILE)
    new_profile["niche"] = niche
    new_profile["sample_content"] = sample_content
    new_profile["tone"] = current.get("tone", DEFAULT_VOICE_PROFILE["tone"])
    new_profile["banned_words"] = current.get("banned_words", DEFAULT_VOICE_PROFILE["banned_words"])
    new_profile["default_platforms"] = current.get("default_platforms", DEFAULT_VOICE_PROFILE["default_platforms"])
    new_profile["cta_style"] = current.get("cta_style", DEFAULT_VOICE_PROFILE["cta_style"])
    new_profile["audience"] = current.get("audience", DEFAULT_VOICE_PROFILE["audience"])
    new_profile["auto_seeded"] = True

    return save(new_profile)


def to_prompt_block(profile: Optional[Dict[str, Any]] = None) -> str:
    """
    Render the profile as the block injected into every STUDIO system prompt. Kept as a
    single function so every tool formats the profile identically — if this changes, every
    tool's tone consistency changes with it, which is the point.
    """
    p = profile if profile is not None else load()

    lines = ["Voice Profile — match this creator's tone:"]
    if p.get("niche"):
        lines.append(f"- Niche: {p['niche']}")
    if p.get("audience"):
        lines.append(f"- Audience: {p['audience']}")
    if p.get("tone"):
        lines.append(f"- Tone: {', '.join(p['tone'])}")
    if p.get("cta_style"):
        lines.append(f"- CTA style: {p['cta_style']}")
    if p.get("banned_words"):
        lines.append(f"- Never use these words/phrases: {', '.join(p['banned_words'])}")
    if p.get("sample_content"):
        lines.append("- Sample writing from this creator (match this voice, do not quote it):")
        for sample in p["sample_content"]:
            lines.append(f'  "{sample}"')

    if len(lines) == 1:
        return "No voice profile is set. Write in a clear, direct, platform-native style."
    return "\n".join(lines)
