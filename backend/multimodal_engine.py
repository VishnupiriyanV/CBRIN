import os
import re
import math
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
    global TEXT_MODEL, CLIP_MODEL, HAS_TEXT_MODEL, HAS_CLIP_MODEL
    _ensure_keyframes_dir()

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
    2. CLIP visual scene embedding (via frame sampling)
    3. TF-IDF weighted contextual topic & synthetic question extraction
    4. Bigram/trigram phrase detection for meaningful multi-word concepts
    5. Keyframe thumbnail generation
    """

    @staticmethod
    def _extract_ngrams(words: List[str], n: int) -> List[str]:
        """Extract n-grams from a list of cleaned words."""
        if len(words) < n:
            return []
        return [" ".join(words[i:i+n]) for i in range(len(words) - n + 1)]

    @staticmethod
    def _score_ngram(ngram: str, frequency: int, total_words: int) -> float:
        """
        Score an n-gram by its frequency relative to total words and its word count.
        Bigrams/trigrams get a boost because multi-word phrases are more specific.
        """
        tf = frequency / max(total_words, 1)
        length_bonus = len(ngram.split()) * 0.3  # bigrams=0.6, trigrams=0.9
        return tf + length_bonus

    @staticmethod
    def _extract_positional_ngrams(raw_words: List[str], n: int) -> List[str]:
        """
        Extract n-grams from the ORIGINAL word sequence, keeping only those
        where ALL constituent words pass the meaningful filter (>= 5 chars, not stopwords).
        This ensures bigrams like 'relational database' are real adjacent phrases from the text,
        not artifacts of stopword removal.
        """
        ngrams = []
        for i in range(len(raw_words) - n + 1):
            window = raw_words[i:i+n]
            if all(len(w) >= 5 and w not in STOPWORDS for w in window):
                ngrams.append(" ".join(window))
        return ngrams

    @staticmethod
    def extract_context(text: str) -> Dict[str, Any]:
        """
        Extract section topic, synthetic questions answered, and implicit concepts
        using frequency-weighted ranking with positional bigram/trigram phrase detection.
        Produces contextually meaningful topics and questions.
        """
        # Tokenize: preserve original word order for positional n-gram extraction
        raw_words = re.findall(r'\b[a-zA-Z]+\b', text.lower())

        # Filter: meaningful unigrams (>= 5 chars, not stopwords)
        meaningful_words = [
            w for w in raw_words
            if len(w) >= 5 and w not in STOPWORDS
        ]

        # Count word frequencies for TF-IDF style ranking
        word_freq = Counter(meaningful_words)
        total_words = len(meaningful_words)

        # --- Positional Bigram and Trigram extraction from ORIGINAL word order ---
        bigrams = MultimodalEngine._extract_positional_ngrams(raw_words, 2)
        trigrams = MultimodalEngine._extract_positional_ngrams(raw_words, 3)

        bigram_freq = Counter(bigrams)
        trigram_freq = Counter(trigrams)

        # Score all candidates
        scored_candidates = []

        # Score unigrams: those appearing 2+ times or 7+ chars (domain-specific terms)
        for word, freq in word_freq.items():
            if freq >= 2 or len(word) >= 7:
                score = MultimodalEngine._score_ngram(word, freq, total_words)
                scored_candidates.append((word, score, 'unigram'))

        # Score bigrams: appearing 2+ times, or both words >= 6 chars (technical/domain terms)
        for bigram, freq in bigram_freq.items():
            parts = bigram.split()
            if freq >= 2 or all(len(p) >= 6 for p in parts):
                score = MultimodalEngine._score_ngram(bigram, freq, total_words)
                scored_candidates.append((bigram, score, 'bigram'))

        # Score trigrams: only those appearing 2+ times (high confidence)
        for trigram, freq in trigram_freq.items():
            if freq >= 2:
                score = MultimodalEngine._score_ngram(trigram, freq, total_words)
                scored_candidates.append((trigram, score, 'trigram'))

        # Sort by score descending
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        # Deduplicate: prefer higher-scoring phrases, suppress subsumed unigrams
        final_concepts = []
        used_words = set()
        for candidate, score, gram_type in scored_candidates:
            candidate_words = set(candidate.split())
            # Skip unigrams whose word is already covered by a higher-scoring multi-word phrase
            if gram_type == 'unigram' and candidate_words.issubset(used_words):
                continue
            final_concepts.append(candidate)
            used_words.update(candidate_words)
            if len(final_concepts) >= 6:
                break

        # Fallback: if too few concepts, add top-frequency single words
        if len(final_concepts) < 3:
            for word, freq in word_freq.most_common(10):
                if word not in used_words and len(word) >= 5:
                    final_concepts.append(word)
                    used_words.add(word)
                    if len(final_concepts) >= 4:
                        break

        # --- Generate section topic ---
        if len(final_concepts) >= 2:
            top = final_concepts[0]
            if ' ' in top:
                # Multi-word phrase makes a great standalone topic
                section_topic = top.title()
            else:
                section_topic = f"{final_concepts[0].title()} & {final_concepts[1].title()}"
        elif len(final_concepts) == 1:
            section_topic = final_concepts[0].title()
        else:
            section_topic = "General Discussion"

        # --- Generate synthetic questions ---
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
        Combine transcript text with section topic, synthetic questions, and concepts for hybrid embedding.
        """
        topic = context.get('section_topic', '')
        questions = " ".join(context.get('questions_answered', []))
        concepts = " ".join(context.get('implicit_concepts', []))
        return f"Topic: {topic}. Questions: {questions}. Concepts: {concepts}. Spoken: {chunk_text}"

    @staticmethod
    def extract_keyframe_and_embed(media_path: str, timestamp_sec: float, chunk_id: str) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Sample video frame at target timestamp, save thumbnail JPEG to disk, and compute CLIP visual embedding.
        Returns tuple: (visual_vector, keyframe_url)
        """
        global CLIP_MODEL
        _ensure_keyframes_dir()

        if CLIP_MODEL is None and HAS_CLIP_MODEL:
            preload_models()

        if not HAS_OPENCV or not os.path.exists(media_path):
            return None, None

        try:
            cap = cv2.VideoCapture(media_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_number = int(timestamp_sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return None, None

            # Save keyframe image JPEG for UI thumbnail display
            keyframe_filename = f"{chunk_id}.jpg"
            keyframe_path = os.path.join(KEYFRAMES_DIR, keyframe_filename)
            cv2.imwrite(keyframe_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            keyframe_url = f"http://localhost:8000/api/keyframe/{chunk_id}"

            # Compute CLIP visual embedding if model is available
            visual_vec = None
            if CLIP_MODEL is not None:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                visual_vec = CLIP_MODEL.encode(pil_img, convert_to_numpy=True, normalize_embeddings=True)

            return visual_vec, keyframe_url
        except Exception as e:
            print(f"[MultimodalEngine] Keyframe extraction failed at {timestamp_sec}s: {e}")
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
