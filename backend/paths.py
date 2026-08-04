"""
Single source of truth for every on-disk data path this backend touches.

Why this file exists: vector_store.py and multimodal_engine.py each used to compute their
own DATA_DIR-derived constants at import time. Tests only monkeypatched two of them
(KEYFRAMES_DIR, MEDIA_DIR — see backend/tests/test_vector_store.py), so _save_to_disk() calls
during tests silently wrote through to the real backend/data/ for everything else
(chunks.json, videos.json, embeddings.npy, ...). Centralizing every path here, mutable via
use_root(), gives the test suite exactly one seam to redirect — see
backend/tests/conftest.py's autouse `redirect_data` fixture.

Consumers must read these as `paths.CHUNKS_FILE` (attribute access on the module), never
`from paths import CHUNKS_FILE` — the latter binds a copy at import time that `use_root()`
can no longer reach.
"""
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

MEDIA_DIR = os.path.join(DATA_DIR, "media")
KEYFRAMES_DIR = os.path.join(DATA_DIR, "keyframes")
CHUNKS_FILE = os.path.join(DATA_DIR, "chunks.json")
EMBEDDINGS_FILE = os.path.join(DATA_DIR, "embeddings.npy")
VISUAL_EMBEDDINGS_FILE = os.path.join(DATA_DIR, "visual_embeddings.npy")
VIDEOS_FILE = os.path.join(DATA_DIR, "videos.json")
HIGHLIGHTS_FILE = os.path.join(DATA_DIR, "highlights.json")
INDEX_META_FILE = os.path.join(DATA_DIR, "index_meta.json")

# ENGINE (Layer 3)
WORDS_DIR = os.path.join(DATA_DIR, "words")
CLIPS_DIR = os.path.join(DATA_DIR, "clips")
CLIPS_FILE = os.path.join(DATA_DIR, "clips.json")
BRAND_KIT_FILE = os.path.join(DATA_DIR, "brand_kit.json")
JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")
CLIP_FEEDBACK_FILE = os.path.join(DATA_DIR, "clip_feedback.json")

# STUDIO (Layer 4)
VOICE_PROFILE_FILE = os.path.join(DATA_DIR, "voice_profile.json")
PLATFORM_RULES_FILE = os.path.join(DATA_DIR, "platform_rules.json")
TOOL_RUNS_FILE = os.path.join(DATA_DIR, "tool_runs.json")
TOOL_USAGE_FILE = os.path.join(DATA_DIR, "tool_usage.json")


def use_root(root: str) -> None:
    """Repoint every path constant at `root`. Tests call this via the redirect_data fixture
    so nothing a test does can ever touch the real backend/data/ directory."""
    global DATA_DIR, MEDIA_DIR, KEYFRAMES_DIR, CHUNKS_FILE, EMBEDDINGS_FILE
    global VISUAL_EMBEDDINGS_FILE, VIDEOS_FILE, HIGHLIGHTS_FILE, INDEX_META_FILE
    global WORDS_DIR, CLIPS_DIR, CLIPS_FILE, BRAND_KIT_FILE, JOBS_FILE, CLIP_FEEDBACK_FILE
    global VOICE_PROFILE_FILE, PLATFORM_RULES_FILE, TOOL_RUNS_FILE, TOOL_USAGE_FILE

    DATA_DIR = root
    MEDIA_DIR = os.path.join(DATA_DIR, "media")
    KEYFRAMES_DIR = os.path.join(DATA_DIR, "keyframes")
    CHUNKS_FILE = os.path.join(DATA_DIR, "chunks.json")
    EMBEDDINGS_FILE = os.path.join(DATA_DIR, "embeddings.npy")
    VISUAL_EMBEDDINGS_FILE = os.path.join(DATA_DIR, "visual_embeddings.npy")
    VIDEOS_FILE = os.path.join(DATA_DIR, "videos.json")
    HIGHLIGHTS_FILE = os.path.join(DATA_DIR, "highlights.json")
    INDEX_META_FILE = os.path.join(DATA_DIR, "index_meta.json")

    WORDS_DIR = os.path.join(DATA_DIR, "words")
    CLIPS_DIR = os.path.join(DATA_DIR, "clips")
    CLIPS_FILE = os.path.join(DATA_DIR, "clips.json")
    BRAND_KIT_FILE = os.path.join(DATA_DIR, "brand_kit.json")
    JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")
    CLIP_FEEDBACK_FILE = os.path.join(DATA_DIR, "clip_feedback.json")

    VOICE_PROFILE_FILE = os.path.join(DATA_DIR, "voice_profile.json")
    PLATFORM_RULES_FILE = os.path.join(DATA_DIR, "platform_rules.json")
    TOOL_RUNS_FILE = os.path.join(DATA_DIR, "tool_runs.json")
    TOOL_USAGE_FILE = os.path.join(DATA_DIR, "tool_usage.json")
