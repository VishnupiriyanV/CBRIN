import time
import math
import re
import os
import json
import csv
import io
import zipfile
import datetime
from typing import List, Dict, Any, Optional
import numpy as np

from multimodal_engine import MultimodalEngine

try:
    from sentence_transformers import SentenceTransformer, CrossEncoder
    EMBEDDING_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    HAS_DENSE_MODEL = True
    print("[Vault] Loaded SentenceTransformer ('all-MiniLM-L6-v2') for semantic text embeddings.")
except Exception as e:
    HAS_DENSE_MODEL = False
    print(f"[Vault] SentenceTransformer unavailable ({e}), falling back to TF-IDF.")
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

CROSS_ENCODER_MODEL = None
HAS_CROSS_ENCODER = True

def get_cross_encoder():
    global CROSS_ENCODER_MODEL, HAS_CROSS_ENCODER
    if CROSS_ENCODER_MODEL is None and HAS_CROSS_ENCODER:
        try:
            print("[Vault] Loading CrossEncoder reranker ('cross-encoder/ms-marco-MiniLM-L-6-v2')...")
            CROSS_ENCODER_MODEL = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            print("[Vault] CrossEncoder reranker loaded.")
        except Exception as e:
            print(f"[Vault] CrossEncoder failed to load: {e}")
            HAS_CROSS_ENCODER = False
    return CROSS_ENCODER_MODEL

# Persistence paths
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
CHUNKS_FILE = os.path.join(DATA_DIR, "chunks.json")
EMBEDDINGS_FILE = os.path.join(DATA_DIR, "embeddings.npy")
VISUAL_EMBEDDINGS_FILE = os.path.join(DATA_DIR, "visual_embeddings.npy")
VIDEOS_FILE = os.path.join(DATA_DIR, "videos.json")
HIGHLIGHTS_FILE = os.path.join(DATA_DIR, "highlights.json")


class VectorStore:
    def __init__(self):
        self.chunks: List[Dict[str, Any]] = []
        self.videos: Dict[str, Dict[str, Any]] = {}  # video_id -> metadata
        self.highlights: Dict[str, Dict[str, Any]] = {}  # chunk_id -> highlight data
        self.is_fitted = False
        self.dense_embeddings: Optional[np.ndarray] = None
        self.visual_embeddings: Optional[np.ndarray] = None

        if not HAS_DENSE_MODEL:
            self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words='english')
            self.tfidf_matrix = None

        self._ensure_dirs()
        self._load_from_disk()

    def _ensure_dirs(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(MEDIA_DIR, exist_ok=True)

    def _save_to_disk(self):
        """Persist chunks, video metadata, highlights, and dual embeddings to disk."""
        self._ensure_dirs()

        with open(CHUNKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.chunks, f, indent=2, ensure_ascii=False)

        with open(VIDEOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.videos, f, indent=2, ensure_ascii=False)

        with open(HIGHLIGHTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.highlights, f, indent=2, ensure_ascii=False)

        if self.dense_embeddings is not None:
            np.save(EMBEDDINGS_FILE, self.dense_embeddings)

        if self.visual_embeddings is not None:
            np.save(VISUAL_EMBEDDINGS_FILE, self.visual_embeddings)

        print(f"[Vault] Persisted {len(self.chunks)} chunks, {len(self.videos)} videos, {len(self.highlights)} highlights to disk.")

    def _load_from_disk(self):
        """Load previously persisted library data on startup."""
        if not os.path.exists(CHUNKS_FILE):
            print("[Vault] No persisted library found. Starting fresh.")
            self.is_fitted = True
            return

        try:
            with open(CHUNKS_FILE, 'r', encoding='utf-8') as f:
                self.chunks = json.load(f)

            if os.path.exists(VIDEOS_FILE):
                with open(VIDEOS_FILE, 'r', encoding='utf-8') as f:
                    self.videos = json.load(f)

            if os.path.exists(HIGHLIGHTS_FILE):
                with open(HIGHLIGHTS_FILE, 'r', encoding='utf-8') as f:
                    self.highlights = json.load(f)

            if HAS_DENSE_MODEL and os.path.exists(EMBEDDINGS_FILE):
                self.dense_embeddings = np.load(EMBEDDINGS_FILE)
                if len(self.dense_embeddings) == len(self.chunks):
                    self.is_fitted = True
                    print(f"[Vault] Restored {len(self.chunks)} chunks with dense embeddings.")
                else:
                    self.reindex()
            elif self.chunks:
                self.reindex()
            else:
                self.is_fitted = True

            if os.path.exists(VISUAL_EMBEDDINGS_FILE):
                self.visual_embeddings = np.load(VISUAL_EMBEDDINGS_FILE)

            # Auto-generate visual embeddings if missing or unpopulated
            missing_vis = sum(1 for c in self.chunks if not c.get('has_visual_embedding', False))
            if self.chunks and (self.visual_embeddings is None or missing_vis > 0):
                self.reindex_visual_embeddings()

        except Exception as e:
            print(f"[Vault] Error loading persisted library: {e}. Starting fresh.")
            self.chunks = []
            self.videos = {}
            self.highlights = {}
            self.is_fitted = True

    def reindex_visual_embeddings(self):
        """
        Generate CLIP visual embeddings for all stored chunks (YouTube thumbnails or local video keyframes).
        """
        if not self.chunks:
            return

        print(f"[Vault] Generating CLIP visual embeddings for {len(self.chunks)} chunks...")
        visual_vectors = []
        updated_chunks = False

        for chunk in self.chunks:
            chunk_id = chunk['id']
            start_sec = chunk.get('start_sec', 0)
            video_id = chunk.get('video_id', '')

            local_path = None
            for ext in ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.mp3', '.wav', '.m4a']:
                fpath = os.path.join(MEDIA_DIR, f"{video_id}{ext}")
                if os.path.exists(fpath):
                    local_path = fpath
                    break

            thumb_url = chunk.get('thumbnail_url') or (
                f"https://img.youtube.com/vi/{chunk.get('youtube_id')}/hqdefault.jpg" if chunk.get('youtube_id') else None
            )

            vis_vec, keyframe_url = MultimodalEngine.extract_keyframe_and_embed(
                source_target=local_path,
                timestamp_sec=start_sec,
                chunk_id=chunk_id,
                image_url=thumb_url
            )

            if vis_vec is not None:
                chunk["has_visual_embedding"] = True
                visual_vectors.append(vis_vec)
                if keyframe_url:
                    chunk["keyframe_url"] = keyframe_url
                updated_chunks = True
            else:
                visual_vectors.append(None)

        if any(v is not None for v in visual_vectors):
            dim = next(v.shape[0] for v in visual_vectors if v is not None)
            self.visual_embeddings = np.array([
                v if v is not None else np.zeros(dim)
                for v in visual_vectors
            ])
            print(f"[Vault] Successfully indexed CLIP visual embeddings for {sum(1 for v in visual_vectors if v is not None)}/{len(self.chunks)} chunks.")

        if updated_chunks:
            self._save_to_disk()

    def chunk_transcript(self, transcript_segments: List[Dict[str, Any]], video_meta: Dict[str, Any], media_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Sentence-level small-to-big chunking.
        1. Segment transcript into punctuated sentence units.
        2. Embed each sentence unit for high-precision semantic matching.
        3. Extract keyframe thumbnail & CLIP visual embedding.
        """
        chunks = []
        visual_vectors = []
        now_iso = datetime.datetime.now().isoformat()

        if not transcript_segments:
            return chunks

        sentences = MultimodalEngine.segment_transcript_into_sentences(transcript_segments)

        # Fallback to sliding windows if sentence segmentation yields nothing
        if not sentences:
            total_duration = transcript_segments[-1].get('start', 0) + transcript_segments[-1].get('duration', 0)
            current_start = 0.0
            chunk_idx = 1
            window_duration = 45.0
            overlap_duration = 10.0

            while current_start < total_duration:
                current_end = current_start + window_duration
                matching = [s for s in transcript_segments if s.get('start', 0) >= current_start and s.get('start', 0) < current_end]
                if matching:
                    text = " ".join([s.get('text', '') for s in matching]).strip()
                    s_sec = math.floor(matching[0].get('start', 0))
                    e_sec = math.ceil(matching[-1].get('start', 0) + matching[-1].get('duration', 0))
                    if len(text.split()) >= 4:
                        sentences.append({"sentence_idx": chunk_idx - 1, "text": text, "start_sec": s_sec, "end_sec": e_sec})
                        chunk_idx += 1
                current_start += (window_duration - overlap_duration)

        local_target = media_path if (media_path and os.path.exists(media_path)) else None
        thumb_url = video_meta.get('thumbnail_url') or (
            f"https://img.youtube.com/vi/{video_meta.get('youtube_id')}/hqdefault.jpg" if video_meta.get('youtube_id') else None
        )

        for s_idx, sent in enumerate(sentences):
            chunk_id = f"chunk-{video_meta['id']}-{s_idx + 1}"
            sent_text = sent['text']
            start_sec = sent['start_sec']
            end_sec = sent['end_sec']

            start_timestamp = self._format_timestamp(start_sec)
            end_timestamp = self._format_timestamp(end_sec)

            context = MultimodalEngine.extract_context(sent_text)
            enriched_text = MultimodalEngine.generate_enriched_text(sent_text, context)

            vis_vec, keyframe_url = MultimodalEngine.extract_keyframe_and_embed(
                source_target=local_target,
                timestamp_sec=start_sec,
                chunk_id=chunk_id,
                image_url=thumb_url
            )

            chunk_obj = {
                "id": chunk_id,
                "video_id": video_meta['id'],
                "video_title": video_meta.get('title', 'Untitled'),
                "channel": video_meta.get('channel', 'Creator Library'),
                "youtube_id": video_meta.get('youtube_id'),
                "is_local": video_meta.get('is_local', False),
                "sentence_idx": s_idx,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "text": sent_text,
                "enriched_text": enriched_text,
                "section_topic": context['section_topic'],
                "questions_answered": context['questions_answered'],
                "implicit_concepts": context['implicit_concepts'],
                "matched_concepts": context['implicit_concepts'],
                "thumbnail_url": video_meta.get('thumbnail_url', ''),
                "has_visual_embedding": vis_vec is not None,
                "keyframe_url": keyframe_url,
                "indexed_at": now_iso,
            }

            chunks.append(chunk_obj)
            visual_vectors.append(vis_vec)

        if any(v is not None for v in visual_vectors):
            dim = next(v.shape[0] for v in visual_vectors if v is not None)
            new_vis = np.array([
                v if v is not None else np.zeros(dim)
                for v in visual_vectors
            ])
            if self.visual_embeddings is not None and len(self.visual_embeddings) > 0:
                self.visual_embeddings = np.vstack([self.visual_embeddings, new_vis])
            else:
                self.visual_embeddings = new_vis

        return chunks

    def _format_timestamp(self, seconds: int) -> str:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def add_video(self, video_meta: Dict[str, Any]):
        """Store or update video metadata with status."""
        vid_id = video_meta.get('id', '')
        video_meta['status'] = video_meta.get('status', 'fully_indexed')
        video_meta['error_message'] = video_meta.get('error_message', None)
        self.videos[vid_id] = video_meta

    def add_failed_video(self, video_id: str, title: str, channel: str, error_msg: str, is_local: bool = False, youtube_id: Optional[str] = None):
        """Record a failed ingestion so user can see it in UI with Retry options."""
        self.videos[video_id] = {
            "id": video_id,
            "youtube_id": youtube_id,
            "is_local": is_local,
            "title": title,
            "channel": channel,
            "duration_formatted": "00:00",
            "total_seconds": 0,
            "thumbnail_url": f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg" if youtube_id else "",
            "chunk_count": 0,
            "uploaded_at": datetime.datetime.now().isoformat(),
            "category": "Failed Ingestion",
            "status": "failed",
            "error_message": error_msg
        }
        self._save_to_disk()

    def delete_video(self, video_id: str) -> bool:
        """Delete video, remove associated chunks and media file, then re-index."""
        if video_id in self.videos:
            del self.videos[video_id]

        # Filter out chunks for this video
        self.chunks = [c for c in self.chunks if c.get('video_id') != video_id]

        # Remove associated highlights
        chunk_ids_to_remove = [cid for cid, h in self.highlights.items() if h.get('video_id') == video_id]
        for cid in chunk_ids_to_remove:
            del self.highlights[cid]

        # Delete local media file if present
        for ext in ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.mp3', '.wav', '.m4a']:
            fpath = os.path.join(MEDIA_DIR, f"{video_id}{ext}")
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    print(f"[Vault] Error deleting media file {fpath}: {e}")

        self.reindex()
        self._save_to_disk()
        return True

    def add_chunks(self, new_chunks: List[Dict[str, Any]]):
        """Add new chunks, re-index embeddings, and persist."""
        self.chunks.extend(new_chunks)
        self.reindex()
        self._save_to_disk()

    def reindex(self):
        """Re-compute dense embeddings for all stored chunks."""
        if not self.chunks:
            self.dense_embeddings = None
            self.is_fitted = True
            return

        corpus = [c.get('enriched_text', c['text']) for c in self.chunks]

        if HAS_DENSE_MODEL:
            embeddings = EMBEDDING_MODEL.encode(
                corpus,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False
            )
            self.dense_embeddings = embeddings
        else:
            if corpus:
                self.tfidf_matrix = self.vectorizer.fit_transform(corpus)

        self.is_fitted = True
        print(f"[Vault] Indexed {len(self.chunks)} chunks.")

    def search(self, query: str, top_k: int = 5, relevance_threshold: float = 0.1, search_mode: str = "hybrid") -> Dict[str, Any]:
        """
        Small-to-Big Retrieval Pipeline:
        1. Dense retrieval over sentence-level chunks (top 20).
        2. Window expansion (±1 surrounding sentence).
        3. Merge overlapping / adjacent windows from same video.
        4. Cross-Encoder reranking to pick top 5.
        """
        start_time = time.time()

        if not self.chunks or not self.is_fitted or not query.strip():
            return {
                "query": query,
                "results": [],
                "execution_time_ms": 0,
                "total_chunks_scanned": len(self.chunks),
                "library_video_count": len(self.videos),
                "search_mode": search_mode
            }

        search_query = query

        # Step 1: Compute Dense Similarities over Sentence Chunks
        if search_mode == "visual_scenes":
            clip_vec = MultimodalEngine.embed_text_clip(query)
            if clip_vec is not None and self.visual_embeddings is not None and len(self.visual_embeddings) == len(self.chunks):
                similarities = np.dot(self.visual_embeddings, clip_vec)
            elif HAS_DENSE_MODEL and self.dense_embeddings is not None:
                query_vec = EMBEDDING_MODEL.encode([search_query], convert_to_numpy=True, normalize_embeddings=True)[0]
                similarities = np.dot(self.dense_embeddings, query_vec)
            else:
                query_vec = self.vectorizer.transform([search_query])
                similarities = cosine_similarity(query_vec, self.tfidf_matrix)[0]
        else:
            if HAS_DENSE_MODEL and self.dense_embeddings is not None:
                query_vec = EMBEDDING_MODEL.encode([search_query], convert_to_numpy=True, normalize_embeddings=True)[0]
                similarities = np.dot(self.dense_embeddings, query_vec)
            elif hasattr(self, 'vectorizer') and self.tfidf_matrix is not None:
                query_vec = self.vectorizer.transform([search_query])
                similarities = cosine_similarity(query_vec, self.tfidf_matrix)[0]
            else:
                similarities = np.zeros(len(self.chunks))

        # Filter top 20 candidate sentence matches
        scored_indices = []
        for idx, score in enumerate(similarities):
            val = float(score)
            if val >= relevance_threshold:
                scored_indices.append((idx, val))

        scored_indices.sort(key=lambda x: x[1], reverse=True)
        top_sentence_matches = scored_indices[:20]

        if not top_sentence_matches:
            return {
                "query": query,
                "results": [],
                "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                "total_chunks_scanned": len(self.chunks),
                "library_video_count": len(self.videos),
                "search_mode": search_mode
            }

        # Step 2: Window Expansion (±1 sentence) & Candidate Construction
        # Group chunks by video_id for fast sentence lookup
        video_chunks_map: Dict[str, List[Dict[str, Any]]] = {}
        for c in self.chunks:
            vid = c.get('video_id', '')
            if vid not in video_chunks_map:
                video_chunks_map[vid] = []
            video_chunks_map[vid].append(c)

        for vid in video_chunks_map:
            video_chunks_map[vid].sort(key=lambda x: x.get('sentence_idx', 0))

        expanded_candidates = []

        for idx, dense_score in top_sentence_matches:
            target_chunk = self.chunks[idx]
            vid_id = target_chunk.get('video_id', '')
            s_idx = target_chunk.get('sentence_idx', 0)
            vid_sentences = video_chunks_map.get(vid_id, [])

            # Expand window to ±1 sentence
            matched_pos = next((i for i, sc in enumerate(vid_sentences) if sc['id'] == target_chunk['id']), 0)
            start_pos = max(0, matched_pos - 1)
            end_pos = min(len(vid_sentences) - 1, matched_pos + 1)

            window_sentences = vid_sentences[start_pos:end_pos + 1]

            combined_text = " ".join([s['text'] for s in window_sentences]).strip()
            min_start_sec = window_sentences[0]['start_sec']
            max_end_sec = window_sentences[-1]['end_sec']

            candidate_item = {
                "id": target_chunk['id'],
                "video_id": vid_id,
                "video_title": target_chunk.get('video_title', ''),
                "channel": target_chunk.get('channel', ''),
                "youtube_id": target_chunk.get('youtube_id'),
                "is_local": target_chunk.get('is_local', False),
                "start_sec": min_start_sec,
                "end_sec": max_end_sec,
                "start_timestamp": self._format_timestamp(min_start_sec),
                "end_timestamp": self._format_timestamp(max_end_sec),
                "text": combined_text,
                "matched_sentence": target_chunk['text'],
                "score": dense_score,
                "dense_score": dense_score,
                "matched_concepts": target_chunk.get('implicit_concepts', []),
                "thumbnail_url": target_chunk.get('thumbnail_url', ''),
                "keyframe_url": target_chunk.get('keyframe_url'),
                "section_topic": target_chunk.get('section_topic', ''),
                "questions_answered": target_chunk.get('questions_answered', []),
                "implicit_concepts": target_chunk.get('implicit_concepts', []),
                "has_visual_embedding": target_chunk.get('has_visual_embedding', False),
                "is_highlighted": target_chunk['id'] in self.highlights,
                "sentence_range": (window_sentences[0].get('sentence_idx', 0), window_sentences[-1].get('sentence_idx', 0)),
            }
            expanded_candidates.append(candidate_item)

        # Step 3: Merge Overlapping or Adjacent Windows from the Same Video
        merged_candidates = []
        expanded_candidates.sort(key=lambda x: (x['video_id'], x['sentence_range'][0]))

        for candidate in expanded_candidates:
            if not merged_candidates:
                merged_candidates.append(candidate)
                continue

            last = merged_candidates[-1]
            # Check if same video and overlapping/adjacent sentence ranges
            if last['video_id'] == candidate['video_id']:
                last_start_s, last_end_s = last['sentence_range']
                cand_start_s, cand_end_s = candidate['sentence_range']

                if cand_start_s <= last_end_s + 1:
                    # Merge overlapping windows
                    new_start_s = min(last_start_s, cand_start_s)
                    new_end_s = max(last_end_s, cand_end_s)

                    # Reconstruct merged text without duplicate sentences
                    vid_sents = video_chunks_map.get(last['video_id'], [])
                    merged_sents = [s for s in vid_sents if new_start_s <= s.get('sentence_idx', 0) <= new_end_s]
                    merged_text = " ".join([s['text'] for s in merged_sents]).strip()

                    last['sentence_range'] = (new_start_s, new_end_s)
                    last['start_sec'] = merged_sents[0]['start_sec']
                    last['end_sec'] = merged_sents[-1]['end_sec']
                    last['start_timestamp'] = self._format_timestamp(last['start_sec'])
                    last['end_timestamp'] = self._format_timestamp(last['end_sec'])
                    last['text'] = merged_text
                    last['dense_score'] = max(last['dense_score'], candidate['dense_score'])
                    last['score'] = last['dense_score']
                    continue

            merged_candidates.append(candidate)

        # Step 4: Cross-Encoder Reranking Stage
        results = []

        reranker = get_cross_encoder()
        if reranker is not None and merged_candidates:
            try:
                pairs = [(query, cand['text']) for cand in merged_candidates]
                rerank_scores = reranker.predict(pairs)

                for idx, cand in enumerate(merged_candidates):
                    raw_rerank = float(rerank_scores[idx])
                    normalized_score = round(1.0 / (1.0 + math.exp(-raw_rerank)), 4)
                    cand['score'] = normalized_score
                    cand['rerank_score'] = raw_rerank

                merged_candidates.sort(key=lambda x: x['score'], reverse=True)
            except Exception as e:
                print(f"[Vault] CrossEncoder prediction error: {e}")
                merged_candidates.sort(key=lambda x: x['score'], reverse=True)
        else:
            merged_candidates.sort(key=lambda x: x['score'], reverse=True)

        for item in merged_candidates[:top_k]:
            topic = item.get('section_topic', 'spoken content')
            concepts = item.get('implicit_concepts', [])
            matched_sentence = item.get('matched_sentence', '')

            if search_mode == 'visual_scenes':
                match_reason = f"Matched visual scene frame for '{topic}'"
            elif concepts and len(concepts) >= 2:
                match_reason = f"Matched: {concepts[0]} & {concepts[1]}"
            elif concepts:
                match_reason = f"Matched: {concepts[0]}"
            else:
                match_reason = f"Matched topic: {topic}"

            item['match_reason'] = match_reason
            results.append(item)

        exec_time_ms = round((time.time() - start_time) * 1000, 2)

        return {
            "query": query,
            "results": results,
            "execution_time_ms": exec_time_ms,
            "total_chunks_scanned": len(self.chunks),
            "library_video_count": len(self.videos),
            "search_mode": search_mode
        }

    def get_suggested_queries(self) -> List[str]:
        """
        Dynamically generate suggested queries from real indexed topics.
        Strictly deduplicated (case-insensitive) and varied across 6 natural template formats.
        """
        suggestions = []
        seen_lower = set()

        templates = [
            lambda c1, c2, top: f"How do {c1} and {c2} compare?",
            lambda c1, c2, top: f"Tell me about {top.lower() if top else c1}",
            lambda c1, c2, top: f"Why is {c1} important?",
            lambda c1, c2, top: f"What did the speaker explain about {c1}?",
            lambda c1, c2, top: f"Key insights on {c1} and {c2}",
            lambda c1, c2, top: f"When were {c1} and {c2} discussed?",
        ]
        template_idx = 0

        # Collect concepts and topics from chunks
        for chunk in self.chunks:
            concepts = chunk.get('implicit_concepts', [])
            topic = chunk.get('section_topic', '')

            c1 = concepts[0] if len(concepts) > 0 else 'content'
            c2 = concepts[1] if len(concepts) > 1 else 'topics'

            # Try generating from template
            generator = templates[template_idx % len(templates)]
            candidate = generator(c1, c2, topic).strip()
            norm = candidate.lower()

            if norm not in seen_lower and len(candidate) > 15:
                seen_lower.add(norm)
                suggestions.append(candidate)
                template_idx += 1
                if len(suggestions) >= 4:
                    return suggestions

        # Fallback if too few chunks: generate generic concept suggestions
        for chunk in self.chunks:
            for concept in chunk.get('implicit_concepts', []):
                phrase = f"What is discussed regarding {concept}?"
                norm = phrase.lower()
                if norm not in seen_lower:
                    seen_lower.add(norm)
                    suggestions.append(phrase)
                    if len(suggestions) >= 4:
                        return suggestions

        return suggestions

    # --- Highlights / Bookmark API ---

    def add_highlight(self, chunk_id: str, note: str = "") -> Dict[str, Any]:
        """Bookmark a chunk result with an optional note."""
        # Find the chunk
        chunk = next((c for c in self.chunks if c['id'] == chunk_id), None)
        if not chunk:
            return {"success": False, "message": f"Chunk '{chunk_id}' not found."}

        highlight = {
            "chunk_id": chunk_id,
            "video_id": chunk.get('video_id', ''),
            "video_title": chunk.get('video_title', ''),
            "channel": chunk.get('channel', ''),
            "text": chunk.get('text', ''),
            "start_sec": chunk.get('start_sec', 0),
            "end_sec": chunk.get('end_sec', 0),
            "start_timestamp": chunk.get('start_timestamp', ''),
            "end_timestamp": chunk.get('end_timestamp', ''),
            "thumbnail_url": chunk.get('thumbnail_url', ''),
            "keyframe_url": chunk.get('keyframe_url'),
            "youtube_id": chunk.get('youtube_id'),
            "is_local": chunk.get('is_local', False),
            "section_topic": chunk.get('section_topic', ''),
            "note": note,
            "highlighted_at": datetime.datetime.now().isoformat(),
        }

        self.highlights[chunk_id] = highlight
        self._save_to_disk()
        return {"success": True, "message": f"Highlighted moment at {chunk.get('start_timestamp', '')}.", "highlight": highlight}

    def remove_highlight(self, chunk_id: str) -> Dict[str, Any]:
        """Remove a bookmarked highlight."""
        if chunk_id not in self.highlights:
            return {"success": False, "message": f"Highlight '{chunk_id}' not found."}

        del self.highlights[chunk_id]
        self._save_to_disk()
        return {"success": True, "message": "Highlight removed."}

    def get_highlights(self) -> List[Dict[str, Any]]:
        """Return all highlighted moments sorted by highlight time (newest first)."""
        items = list(self.highlights.values())
        items.sort(key=lambda x: x.get('highlighted_at', ''), reverse=True)
        return items

    # --- Export API ---

    def export_library_json(self) -> Dict[str, Any]:
        """Export the full library as a JSON-serializable dict."""
        return {
            "vault_export_version": "1.0",
            "exported_at": datetime.datetime.now().isoformat(),
            "stats": self.get_stats(),
            "videos": self.videos,
            "chunks": self.chunks,
            "highlights": self.highlights,
        }

    def export_library_zip(self) -> bytes:
        """Export the full library as a ZIP archive containing videos.json, chunks.json, highlights.json."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("videos.json", json.dumps(self.videos, indent=2, ensure_ascii=False))
            zf.writestr("chunks.json", json.dumps(self.chunks, indent=2, ensure_ascii=False))
            zf.writestr("highlights.json", json.dumps(self.highlights, indent=2, ensure_ascii=False))
            meta = {
                "vault_export_version": "1.0",
                "exported_at": datetime.datetime.now().isoformat(),
                "stats": self.get_stats(),
            }
            zf.writestr("metadata.json", json.dumps(meta, indent=2, ensure_ascii=False))
        return buffer.getvalue()

    def export_search_results_csv(self, results: List[Dict[str, Any]], query: str) -> str:
        """Export search results as a CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["query", "video_title", "channel", "start_timestamp", "end_timestamp", "score", "section_topic", "text"])
        for r in results:
            writer.writerow([
                query,
                r.get('video_title', ''),
                r.get('channel', ''),
                r.get('start_timestamp', ''),
                r.get('end_timestamp', ''),
                r.get('score', 0),
                r.get('section_topic', ''),
                r.get('text', ''),
            ])
        return output.getvalue()

    def import_library(self, data: Dict[str, Any], mode: str = "merge") -> Dict[str, Any]:
        """
        Import a previously exported library.
        mode: 'merge' — skip duplicate video IDs, add new ones.
        mode: 'replace' — wipe current library and replace entirely.
        """
        imported_videos = data.get('videos', {})
        imported_chunks = data.get('chunks', [])
        imported_highlights = data.get('highlights', {})

        if mode == "replace":
            self.videos = imported_videos
            self.chunks = imported_chunks
            self.highlights = imported_highlights
            self.reindex()
            self._save_to_disk()
            return {
                "success": True,
                "message": f"Replaced library with {len(imported_videos)} videos, {len(imported_chunks)} chunks.",
                "videos_imported": len(imported_videos),
                "chunks_imported": len(imported_chunks),
            }
        else:
            # Merge mode: skip existing video IDs
            existing_video_ids = set(self.videos.keys())
            new_videos = 0
            new_chunks = 0

            for vid_id, vid_meta in imported_videos.items():
                if vid_id not in existing_video_ids:
                    self.videos[vid_id] = vid_meta
                    new_videos += 1

            existing_chunk_ids = {c['id'] for c in self.chunks}
            for chunk in imported_chunks:
                if chunk['id'] not in existing_chunk_ids:
                    self.chunks.append(chunk)
                    new_chunks += 1

            # Merge highlights (don't overwrite existing)
            for cid, highlight in imported_highlights.items():
                if cid not in self.highlights:
                    self.highlights[cid] = highlight

            if new_chunks > 0:
                self.reindex()
            self._save_to_disk()

            return {
                "success": True,
                "message": f"Merged {new_videos} new videos, {new_chunks} new chunks. Skipped {len(imported_videos) - new_videos} duplicates.",
                "videos_imported": new_videos,
                "chunks_imported": new_chunks,
            }

    def get_stats(self) -> Dict[str, Any]:
        """Return comprehensive library stats including status counts and visual coverage."""
        total_seconds = sum(v.get('total_seconds', 0) for v in self.videos.values() if v.get('status') == 'fully_indexed')
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        indexed_count = sum(1 for v in self.videos.values() if v.get('status') == 'fully_indexed')
        failed_count = sum(1 for v in self.videos.values() if v.get('status') == 'failed')
        indexing_count = sum(1 for v in self.videos.values() if v.get('status') == 'indexing')
        is_fully_indexed = (len(self.videos) > 0 and failed_count == 0 and indexing_count == 0)

        visual_indexed_count = sum(1 for c in self.chunks if c.get('has_visual_embedding', False))

        return {
            "total_videos": len(self.videos),
            "indexed_count": indexed_count,
            "failed_count": failed_count,
            "indexing_count": indexing_count,
            "is_fully_indexed": is_fully_indexed,
            "total_chunks": len(self.chunks),
            "visual_indexed_count": visual_indexed_count,
            "total_highlights": len(self.highlights),
            "total_hours": f"{hours}h {minutes}m",
            "embedding_model": "all-MiniLM-L6-v2 + CLIP" if HAS_DENSE_MODEL else "TF-IDF",
            "is_fitted": self.is_fitted
        }
