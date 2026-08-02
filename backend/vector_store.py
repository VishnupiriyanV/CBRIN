import time
import math
import re
from typing import List, Dict, Any
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

class VectorStore:
    def __init__(self):
        self.chunks: List[Dict[str, Any]] = []
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words='english')
        self.is_fitted = False
        self.tfidf_matrix = None

    def chunk_transcript(self, transcript_segments: List[Dict[str, Any]], video_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Groups transcript segments into ~45-second sliding windows with ~10-second overlap.
        Preserves segment start/end timestamps.
        """
        chunks = []
        window_duration = 45.0  # seconds
        overlap_duration = 10.0 # seconds

        if not transcript_segments:
            return chunks

        total_duration = transcript_segments[-1].get('start', 0) + transcript_segments[-1].get('duration', 0)
        current_start = 0.0

        chunk_idx = 1
        while current_start < total_duration:
            current_end = current_start + window_duration
            
            # Gather all segments falling within [current_start, current_end]
            matching_segments = [
                s for s in transcript_segments
                if s.get('start', 0) >= current_start and s.get('start', 0) < current_end
            ]

            if matching_segments:
                combined_text = " ".join([s.get('text', '') for s in matching_segments]).strip()
                start_sec = math.floor(matching_segments[0].get('start', 0))
                end_sec = math.ceil(matching_segments[-1].get('start', 0) + matching_segments[-1].get('duration', 0))

                start_min = f"{start_sec // 60:02d}:{start_sec % 60:02d}"
                end_min = f"{end_sec // 60:02d}:{end_sec % 60:02d}"

                if len(combined_text) > 20:
                    chunk_obj = {
                        "id": f"chunk-{video_meta['id']}-{chunk_idx}",
                        "video_id": video_meta['id'],
                        "video_title": video_meta['title'],
                        "channel": video_meta['channel'],
                        "youtube_id": video_meta.get('youtube_id'),
                        "start_sec": start_sec,
                        "end_sec": end_sec,
                        "start_timestamp": start_min,
                        "end_timestamp": end_min,
                        "text": combined_text,
                        "matched_concepts": self._extract_key_phrases(combined_text),
                        "thumbnail_url": video_meta.get('thumbnail_url', '')
                    }
                    chunks.append(chunk_obj)
                    chunk_idx += 1

            current_start += (window_duration - overlap_duration)

        return chunks

    def _extract_key_phrases(self, text: str) -> List[str]:
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        stopwords = {'that', 'this', 'with', 'from', 'have', 'your', 'about', 'they', 'what', 'when', 'like', 'just', 'more', 'some'}
        filtered = [w for w in words if w not in stopwords]
        return list(dict.fromkeys(filtered))[:4]

    def add_chunks(self, new_chunks: List[Dict[str, Any]]):
        self.chunks.extend(new_chunks)
        self.reindex()

    def reindex(self):
        if not self.chunks:
            return
        corpus = [c['text'] for c in self.chunks]
        self.tfidf_matrix = self.vectorizer.fit_transform(corpus)
        self.is_fitted = True

    def search(self, query: str, top_k: int = 5, relevance_threshold: float = 0.15) -> Dict[str, Any]:
        start_time = time.time()
        
        if not self.chunks or not self.is_fitted or not query.strip():
            return {
                "query": query,
                "results": [],
                "execution_time_ms": 0,
                "total_chunks_scanned": len(self.chunks),
                "library_video_count": len(set(c['video_id'] for c in self.chunks))
            }

        query_vec = self.vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix)[0]

        scored_indices = []
        for idx, score in enumerate(similarities):
            if score >= relevance_threshold:
                scored_indices.append((idx, float(score)))

        # Sort by similarity score descending
        scored_indices.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in scored_indices[:top_k]:
            item = dict(self.chunks[idx])
            item['score'] = round(score, 3)
            results.append(item)

        exec_time_ms = round((time.time() - start_time) * 1000, 2)
        unique_videos = len(set(c['video_id'] for c in self.chunks))

        return {
            "query": query,
            "results": results,
            "execution_time_ms": exec_time_ms,
            "total_chunks_scanned": len(self.chunks),
            "library_video_count": unique_videos
        }
