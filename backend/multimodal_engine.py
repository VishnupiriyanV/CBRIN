import os
import re
import math
import io
import urllib.request
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

TEXT_MODEL = None
CLIP_MODEL = None
HAS_TEXT_MODEL = True
HAS_CLIP_MODEL = True

KEYFRAMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "keyframes")

try:
    from sentence_transformers import SentenceTransformer
    from PIL import Image
except Exception as e:
    print(f"[MultimodalEngine] SentenceTransformer/PIL import error: {e}")
    HAS_TEXT_MODEL = False
    HAS_CLIP_MODEL = False

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

# Combine scikit-learn's 318 standard English stop words with video transcript & conversational filler terms
MEDIA_FILLER = {
    'yeah', 'okay', 'sure', 'bunch', 'stuff', 'look', 'said', 'says', 'tell', 'told',
    'boring', 'actually', 'basically', 'literally', 'something', 'anything', 'everything', 'nothing',
    'gonna', 'wanna', 'gotta', 'today', 'video', 'episode', 'channel', 'subscribe', 'comment',
    'watch', 'click', 'check', 'link', 'description', 'below', 'people', 'world', 'time', 'times',
    'years', 'year', 'think', 'thought', 'believe', 'happen', 'happened', 'happening', 'example',
    'number', 'place', 'shows', 'shown', 'given', 'taken', 'known', 'found', 'based', 'created',
    'building', 'create', 'build', 'allows', 'allow', 'able', 'order', 'course', 'seconds', 'minutes',
    'hours', 'current', 'worth', 'count', 'handle', 'approach', 'appears', 'variety', 'process',
    'stored', 'quietly', 'shaped', 'modern', 'oldest', 'products', 'things', 'biggest', 'smallest',
    'massive', 'entire', 'quickly', 'slowly', 'heavily', 'launching', 'creating', 'managing',
    'retrieving', 'storing', 'backed', 'power', 'powered', 'billion', 'billions', 'million', 'millions',
    'thousand', 'hundred', 'thousands', 'hundreds', 'lifting', 'heavy', 'light', 'recording', 'recorded',
    'sensation', 'problem', 'solution', 'solutions', 'largely', 'intensive', 'extensive', 'interactive',
    'mostly', 'overall', 'recently', 'eventually', 'finally', 'specifically', 'discuss', 'discussion',
    'speaker', 'spoken', 'mention'
}

STOPWORDS = set(ENGLISH_STOP_WORDS).union(MEDIA_FILLER)


def _ensure_keyframes_dir():
    os.makedirs(KEYFRAMES_DIR, exist_ok=True)


def preload_models():
    """Preload SentenceTransformer text model and CLIP visual model into memory on startup."""
    global TEXT_MODEL, CLIP_MODEL, HAS_TEXT_MODEL, HAS_CLIP_MODEL, HAS_OPENCV
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

    if HAS_TEXT_MODEL and TEXT_MODEL is None:
        try:
            print("[MultimodalEngine] Preloading text embedding model ('all-MiniLM-L6-v2')...")
            TEXT_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
            print("[MultimodalEngine] Text embedding model loaded.")
        except Exception as e:
            print(f"[MultimodalEngine] Text model preload failed: {e}")
            HAS_TEXT_MODEL = False

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
    def _score_ngram(ngram: str, frequency: int, total_words: int) -> float:
        tf = frequency / max(total_words, 1)
        length_bonus = len(ngram.split()) * 0.3
        return tf + length_bonus

    @staticmethod
    def _extract_positional_ngrams(raw_words: List[str], n: int) -> List[str]:
        ngrams = []
        for i in range(len(raw_words) - n + 1):
            window = raw_words[i:i+n]
            if all(len(w) >= 5 and w not in STOPWORDS for w in window):
                ngrams.append(" ".join(window))
        return ngrams

    @staticmethod
    def extract_context(text: str) -> Dict[str, Any]:
        raw_words = re.findall(r'\b[a-zA-Z]+\b', text.lower())

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
                score = MultimodalEngine._score_ngram(word, freq, total_words)
                scored_candidates.append((word, score, 'unigram'))

        for bigram, freq in bigram_freq.items():
            parts = bigram.split()
            if freq >= 2 or all(len(p) >= 6 for p in parts):
                score = MultimodalEngine._score_ngram(bigram, freq, total_words)
                scored_candidates.append((bigram, score, 'bigram'))

        for trigram, freq in trigram_freq.items():
            if freq >= 2:
                score = MultimodalEngine._score_ngram(trigram, freq, total_words)
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
        topic = context.get('section_topic', '')
        questions = " ".join(context.get('questions_answered', []))
        concepts = " ".join(context.get('implicit_concepts', []))
        return f"Topic: {topic}. Questions: {questions}. Concepts: {concepts}. Spoken: {chunk_text}"

    @staticmethod
    def segment_transcript_into_sentences(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Split transcript segment list into punctuated sentence units.
        Preserves start/end timestamps, duration, and sentence index.
        """
        if not segments:
            return []

        sentences = []
        current_words = []
        sentence_start_sec = None
        sentence_end_sec = 0.0
        sentence_idx = 0

        for seg in segments:
            seg_start = float(seg.get('start', 0.0))
            seg_duration = float(seg.get('duration', 0.0))
            seg_text = seg.get('text', '').strip()

            if not seg_text:
                continue

            if sentence_start_sec is None:
                sentence_start_sec = seg_start

            # Split segment text by sentence punctuation [.!?]
            raw_parts = re.split(r'([.!?]+)', seg_text)

            for i in range(0, len(raw_parts), 2):
                text_part = raw_parts[i].strip()
                punct_part = raw_parts[i+1] if i+1 < len(raw_parts) else ''

                if text_part:
                    current_words.append(text_part + punct_part)
                    sentence_end_sec = seg_start + seg_duration

                if punct_part or (i + 2 < len(raw_parts)):
                    full_text = " ".join(current_words).strip()
                    if len(full_text.split()) >= 3:
                        sentences.append({
                            "sentence_idx": sentence_idx,
                            "text": full_text,
                            "start_sec": math.floor(sentence_start_sec),
                            "end_sec": math.ceil(sentence_end_sec),
                        })
                        sentence_idx += 1
                    current_words = []
                    sentence_start_sec = None

        if current_words and sentence_start_sec is not None:
            full_text = " ".join(current_words).strip()
            if len(full_text.split()) >= 3:
                sentences.append({
                    "sentence_idx": sentence_idx,
                    "text": full_text,
                    "start_sec": math.floor(sentence_start_sec),
                    "end_sec": math.ceil(sentence_end_sec),
                })

        return sentences

    @staticmethod
    def extract_keyframe_and_embed(
        source_target: Optional[str],
        timestamp_sec: float,
        chunk_id: str,
        image_url: Optional[str] = None
    ) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Extract keyframe or image, compute CLIP visual embedding, and save thumbnail.
        Supports:
        1. Local video files (.mp4/.mov) via OpenCV frame sampling.
        2. Image URLs (YouTube thumbnails / Web images) via PIL & HTTP fetch.
        Returns tuple: (visual_vector, keyframe_url)
        """
        global CLIP_MODEL, HAS_OPENCV
        _ensure_keyframes_dir()

        if CLIP_MODEL is None and HAS_CLIP_MODEL:
            preload_models()

        if CLIP_MODEL is None:
            return None, None

        keyframe_filename = f"{chunk_id}.jpg"
        keyframe_path = os.path.join(KEYFRAMES_DIR, keyframe_filename)
        keyframe_url = f"http://localhost:8000/api/keyframe/{chunk_id}"

        # Option A: Local video file via OpenCV
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
                    return visual_vec, keyframe_url
            except Exception as e:
                print(f"[MultimodalEngine] OpenCV frame sampling error at {timestamp_sec}s: {e}")

        # Option B: Image URL (e.g. YouTube thumbnail poster) via PIL
        target_url = image_url or (source_target if source_target and source_target.startswith('http') else None)
        if target_url:
            try:
                req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                with urllib.request.urlopen(req, timeout=8) as response:
                    img_bytes = response.read()
                    pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    pil_img.save(keyframe_path, "JPEG", quality=85)
                    visual_vec = CLIP_MODEL.encode(pil_img, convert_to_numpy=True, normalize_embeddings=True)
                    return visual_vec, keyframe_url
            except Exception as e:
                print(f"[MultimodalEngine] Image URL visual embedding failed for {target_url}: {e}")

        return None, None

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
