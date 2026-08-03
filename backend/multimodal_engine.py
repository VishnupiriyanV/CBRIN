import os
import re
import math
import io
import urllib.request
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

CLIP_MODEL = None
HAS_CLIP_MODEL = True

KEYFRAMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "keyframes")


def _enable_hf_offline_if_already_cached():
    """
    huggingface_hub does an online "check for updates" round-trip on every single model
    load by default — even when the model is already fully cached locally. That's the
    actual reason backend boot can take a long time or intermittently fail: each of the
    three HF-hosted models this app loads (embedding, CLIP, cross-encoder reranker) retries
    that check with backoff on a flaky/offline connection before giving up (observed live:
    up to ~30s of retries per model, and in one case the load failed outright and silently
    fell back to a much worse TF-IDF/no-reranker mode instead of just using the cache).

    If every model this app needs is already cached, skip the network check entirely by
    setting HF_HUB_OFFLINE before huggingface_hub is imported (transitively, via
    sentence_transformers below) — this must run before that import for the setting to take
    effect, since huggingface_hub reads it once into a module-level constant. If anything
    isn't cached yet (first run on this machine), leave it unset so it can download normally.
    Respects an explicit HF_HUB_OFFLINE the user/deployment already set.
    """
    if os.environ.get("HF_HUB_OFFLINE") is not None:
        return

    try:
        from huggingface_hub import constants as hf_constants
    except Exception:
        return  # huggingface_hub itself isn't installed; nothing to do here

    required_repos = [
        "sentence-transformers/all-MiniLM-L6-v2",
        "sentence-transformers/clip-ViT-B-32",
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ]

    def _is_cached(repo_id: str) -> bool:
        snapshots_dir = os.path.join(hf_constants.HF_HUB_CACHE, "models--" + repo_id.replace("/", "--"), "snapshots")
        return os.path.isdir(snapshots_dir) and len(os.listdir(snapshots_dir)) > 0

    if all(_is_cached(r) for r in required_repos):
        os.environ["HF_HUB_OFFLINE"] = "1"
        print("[MultimodalEngine] All HF models found in local cache — loading offline (no network round-trip).")


_enable_hf_offline_if_already_cached()

try:
    from sentence_transformers import SentenceTransformer
    from PIL import Image
except Exception as e:
    print(f"[MultimodalEngine] SentenceTransformer/PIL import error: {e}")
    HAS_CLIP_MODEL = False

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

# scikit-learn's 318 standard English stop words plus genuine discourse filler/meta-commentary
# terms — NOT subject-matter words. IMPROVEMENT-PLAN.md 2.7 flagged the old list (100+ words
# including 'problem', 'solution', 'approach', 'process', 'power', 'modern') as overfit to one
# test video: those are exactly the words a tech creator's real content is *about*. Corpus-level
# IDF (see compute_corpus_idf) now does the actual work of demoting terms that recur across the
# library; this list only holds words that are filler in *every* context, not just this video's.
MEDIA_FILLER = {
    'yeah', 'okay', 'sure', 'look', 'said', 'says', 'tell', 'told',
    'actually', 'basically', 'literally', 'something', 'anything', 'everything', 'nothing',
    'gonna', 'wanna', 'gotta', 'today', 'video', 'episode', 'channel', 'subscribe', 'comment',
    'watch', 'click', 'description', 'below', 'people', 'time', 'times',
    'years', 'year', 'think', 'thought', 'believe', 'happen', 'happened', 'happening',
    'shows', 'shown', 'given', 'taken', 'known', 'found',
    'order', 'course', 'seconds', 'minutes', 'hours',
    'quickly', 'slowly', 'heavily',
    'largely', 'mostly', 'overall', 'recently', 'eventually', 'finally', 'specifically',
    'speaker', 'spoken', 'mention'
}

STOPWORDS = set(ENGLISH_STOP_WORDS).union(MEDIA_FILLER)

# Common contraction suffixes, expanded before tokenizing so "doesn't" yields the clean words
# "does" + "not" instead of the word-boundary regex silently truncating it to a bogus "doesn"
# fragment (IMPROVEMENT-PLAN.md 2.7 — this fragment was observed live in implicit_concepts).
_CONTRACTION_EXPANSIONS = [
    (r"n't\b", " not"),
    (r"'re\b", " are"),
    (r"'ve\b", " have"),
    (r"'ll\b", " will"),
    (r"'d\b", " would"),
    (r"'m\b", " am"),
]
_CONTRACTION_PATTERNS = [(re.compile(pat, re.IGNORECASE), repl) for pat, repl in _CONTRACTION_EXPANSIONS]


def _ensure_keyframes_dir():
    os.makedirs(KEYFRAMES_DIR, exist_ok=True)


def preload_models():
    """Preload the CLIP visual model into memory on startup.

    Text embedding is handled entirely by vector_store.py's own EMBEDDING_MODEL — this
    module used to *also* eagerly load a second, separate 'all-MiniLM-L6-v2' instance into
    a TEXT_MODEL global that nothing ever read afterward, doubling that model's load time
    (and RAM) for no reason. Removed rather than fixed forward, since it had no callers."""
    global CLIP_MODEL, HAS_CLIP_MODEL, HAS_OPENCV
    _ensure_keyframes_dir()

    # Re-check OpenCV import in case it was installed dynamically
    if not HAS_OPENCV:
        try:
            import cv2
            globals()['cv2'] = cv2
            HAS_OPENCV = True
            print("[MultimodalEngine] OpenCV (cv2) successfully initialized.")
        except ImportError:
            HAS_OPENCV = False

    if HAS_CLIP_MODEL and CLIP_MODEL is None:
        try:
            print("[MultimodalEngine] Preloading CLIP visual model ('clip-ViT-B-32')...")
            CLIP_MODEL = SentenceTransformer('clip-ViT-B-32')
            print("[MultimodalEngine] CLIP visual model loaded.")
        except Exception as e:
            print(f"[MultimodalEngine] CLIP model preload failed: {e}")
            HAS_CLIP_MODEL = False


class MultimodalEngine:
    """
    Multimodal Context Engine combining:
    1. Whisper segment analysis
    2. CLIP visual scene embedding (via video frame sampling or image URLs)
    3. TF-IDF weighted contextual topic & synthetic question extraction
    4. Positional bigram/trigram phrase detection
    5. Keyframe thumbnail generation
    """

    @staticmethod
    def _expand_contractions(text: str) -> str:
        for pattern, repl in _CONTRACTION_PATTERNS:
            text = pattern.sub(repl, text)
        return text

    @staticmethod
    def compute_corpus_idf(sentence_texts: List[str]) -> Dict[str, float]:
        """
        Document-frequency-based IDF over a batch of sentences (each sentence = one
        "document"). Used in place of a hand-curated blocklist to demote terms that are
        common across *this library* — the actual definition of "uninformative" — rather
        than a fixed list of words someone guessed while looking at one test video
        (IMPROVEMENT-PLAN.md 2.7). Call with the existing library's chunk texts plus the
        new video's sentences so recurring filler is demoted without also suppressing a
        video's own genuinely-central, frequently-repeated topic.
        """
        n_docs = len(sentence_texts)
        if n_docs == 0:
            return {}
        df = Counter()
        for text in sentence_texts:
            expanded = MultimodalEngine._expand_contractions(text.lower())
            words = set(re.findall(r'\b[a-zA-Z]+\b', expanded))
            df.update(words)
        return {w: math.log((n_docs + 1) / (c + 1)) + 1.0 for w, c in df.items()}

    @staticmethod
    def _score_ngram(ngram: str, frequency: int, total_words: int, idf_lookup: Optional[Dict[str, float]] = None) -> float:
        tf = frequency / max(total_words, 1)
        length_bonus = len(ngram.split()) * 0.3
        idf_weight = 1.0
        if idf_lookup:
            words = ngram.split()
            weights = [idf_lookup.get(w, 1.0) for w in words if w]
            if weights:
                idf_weight = sum(weights) / len(weights)
        return tf * idf_weight + length_bonus

    @staticmethod
    def _extract_positional_ngrams(raw_words: List[str], n: int) -> List[str]:
        ngrams = []
        for i in range(len(raw_words) - n + 1):
            window = raw_words[i:i+n]
            if all(len(w) >= 5 and w not in STOPWORDS for w in window):
                ngrams.append(" ".join(window))
        return ngrams

    @staticmethod
    def extract_context(text: str, idf_lookup: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        expanded_text = MultimodalEngine._expand_contractions(text.lower())
        raw_words = re.findall(r'\b[a-zA-Z]+\b', expanded_text)

        meaningful_words = [
            w for w in raw_words
            if len(w) >= 5 and w not in STOPWORDS
        ]

        word_freq = Counter(meaningful_words)
        total_words = len(meaningful_words)

        bigrams = MultimodalEngine._extract_positional_ngrams(raw_words, 2)
        trigrams = MultimodalEngine._extract_positional_ngrams(raw_words, 3)

        bigram_freq = Counter(bigrams)
        trigram_freq = Counter(trigrams)

        scored_candidates = []

        for word, freq in word_freq.items():
            if freq >= 2 or len(word) >= 7:
                score = MultimodalEngine._score_ngram(word, freq, total_words, idf_lookup)
                scored_candidates.append((word, score, 'unigram'))

        for bigram, freq in bigram_freq.items():
            parts = bigram.split()
            if freq >= 2 or all(len(p) >= 6 for p in parts):
                score = MultimodalEngine._score_ngram(bigram, freq, total_words, idf_lookup)
                scored_candidates.append((bigram, score, 'bigram'))

        for trigram, freq in trigram_freq.items():
            if freq >= 2:
                score = MultimodalEngine._score_ngram(trigram, freq, total_words, idf_lookup)
                scored_candidates.append((trigram, score, 'trigram'))

        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        final_concepts = []
        used_words = set()
        for candidate, score, gram_type in scored_candidates:
            candidate_words = set(candidate.split())
            if gram_type == 'unigram' and candidate_words.issubset(used_words):
                continue
            final_concepts.append(candidate)
            used_words.update(candidate_words)
            if len(final_concepts) >= 6:
                break

        if len(final_concepts) < 3:
            for word, freq in word_freq.most_common(10):
                if word not in used_words and len(word) >= 5:
                    final_concepts.append(word)
                    used_words.add(word)
                    if len(final_concepts) >= 4:
                        break

        if len(final_concepts) >= 2:
            top = final_concepts[0]
            if ' ' in top:
                section_topic = top.title()
            else:
                section_topic = f"{final_concepts[0].title()} & {final_concepts[1].title()}"
        elif len(final_concepts) == 1:
            section_topic = final_concepts[0].title()
        else:
            section_topic = "General Discussion"

        questions_answered = []
        if len(final_concepts) >= 2:
            top_concept = final_concepts[0].replace('_', ' ')
            second_concept = final_concepts[1].replace('_', ' ')
            questions_answered.append(
                f"What is the relationship between {top_concept} and {second_concept}?"
            )
            if len(final_concepts) >= 3:
                third_concept = final_concepts[2].replace('_', ' ')
                questions_answered.append(
                    f"What role does {third_concept} play in this discussion?"
                )
        elif len(final_concepts) == 1:
            questions_answered.append(
                f"What are the key points about {final_concepts[0]}?"
            )
        else:
            questions_answered.append("What concept is addressed in this segment?")

        return {
            "section_topic": section_topic,
            "questions_answered": questions_answered,
            "implicit_concepts": final_concepts
        }

    @staticmethod
    def generate_enriched_text(chunk_text: str, context: Dict[str, Any]) -> str:
        """
        Text actually fed to the dense embedding model. Previously prepended a fixed
        template ("Topic: X. Questions: Y. Concepts: Z. Spoken: ...") whose literal
        boilerplate words — plus concepts duplicated once raw and once inside a synthetic
        question — appeared in *every* chunk and ate into the 384-dim MiniLM vector's
        real signal (IMPROVEMENT-PLAN.md 2.6). Now just prepends the topic: enough to
        nudge retrieval toward the right section without drowning out the actual words
        that were spoken.
        """
        topic = context.get('section_topic', '')
        if topic and topic != "General Discussion":
            return f"{topic}. {chunk_text}"
        return chunk_text

    # Hard caps so transcripts with no [.!?] punctuation at all (common in YouTube
    # auto-captions) still produce bounded chunks instead of one giant "sentence" per video.
    MAX_SENTENCE_SECONDS = 40.0
    MAX_SENTENCE_WORDS = 80

    @staticmethod
    def segment_transcript_into_sentences(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Split transcript segments into punctuated sentence units via an explicit state
        machine. Preserves start/end timestamps and assigns a stable sentence_idx.

        Handles, by construction (see tests in backend/tests/test_multimodal_engine.py):
        - segments with no punctuation at all -> hard-capped at MAX_SENTENCE_SECONDS /
          MAX_SENTENCE_WORDS rather than becoming one unbounded sentence.
        - a single segment containing multiple punctuated sentences -> each flush resets
          the pending sentence's start time to the *current segment's* start, not to None,
          so a second sentence within the same segment can't hit math.floor(None).
        - empty segments -> skipped.
        """
        if not segments:
            return []

        sentences: List[Dict[str, Any]] = []
        current_words: List[str] = []
        sentence_start_sec: Optional[float] = None
        sentence_end_sec: float = 0.0
        sentence_idx = 0

        def flush():
            nonlocal current_words, sentence_start_sec, sentence_end_sec, sentence_idx
            full_text = " ".join(current_words).strip()
            if full_text and len(full_text.split()) >= 3 and sentence_start_sec is not None:
                sentences.append({
                    "sentence_idx": sentence_idx,
                    "text": full_text,
                    "start_sec": math.floor(sentence_start_sec),
                    "end_sec": math.ceil(sentence_end_sec),
                })
                sentence_idx += 1
            current_words = []
            sentence_start_sec = None

        for seg in segments:
            seg_start = float(seg.get('start', 0.0))
            seg_duration = float(seg.get('duration', 0.0))
            seg_text = seg.get('text', '').strip()

            if not seg_text:
                continue

            # Split segment text by sentence punctuation [.!?], keeping the punctuation.
            raw_parts = re.split(r'([.!?]+)', seg_text)

            for i in range(0, len(raw_parts), 2):
                text_part = raw_parts[i].strip()
                punct_part = raw_parts[i + 1] if i + 1 < len(raw_parts) else ''

                if not text_part and not punct_part:
                    continue

                if text_part:
                    if sentence_start_sec is None:
                        # Reset to *this segment's* start, never left as None — the bug
                        # that crashed ingest on any segment containing 2+ sentences.
                        sentence_start_sec = seg_start
                    current_words.append(text_part + punct_part)
                    sentence_end_sec = seg_start + seg_duration

                hit_punctuation = bool(punct_part)
                hit_word_cap = len(current_words) > 0 and len(" ".join(current_words).split()) >= MultimodalEngine.MAX_SENTENCE_WORDS
                hit_time_cap = (
                    sentence_start_sec is not None
                    and (sentence_end_sec - sentence_start_sec) >= MultimodalEngine.MAX_SENTENCE_SECONDS
                )

                if hit_punctuation or hit_word_cap or hit_time_cap:
                    flush()

        flush()

        return sentences

    @staticmethod
    def extract_keyframe_and_embed(
        source_target: Optional[str],
        timestamp_sec: float,
        chunk_id: str,
        image_url: Optional[str] = None
    ) -> Tuple[Optional[np.ndarray], Optional[str], Optional[str]]:
        """
        Extract keyframe or image, compute CLIP visual embedding, and save thumbnail.
        Supports:
        1. Local video files (.mp4/.mov) via OpenCV frame sampling — a real per-moment frame.
        2. Image URLs (YouTube thumbnails / Web images) via PIL & HTTP fetch — for YouTube
           this is the *same* video-level thumbnail for every chunk of that video, so it
           cannot actually localize a moment (IMPROVEMENT-PLAN.md 2.10).
        Returns (visual_vector, keyframe_url, source_kind), where source_kind is
        'frame' (real per-moment sample), 'thumbnail' (shared video-level image), or None.
        """
        global CLIP_MODEL, HAS_OPENCV
        _ensure_keyframes_dir()

        if CLIP_MODEL is None and HAS_CLIP_MODEL:
            preload_models()

        if CLIP_MODEL is None:
            return None, None, None

        keyframe_filename = f"{chunk_id}.jpg"
        keyframe_path = os.path.join(KEYFRAMES_DIR, keyframe_filename)
        # Relative path — the frontend resolves it against its configured API origin
        # (VITE_API_URL). A hardcoded absolute URL here gets baked into every persisted
        # chunk, so changing the backend port breaks every existing thumbnail (hygiene).
        keyframe_url = f"/api/keyframe/{chunk_id}"

        # Option A: Local video file via OpenCV — genuine per-moment frame.
        if source_target and os.path.exists(source_target) and HAS_OPENCV:
            try:
                cap = cv2.VideoCapture(source_target)
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                frame_number = int(timestamp_sec * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ret, frame = cap.read()
                cap.release()

                if ret and frame is not None:
                    cv2.imwrite(keyframe_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(rgb_frame)
                    visual_vec = CLIP_MODEL.encode(pil_img, convert_to_numpy=True, normalize_embeddings=True)
                    return visual_vec, keyframe_url, 'frame'
            except Exception as e:
                print(f"[MultimodalEngine] OpenCV frame sampling error at {timestamp_sec}s: {e}")

        # Option B: Image URL (e.g. YouTube thumbnail poster) via PIL — video-level, not
        # per-moment: every chunk of the same video gets this same image.
        target_url = image_url or (source_target if source_target and source_target.startswith('http') else None)
        if target_url:
            try:
                req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                with urllib.request.urlopen(req, timeout=8) as response:
                    img_bytes = response.read()
                    pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    pil_img.save(keyframe_path, "JPEG", quality=85)
                    visual_vec = CLIP_MODEL.encode(pil_img, convert_to_numpy=True, normalize_embeddings=True)
                    return visual_vec, keyframe_url, 'thumbnail'
            except Exception as e:
                print(f"[MultimodalEngine] Image URL visual embedding failed for {target_url}: {e}")

        return None, None, None

    @staticmethod
    def embed_text_clip(query: str) -> Optional[np.ndarray]:
        """
        Embed query using CLIP text encoder for visual scene search.
        """
        global CLIP_MODEL
        if CLIP_MODEL is None and HAS_CLIP_MODEL:
            preload_models()

        if CLIP_MODEL is None or not query.strip():
            return None
        try:
            return CLIP_MODEL.encode(query, convert_to_numpy=True, normalize_embeddings=True)
        except Exception as e:
            print(f"[MultimodalEngine] CLIP text encoding failed: {e}")
            return None
