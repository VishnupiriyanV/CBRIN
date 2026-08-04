"""
Per-platform caption/hashtag/link conventions for the Caption Reformatter tool (STUDIO
tool 5). creator-tools-integration-spec.md §5 is explicit that these rules "shift" over
time and must live in an editable config, not be baked into a prompt — same load/save
shape as brand_kit.py, applied to platform conventions instead of visual style.

Character limits below are the tool's enforced hard caps used by studio_prompts.py's
caption validator (regenerate on overflow, never truncate) — not necessarily the
platform's absolute technical maximum, but the length past which a caption stops reading
as platform-native for that surface. Editable via PUT /api/studio/platform_rules without
a code change, exactly because these numbers will go stale.
"""
import json
import os
from typing import Any, Dict

import paths

DEFAULT_PLATFORM_RULES: Dict[str, Dict[str, Any]] = {
    "tiktok": {
        "label": "TikTok",
        "style": "Short, hook-first, casual",
        "char_limit": 150,
        "hashtag_min": 3,
        "hashtag_max": 5,
        "hashtag_placement": "in-caption",
        "links_clickable": False,
    },
    "instagram": {
        "label": "Instagram",
        "style": "Hook line + break + body",
        "char_limit": 2200,
        "hashtag_min": 3,
        "hashtag_max": 8,
        "hashtag_placement": "avoid spam blocks",
        "links_clickable": False,
    },
    "youtube_short": {
        "label": "YouTube Shorts",
        "style": "Very short, keyword-aware",
        "char_limit": 100,
        "hashtag_min": 2,
        "hashtag_max": 3,
        "hashtag_placement": "in-description",
        "links_clickable": True,
    },
    "youtube_long": {
        "label": "YouTube (long-form)",
        "style": "Full description + timestamps + links",
        "char_limit": 5000,
        "hashtag_min": 2,
        "hashtag_max": 3,
        "hashtag_placement": "in-description",
        "links_clickable": True,
    },
    "x": {
        "label": "X",
        "style": "One idea, punchy",
        "char_limit": 280,
        "hashtag_min": 0,
        "hashtag_max": 2,
        "hashtag_placement": "inline",
        "links_clickable": True,
    },
    "linkedin": {
        "label": "LinkedIn",
        "style": "Hook + line breaks + takeaway",
        "char_limit": 3000,
        "hashtag_min": 0,
        "hashtag_max": 3,
        "hashtag_placement": "end, deprioritized",
        "links_clickable": True,
    },
}


def load() -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(paths.PLATFORM_RULES_FILE):
        return json.loads(json.dumps(DEFAULT_PLATFORM_RULES))  # deep copy
    try:
        with open(paths.PLATFORM_RULES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        merged = json.loads(json.dumps(DEFAULT_PLATFORM_RULES))
        for platform, patch in data.items():
            if platform in merged:
                merged[platform].update(patch)
            else:
                merged[platform] = patch
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_PLATFORM_RULES))


def save(rules: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    with open(paths.PLATFORM_RULES_FILE, 'w', encoding='utf-8') as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)
    return rules


def apply_edit(patch: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    current = load()
    for platform, fields in patch.items():
        if platform in current and isinstance(fields, dict):
            current[platform].update(fields)
        else:
            current[platform] = fields
    return save(current)


def get(platform: str) -> Dict[str, Any]:
    return load().get(platform, {})
