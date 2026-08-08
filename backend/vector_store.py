import time
import math
import re
import os
import json
import datetime
from typing import List, Dict, Any, Optional
import numpy as np

import paths
import atomic_io
from multimodal_engine import MultimodalEngine

try:
    from sentence_transformers import SentenceTransformer, CrossEncoder
    EMBEDDING_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    HAS_DENSE_MODEL = True
    print("[Cbrin] Loaded SentenceTransformer ('all-MiniLM-L6-v2') for semantic text embeddings.")
except Exception as e:
    HAS_DENSE_MODEL = False
    print(f"[Cbrin] SentenceTransformer unavailable ({e}), falling back to TF-IDF.")
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False
    print("[Cbrin] 'rank_bm25' not installed — hybrid retrieval falls back to dense-only. "
          "Install it (see backend/requirements.txt) for lexical matching on proper nouns, "
          "product names, and acronyms that dense embeddings miss (IMPROVEMENT-PLAN.md 2.5).")

CROSS_ENCODER_MODEL = None
HAS_CROSS_ENCODER = True

# Reranker gating threshold (IMPROVEMENT-PLAN.md 2.2): sigmoid(ms-marco cross-encoder logit).
# The retriever's own cosine/BM25/RRF scores are NOT comparable across queries and are used
# only to build the candidate pool (top ~30) — this is the one number that actually decides
# whether a result is shown at all, which is what makes the empty state reachable (3.2).
#
# Calibrated against backend/eval/queries.yaml (not by eye — see backend/eval/README.md):
# ms-marco-MiniLM-L-6-v2's sigmoid(logit) runs much lower on short spoken-transcript
# sentences than on the passage-ranking data it was trained on. Measured negative-query
# (genuinely unrelated topics) top scores cluster at ~0.000-0.001; measured true-positive
# top scores on this library run ~0.05-0.4+. 0.5 (the original guess) was clearing almost
# nothing — Recall@5 was 21%. 0.08 sits comfortably above the negative cluster with margin
# to spare, well below every observed true positive. Re-run `eval/run_eval.py --verbose`
# after touching this and confirm recall goes up AND false-positive rate stays ~0% — don't
# move it on vibes.
RERANK_RELEVANCE_THRESHOLD = 0.08
RERANK_STRONG_THRESHOLD = 0.35  # "Strong" vs "Possible" confidence bucket cutoff (2.3) — also eval-derived

# CLIP cosine similarities live on a completely different scale than the MiniLM/cross-encoder
# text scores above (2.8) — calibrated separately, and not run through the text cross-encoder
# at all (see search()'s visual_scenes branch).
VISUAL_RELEVANCE_THRESHOLD = 0.20
VISUAL_STRONG_THRESHOLD = 0.28

# Cap on how large a merged "small-to-big" window can grow (seconds) — see the comment at
# its use site in search() for why this exists.
MAX_MERGED_WINDOW_SECONDS = 90


def get_cross_encoder():
    global CROSS_ENCODER_MODEL, HAS_CROSS_ENCODER
    if CROSS_ENCODER_MODEL is None and HAS_CROSS_ENCODER:
        try:
            print("[Cbrin] Loading CrossEncoder reranker ('cross-encoder/ms-marco-MiniLM-L-6-v2')...")
            CROSS_ENCODER_MODEL = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            print("[Cbrin] CrossEncoder reranker loaded.")
        except Exception as e:
            print(f"[Cbrin] CrossEncoder failed to load: {e}")
            HAS_CROSS_ENCODER = False
    return CROSS_ENCODER_MODEL

# Persistence paths live in paths.py (single seam tests redirect via paths.use_root()).
# Read them as paths.CHUNKS_FILE etc at each use site — never `from paths import X`, which
# would bind a copy that a later use_root() call can't reach.

# Bump whenever the on-disk chunk shape changes in a way search() depends on.
# v2 introduced sentence-level `sentence_idx` — chunks without it were written by the
# old sliding-window fallback and break the window-merge logic in search().
SCHEMA_VERSION = 2


class VectorStore:
    def __init__(self):
        self.chunks: List[Dict[str, Any]] = []
        self.videos: Dict[str, Dict[str, Any]] = {}  # video_id -> metadata
        self.is_fitted = False
        self.dense_embeddings: Optional[np.ndarray] = None
        self.visual_embeddings: Optional[np.ndarray] = None
        self.bm25_index = None  # BM25Okapi, rebuilt in reindex() alongside dense_embeddings
        self._suggested_queries_cache: Optional[List[str]] = None
        # Video IDs whose persisted chunks were evicted for predating SCHEMA_VERSION;
        # the caller (main.py) re-derives them from their original source and calls
        # finalize_schema_migration() when done.
        self.pending_rechunk: List[str] = []
        self.pending_rechunk_meta: Dict[str, Dict[str, Any]] = {}

        if not HAS_DENSE_MODEL:
            self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words='english')
            self.tfidf_matrix = None

        self._ensure_dirs()
        self._load_from_disk()

    def _ensure_dirs(self):
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        os.makedirs(paths.MEDIA_DIR, exist_ok=True)

    def _save_to_disk(self):
        """Persist chunks, video metadata, and dual embeddings to disk."""
        self._ensure_dirs()

        # Atomic (atomic_io): chunks.json IS the library — a truncated write loses it.
        atomic_io.write_json(paths.CHUNKS_FILE, self.chunks)
        atomic_io.write_json(paths.VIDEOS_FILE, self.videos)

        if self.dense_embeddings is not None:
            atomic_io.save_npy(paths.EMBEDDINGS_FILE, self.dense_embeddings)

        if self.visual_embeddings is not None:
            atomic_io.save_npy(paths.VISUAL_EMBEDDINGS_FILE, self.visual_embeddings)

        print(f"[Cbrin] Persisted {len(self.chunks)} chunks and {len(self.videos)} videos to disk.")

    def _load_from_disk(self):
        """Load previously persisted library data on startup."""
        self.pending_rechunk = []
        self.pending_rechunk_meta = {}

        if not os.path.exists(paths.CHUNKS_FILE):
            print("[Cbrin] No persisted library found. Starting fresh.")
            self.is_fitted = True
            return

        try:
            with open(paths.CHUNKS_FILE, 'r', encoding='utf-8') as f:
                self.chunks = json.load(f)

            if os.path.exists(paths.VIDEOS_FILE):
                with open(paths.VIDEOS_FILE, 'r', encoding='utf-8') as f:
                    self.videos = json.load(f)

            evicted = self._evict_stale_chunks()

            if HAS_DENSE_MODEL and os.path.exists(paths.EMBEDDINGS_FILE) and not evicted:
                self.dense_embeddings = np.load(paths.EMBEDDINGS_FILE)
                if len(self.dense_embeddings) == len(self.chunks):
                    self.is_fitted = True
                    print(f"[Cbrin] Restored {len(self.chunks)} chunks with dense embeddings.")
                else:
                    self.reindex()
            elif self.chunks:
                self.reindex()
            else:
                self.is_fitted = True

            if os.path.exists(paths.VISUAL_EMBEDDINGS_FILE) and not evicted:
                self.visual_embeddings = np.load(paths.VISUAL_EMBEDDINGS_FILE)

            # Auto-generate visual embeddings for chunks that don't have one yet and
            # haven't already been marked as permanently unable to get one (1.6: don't
            # retry the same dead thumbnail/audio-only chunk on every single boot).
            missing_vis = sum(
                1 for c in self.chunks
                if not c.get('has_visual_embedding', False) and c.get('visual_status') != 'failed'
            )
            visual_len_mismatch = self.visual_embeddings is None or len(self.visual_embeddings) != len(self.chunks)
            if self.chunks and (visual_len_mismatch or missing_vis > 0):
                self.reindex_visual_embeddings()

            self._warn_if_thresholds_uncalibrated()

        except Exception as e:
            print(f"[Cbrin] Error loading persisted library: {e}. Starting fresh.")
            self.chunks = []
            self.videos = {}
            self.is_fitted = True

    def _evict_stale_chunks(self) -> bool:
        """
        Evict chunks written by a pre-SCHEMA_VERSION chunker (missing `sentence_idx`).
        search()'s window-merge logic silently collapses these into garbage merged blobs
        with fabricated timestamps (see IMPROVEMENT-PLAN.md 1.1), so refuse to serve them.
        Affected video IDs are recorded on self.pending_rechunk for the caller to re-derive
        from their original source (see main.py's startup repair pass).
        Returns True if anything was evicted.
        """
        stored_schema_version = 0
        if os.path.exists(paths.INDEX_META_FILE):
            try:
                with open(paths.INDEX_META_FILE, 'r', encoding='utf-8') as f:
                    stored_schema_version = json.load(f).get('schema_version', 0)
            except Exception:
                stored_schema_version = 0

        if stored_schema_version >= SCHEMA_VERSION:
            return False

        stale_video_ids = {
            c.get('video_id') for c in self.chunks
            if c.get('sentence_idx') is None
        }
        if not stale_video_ids:
            return False

        print(f"[Vault] {len(stale_video_ids)} video(s) predate sentence-level chunking "
              f"(index schema v{stored_schema_version} < v{SCHEMA_VERSION}). Evicting their "
              f"chunks from the live index for automatic re-chunking.")

        for vid in stale_video_ids:
            self.pending_rechunk_meta[vid] = dict(self.videos.get(vid, {"id": vid}))
        self.pending_rechunk = sorted(stale_video_ids)
        self.chunks = [c for c in self.chunks if c.get('video_id') not in stale_video_ids]
        return True

    def finalize_schema_migration(self):
        """Call once pending re-chunk repairs (self.pending_rechunk) have been attempted,
        successfully or not, so the next boot doesn't re-run the eviction/repair pass."""
        self._ensure_dirs()
        with open(paths.INDEX_META_FILE, 'w', encoding='utf-8') as f:
            json.dump({"schema_version": SCHEMA_VERSION}, f, indent=2)
        self.pending_rechunk = []
        self.pending_rechunk_meta = {}

    def _warn_if_thresholds_uncalibrated(self):
        """
        RERANK_RELEVANCE_THRESHOLD/RERANK_STRONG_THRESHOLD and their VISUAL_* counterparts
        were calibrated against backend/eval/queries.yaml on a specific small library (see
        eval/README.md's history). They are not universal constants — re-run
        `python eval/run_eval.py --verbose` and adjust them whenever the library's size or
        content composition changes meaningfully, rather than trusting them by default.
        Printed once per boot, not per-request, so it doesn't spam the log.
        """
        video_count = len({c.get('video_id') for c in self.chunks if c.get('video_id')})
        if 0 < video_count < 5:
            print(f"[Vault] Library has only {video_count} video(s) indexed. "
                  f"RERANK_RELEVANCE_THRESHOLD/VISUAL_RELEVANCE_THRESHOLD in vector_store.py "
                  f"were calibrated against a small eval library and may not generalize — "
                  f"re-run `python eval/run_eval.py --verbose` before trusting search quality.")

    @staticmethod
    def find_local_media(video_id: str) -> Optional[str]:
        """
        Locate the downloaded media file for a video, if one is on disk.

        Prefers the canonical "{video_id}{ext}" name, but also accepts any
        "{video_id}.<anything>{ext}" — older ingest code could leave a merged file named
        e.g. "yt-dQw4w9WgXcQ.mp4.part.mp4" (the .part hazard described in
        media_service._download_youtube). Those files are perfectly valid video; only the
        name is odd, and an exact-name lookup silently downgraded them to thumbnail-only
        visual embeddings forever.
        """
        exts = ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.mp3', '.wav', '.m4a']

        for ext in exts:
            fpath = os.path.join(paths.MEDIA_DIR, f"{video_id}{ext}")
            if os.path.exists(fpath):
                return fpath

        try:
            for name in sorted(os.listdir(paths.MEDIA_DIR)):
                if name.startswith(f"{video_id}.") and any(name.lower().endswith(e) for e in exts):
                    return os.path.join(paths.MEDIA_DIR, name)
        except OSError:
            pass

        return None

    def reindex_visual_embeddings(self):
        """
        Generate CLIP visual embeddings for stored chunks (YouTube thumbnails or local video
        keyframes) that don't have one yet and haven't already been marked permanently
        unattainable (1.6: an audio-only file or a dead thumbnail URL would otherwise be
        re-attempted on every single boot, forever).

        Also upgrades 'video-level' chunks to real per-moment keyframes once the source
        media is on disk. This matters because visual embedding can run while a YouTube
        download is still being merged to its final filename: the chunk falls back to the
        shared poster thumbnail, gets has_visual_embedding=True, and — before this — was
        never revisited, so a transient race became a permanent downgrade. Measured on the
        dev library, that left all 116 YouTube chunks thumbnail-only while the merged .mp4
        sat in data/media/ the whole time.
        """
        if not self.chunks:
            return

        # Rebuild the full aligned array (existing successes + freshly attempted ones) so
        # visual_embeddings always stays positionally aligned with self.chunks.
        existing_by_id = {}
        if self.visual_embeddings is not None and len(self.visual_embeddings) == len(self.chunks):
            existing_by_id = {c['id']: self.visual_embeddings[i] for i, c in enumerate(self.chunks)}

        # Cache the media lookup per video so a 400-chunk library does one stat pass per
        # video rather than one per chunk.
        local_media_cache: Dict[str, Optional[str]] = {}

        def _local_media_for(video_id: str) -> Optional[str]:
            if video_id not in local_media_cache:
                local_media_cache[video_id] = self.find_local_media(video_id)
            return local_media_cache[video_id]

        def _wants_attempt(c: Dict[str, Any]) -> bool:
            if c.get('visual_status') == 'failed':
                return False
            if not c.get('has_visual_embedding', False):
                return True
            # Upgrade path: a shared video-level thumbnail can become a real per-moment
            # frame once the source media is on disk. 'visual_upgrade_failed' pins the ones
            # where we already tried that with the file present and still got a thumbnail,
            # so this can't retry on every boot forever (same reasoning as 'failed').
            return (
                c.get('visual_status') == 'video-level'
                and not c.get('visual_upgrade_failed', False)
                and _local_media_for(c.get('video_id', '')) is not None
            )

        to_attempt = [c for c in self.chunks if _wants_attempt(c)]
        if not to_attempt:
            return

        upgrades = sum(1 for c in to_attempt if c.get('has_visual_embedding', False))
        if upgrades:
            print(f"[Vault] {upgrades} chunk(s) have video-level thumbnails but local media is "
                  f"now available — re-extracting real per-moment keyframes.")

        print(f"[Vault] Generating CLIP visual embeddings for {len(to_attempt)} chunk(s)...")
        updated_chunks = False
        attempted_ok = 0

        for chunk in to_attempt:
            chunk_id = chunk['id']
            start_sec = chunk.get('start_sec', 0)
            video_id = chunk.get('video_id', '')

            local_path = _local_media_for(video_id)
            is_upgrade = chunk.get('has_visual_embedding', False)

            thumb_url = chunk.get('thumbnail_url') or (
                f"https://img.youtube.com/vi/{chunk.get('youtube_id')}/hqdefault.jpg" if chunk.get('youtube_id') else None
            )

            vis_vec, keyframe_url, source_kind = MultimodalEngine.extract_keyframe_and_embed(
                source_target=local_path,
                timestamp_sec=start_sec,
                chunk_id=chunk_id,
                image_url=thumb_url
            )

            if vis_vec is not None:
                chunk["has_visual_embedding"] = True
                # 'ok' = a real per-moment frame; 'video-level' = the same shared YouTube
                # thumbnail as every other chunk of this video, which can't localize a
                # moment (IMPROVEMENT-PLAN.md 2.10) — kept distinct so search/UI can be honest.
                chunk["visual_status"] = "ok" if source_kind == "frame" else "video-level"
                existing_by_id[chunk_id] = vis_vec
                if keyframe_url:
                    chunk["keyframe_url"] = keyframe_url
                attempted_ok += 1
                # Tried to upgrade with the media file present and still got a video-level
                # image (unreadable container, timestamp past the real duration, ...). Pin
                # it so the upgrade isn't retried on every boot.
                if is_upgrade and source_kind != 'frame':
                    chunk["visual_upgrade_failed"] = True
                elif source_kind == 'frame':
                    chunk.pop("visual_upgrade_failed", None)
            elif is_upgrade:
                # Never let a failed *upgrade* destroy a working embedding: the old vector
                # stays in existing_by_id and the chunk keeps its 'video-level' status.
                chunk["visual_upgrade_failed"] = True
            else:
                chunk["visual_status"] = "failed"

            updated_chunks = True

        if existing_by_id:
            dim = next(iter(existing_by_id.values())).shape[0]
            self.visual_embeddings = np.array([
                existing_by_id.get(c['id'], np.zeros(dim))
                for c in self.chunks
            ])
            print(f"[Vault] Visual embedding pass: {attempted_ok}/{len(to_attempt)} newly succeeded, "
                  f"{len(existing_by_id)}/{len(self.chunks)} chunks now covered.")

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

        if any(s.get('is_visual_only') for s in transcript_segments):
            sentences = [
                {
                    "sentence_idx": i,
                    "text": s.get('text', ''),
                    "start_sec": math.floor(s.get('start', 0.0)),
                    "end_sec": math.ceil(s.get('start', 0.0) + s.get('duration', 0.0))
                }
                for i, s in enumerate(transcript_segments)
            ]
        else:
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

        # Fall back to a disk lookup when the caller didn't pass a media path (or passed one
        # that isn't there yet). Without this, ingest that runs while a download is still
        # being merged embeds the shared poster thumbnail for every chunk; reindex_visual_
        # embeddings() will now repair that on the next boot, but it's cheaper to get it
        # right the first time.
        local_target = media_path if (media_path and os.path.exists(media_path)) else None
        if local_target is None:
            local_target = self.find_local_media(video_meta['id'])
        thumb_url = video_meta.get('thumbnail_url') or (
            f"https://img.youtube.com/vi/{video_meta.get('youtube_id')}/hqdefault.jpg" if video_meta.get('youtube_id') else None
        )

        # Corpus-level IDF for concept extraction (2.7): existing library + this video's
        # new sentences, so terms common across the library get demoted without also
        # suppressing a video's own genuinely-central, frequently-repeated topic.
        idf_corpus = [c.get('text', '') for c in self.chunks] + [s['text'] for s in sentences]
        idf_lookup = MultimodalEngine.compute_corpus_idf(idf_corpus)

        for s_idx, sent in enumerate(sentences):
            chunk_id = f"chunk-{video_meta['id']}-{s_idx + 1}"
            sent_text = sent['text']
            start_sec = sent['start_sec']
            end_sec = sent['end_sec']

            start_timestamp = self._format_timestamp(start_sec)
            end_timestamp = self._format_timestamp(end_sec)

            context = MultimodalEngine.extract_context(sent_text, idf_lookup)
            enriched_text = MultimodalEngine.generate_enriched_text(sent_text, context)

            vis_vec, keyframe_url, source_kind = MultimodalEngine.extract_keyframe_and_embed(
                source_target=local_target,
                timestamp_sec=start_sec,
                chunk_id=chunk_id,
                image_url=thumb_url
            )
            if vis_vec is not None:
                visual_status = "ok" if source_kind == "frame" else "video-level"
            else:
                visual_status = "failed"

            chunk_obj = {
                "id": chunk_id,
                "video_id": video_meta['id'],
                "video_title": video_meta.get('title', 'Untitled'),
                "channel": video_meta.get('channel', 'Creator Library'),
                "youtube_id": video_meta.get('youtube_id'),
                "is_local": video_meta.get('is_local', False),
                "is_visual_only": sent.get('is_visual_only', False) or sent_text.startswith('[Visual Scene'),
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
                "thumbnail_url": video_meta.get('thumbnail_url', ''),
                "has_visual_embedding": vis_vec is not None,
                "visual_status": visual_status,
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

    def _format_timestamp(self, seconds: float) -> str:
        sec_int = int(seconds)
        hours = sec_int // 3600
        minutes = (sec_int % 3600) // 60
        secs = sec_int % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def is_indexed(self, video_id: str) -> bool:
        """True if this video has EITHER a metadata record or chunks on the index.

        Both halves matter. The upload path used to dedup on self.videos alone while the
        YouTube path deduped on self.chunks, so a video whose videos.json record was missing
        but whose chunks survived would pass the upload check and append a second full set of
        chunks under identical ids. That happened on 2026-08-07: local-99ce947e13e5 gained
        270 duplicate chunks. Checking both sources makes the two ingest paths agree.
        """
        if video_id in self.videos:
            return True
        return any(c.get('video_id') == video_id for c in self.chunks)

    def add_video(self, video_meta: Dict[str, Any]):
        """Store or update video metadata with status."""
        vid_id = video_meta.get('id', '')
        video_meta['status'] = video_meta.get('status', 'fully_indexed')
        video_meta['error_message'] = video_meta.get('error_message', None)
        self.videos[vid_id] = video_meta

    def add_failed_video(self, video_id: str, title: str, channel: str, error_msg: str, is_local: bool = False, youtube_id: Optional[str] = None, source_url: Optional[str] = None):
        """Record a failed ingestion so user can see it in UI with Retry options."""
        self.videos[video_id] = {
            "id": video_id,
            "youtube_id": youtube_id,
            "source_url": source_url,
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
        """Delete video, remove associated chunks, keyframes, and media file."""
        if video_id in self.videos:
            del self.videos[video_id]

        # Chunks for this video, captured before filtering so their keyframe files can be
        # cleaned up too — previously only the source media file was deleted here, leaving
        # every chunk's keyframe JPG orphaned on disk forever (confirmed: 67 orphaned files
        # accumulated from earlier deletes before this fix).
        keep_mask = [c.get('video_id') != video_id for c in self.chunks]
        chunks_to_remove = [c for c, keep in zip(self.chunks, keep_mask) if not keep]

        # Drop the removed rows from the embedding arrays in place rather than re-encoding
        # the remaining corpus from scratch (same O(n) writes-are-quadratic problem as
        # add_chunks — see _add_chunks_incremental). Falls back to a full reindex() only if
        # an array is missing/misaligned, which reindex() already handles defensively.
        if self.dense_embeddings is not None and len(self.dense_embeddings) == len(self.chunks):
            self.dense_embeddings = self.dense_embeddings[keep_mask]
        if self.visual_embeddings is not None and len(self.visual_embeddings) == len(self.chunks):
            self.visual_embeddings = self.visual_embeddings[keep_mask]

        self.chunks = [c for c, keep in zip(self.chunks, keep_mask) if keep]

        for c in chunks_to_remove:
            keyframe_path = os.path.join(paths.KEYFRAMES_DIR, f"{c['id']}.jpg")
            if os.path.exists(keyframe_path):
                try:
                    os.remove(keyframe_path)
                except Exception as e:
                    print(f"[Vault] Error deleting keyframe {keyframe_path}: {e}")

        # Delete local media file if present
        for ext in ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.mp3', '.wav', '.m4a']:
            fpath = os.path.join(paths.MEDIA_DIR, f"{video_id}{ext}")
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    print(f"[Vault] Error deleting media file {fpath}: {e}")

        # If the embedding arrays weren't aligned with self.chunks going in (e.g. TF-IDF
        # fallback, or a prior mismatch), the mask-based slicing above was skipped for that
        # array — fall back to a full reindex() so the store never ends up with an
        # embeddings/chunks length mismatch.
        if not self.chunks:
            self.dense_embeddings = None
            self.bm25_index = None
            self.is_fitted = True
            self._invalidate_suggested_queries_cache()
        elif self.dense_embeddings is None or len(self.dense_embeddings) != len(self.chunks):
            self.reindex()
        else:
            self._invalidate_suggested_queries_cache()
            self._rebuild_bm25()

        self._save_to_disk()
        return True

    def add_chunks(self, new_chunks: List[Dict[str, Any]]):
        """Add new chunks, embedding only the new ones, and persist."""
        self._add_chunks_incremental(new_chunks)
        self._save_to_disk()

    @staticmethod
    def _bm25_tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9']+", text.lower())

    def _rebuild_bm25(self):
        """(Re)build the BM25 lexical index over all current chunks. Pure Python tokenization
        over raw text — not the expensive part of indexing, so this always runs full-corpus
        even when dense embedding is incremental (see _add_chunks_incremental)."""
        if HAS_BM25 and self.chunks:
            tokenized_corpus = [self._bm25_tokenize(c.get('text', '')) for c in self.chunks]
            self.bm25_index = BM25Okapi(tokenized_corpus) if any(tokenized_corpus) else None
        else:
            self.bm25_index = None

    def _add_chunks_incremental(self, new_chunks: List[Dict[str, Any]]):
        """
        Embed only the newly added chunks and append them onto the existing dense index,
        instead of re-encoding the entire corpus on every write (IMPROVEMENT-PLAN.md hygiene:
        "Full reindex on every write" — add_chunks() used to call reindex(), making each
        ingested video O(total corpus size) instead of O(new chunks), i.e. quadratic across a
        library build). BM25 still rebuilds full-corpus since tokenizing raw text is cheap.
        """
        self._invalidate_suggested_queries_cache()

        if not new_chunks:
            return

        self.chunks.extend(new_chunks)

        if HAS_DENSE_MODEL:
            corpus = [c.get('enriched_text', c['text']) for c in new_chunks]
            new_embeddings = EMBEDDING_MODEL.encode(
                corpus,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False
            )
            if self.dense_embeddings is not None and len(self.dense_embeddings) > 0:
                self.dense_embeddings = np.vstack([self.dense_embeddings, new_embeddings])
            else:
                self.dense_embeddings = new_embeddings
        else:
            # TF-IDF's vocabulary depends on the whole corpus, so there's no incremental path
            # here — this branch only runs when sentence-transformers itself failed to load.
            full_corpus = [c.get('enriched_text', c['text']) for c in self.chunks]
            self.tfidf_matrix = self.vectorizer.fit_transform(full_corpus)

        self._rebuild_bm25()
        self.is_fitted = True
        print(f"[Vault] Incrementally embedded {len(new_chunks)} new chunk(s); index now {len(self.chunks)} chunks.")

    def reindex(self):
        """
        Re-compute dense embeddings and the BM25 lexical index for ALL stored chunks. This is
        deliberately full-corpus, unlike _add_chunks_incremental — use it only when chunks
        were removed or replaced wholesale (delete_video's fallback path, import 'replace'
        mode) or the TF-IDF fallback is active (its vocabulary always depends on the whole
        corpus). For appending new chunks, add_chunks() takes the incremental path instead.
        """
        self._invalidate_suggested_queries_cache()

        if not self.chunks:
            self.dense_embeddings = None
            self.bm25_index = None
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
            if corpus and hasattr(self, 'vectorizer') and self.vectorizer is not None:
                self.tfidf_matrix = self.vectorizer.fit_transform(corpus)

        self._rebuild_bm25()
        self.is_fitted = True
        print(f"[Vault] Indexed {len(self.chunks)} chunks.")

    @staticmethod
    def _suppress_overlapping(candidates: List[Dict[str, Any]], overlap_threshold: float = 0.5) -> List[Dict[str, Any]]:
        """
        Greedy non-max suppression on [start_sec, end_sec] within the same video. Candidates
        must already be sorted by score descending.

        A small library (total chunk count below the top-30 retrieval pool) makes nearly
        every sentence a "candidate" regardless of relevance, and the ±1-sentence window-merge
        step (search() step 3) then produces several large merged windows that substantially
        overlap in time — e.g. four "results" that all cover roughly the same 90-second span
        of one video, just anchored on different starting sentences, differing only in which
        concepts happened to get attached to match_reason. That reads as four distinct answers
        when it's really the same moment restated. Keep only the highest-scored candidate per
        overlapping time region instead of returning near-duplicates as if they were different
        moments.
        """
        kept: List[Dict[str, Any]] = []
        for cand in candidates:
            cand_dur = cand['end_sec'] - cand['start_sec']
            is_duplicate = False
            for k in kept:
                if k['video_id'] != cand['video_id']:
                    continue
                overlap = min(cand['end_sec'], k['end_sec']) - max(cand['start_sec'], k['start_sec'])
                shorter = min(cand_dur, k['end_sec'] - k['start_sec'])
                if shorter > 0 and overlap / shorter >= overlap_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(cand)
        return kept

    @staticmethod
    def _reciprocal_rank_fusion(score_arrays: List[np.ndarray], k: int = 60) -> np.ndarray:
        """
        Fuse multiple rankers (dense cosine, BM25) into one candidate-selection score via
        Reciprocal Rank Fusion: sum(1 / (k + rank)) across rankers. RRF is used only to build
        the retrieval candidate pool — final relevance is decided later by the cross-encoder
        reranker against RERANK_RELEVANCE_THRESHOLD (2.2), so RRF's small absolute magnitude
        (~1/60 per ranker) is not meant to be compared against any absolute cutoff.
        """
        n = len(score_arrays[0])
        fused = np.zeros(n)
        for scores in score_arrays:
            order = np.argsort(-scores)
            ranks = np.empty(n, dtype=int)
            ranks[order] = np.arange(1, n + 1)
            fused += 1.0 / (k + ranks)
        return fused

    def search(self, query: str, top_k: int = 5, relevance_threshold: Optional[float] = None, search_mode: str = "spoken") -> Dict[str, Any]:
        """
        Retrieval pipeline:
        1. Candidate retrieval (top 30). 'spoken': dense cosine + BM25 lexical, fused via
           Reciprocal Rank Fusion (2.5) so proper nouns/acronyms/product names that dense
           embeddings miss still surface. 'visual_scenes': CLIP image-text cosine similarity.
           `relevance_threshold`, if explicitly passed, prunes this candidate pool — but the
           default (None) applies no floor at all, because CLIP cosine similarity is signed
           and a hardcoded 0.0 floor would silently drop legitimate (if weak) visual
           candidates before they ever reach the real gate in step 4. Candidate selection is
           deliberately NOT what decides whether a result is shown to the user (that's step 4).
        2. Window expansion (±1 surrounding sentence).
        3. Merge overlapping / adjacent windows from the same video.
        4. Final ranking + relevance gate (2.2): 'spoken' candidates are reranked by a
           cross-encoder, and only those whose sigmoid(logit) clears RERANK_RELEVANCE_THRESHOLD
           become `results`. 'visual_scenes' candidates are ranked directly by CLIP similarity
           against VISUAL_RELEVANCE_THRESHOLD (2.8) — the text cross-encoder has no visual
           grounding, so it never touches these. If nothing clears the bar, `results` is empty
           and the closest few candidates are returned as `near_misses` (3.2) instead of the
           old behavior of just not returning anything explicable. If the cross-encoder isn't
           available at all, gating falls back to unranked top-K instead of comparing a
           retrieval-stage score against a threshold calibrated for a completely different
           scale (see `reranker_active` below and its use site).
        """
        start_time = time.time()

        def _empty(near_misses=None, message=None):
            resp = {
                "query": query,
                "results": [],
                "near_misses": near_misses or [],
                "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                "total_chunks_scanned": len(self.chunks),
                "library_video_count": len(self.videos),
                "search_mode": search_mode,
                "degraded": False,
            }
            if message:
                resp["message"] = message
            return resp

        if not self.chunks or not self.is_fitted or not query.strip():
            return _empty()

        search_query = query

        # Step 1: Candidate retrieval
        if search_mode == "visual_scenes":
            # Distinct from "no results for this query" — this library structurally cannot
            # do moment-level visual search at all (2.10), so say that instead of a bare
            # empty state indistinguishable from "nothing matched."
            if not any(c.get('visual_status') == 'ok' for c in self.chunks):
                return _empty(message=(
                    "This library has no per-moment visual data yet — indexed video is "
                    "YouTube content, which only has a shared video-level thumbnail per "
                    "video, not real frames. Upload a local video/audio file to enable "
                    "on-screen (CLIP) search."
                ))

            clip_vec = MultimodalEngine.embed_text_clip(query)
            if clip_vec is not None and self.visual_embeddings is not None and len(self.visual_embeddings) == len(self.chunks):
                similarities = np.dot(self.visual_embeddings, clip_vec)
                # YouTube chunks share one video-level thumbnail across every chunk of that
                # video — ranking *moments* by it is meaningless (2.10), so exclude them here
                # rather than let the UI's "visual indexed" badge imply moment-level search.
                for i, c in enumerate(self.chunks):
                    if c.get('visual_status') == 'video-level':
                        similarities[i] = -1.0
            elif HAS_DENSE_MODEL and self.dense_embeddings is not None:
                query_vec = EMBEDDING_MODEL.encode([search_query], convert_to_numpy=True, normalize_embeddings=True)[0]
                similarities = np.dot(self.dense_embeddings, query_vec)
            elif hasattr(self, 'vectorizer') and self.vectorizer is not None and self.tfidf_matrix is not None:
                query_vec = self.vectorizer.transform([search_query])
                similarities = cosine_similarity(query_vec, self.tfidf_matrix)[0]
            else:
                similarities = np.zeros(len(self.chunks))
        else:
            dense_sims = None
            if HAS_DENSE_MODEL and self.dense_embeddings is not None:
                query_vec = EMBEDDING_MODEL.encode([search_query], convert_to_numpy=True, normalize_embeddings=True)[0]
                dense_sims = np.dot(self.dense_embeddings, query_vec)
            elif hasattr(self, 'vectorizer') and self.tfidf_matrix is not None:
                query_vec = self.vectorizer.transform([search_query])
                dense_sims = cosine_similarity(query_vec, self.tfidf_matrix)[0]

            bm25_sims = None
            if self.bm25_index is not None:
                bm25_sims = np.array(self.bm25_index.get_scores(self._bm25_tokenize(search_query)))

            if dense_sims is not None and bm25_sims is not None:
                similarities = self._reciprocal_rank_fusion([dense_sims, bm25_sims])
            elif dense_sims is not None:
                similarities = dense_sims
            elif bm25_sims is not None:
                similarities = bm25_sims
            else:
                similarities = np.zeros(len(self.chunks))

            # Suppress non-speech / visual-only synthetic chunks from spoken transcript search
            for i, c in enumerate(self.chunks):
                if c.get('is_visual_only') or c.get('text', '').startswith('[Visual Scene'):
                    similarities[i] = -999.0

        if relevance_threshold is not None:
            scored_indices = [(idx, float(score)) for idx, score in enumerate(similarities) if float(score) >= relevance_threshold and float(score) > -500.0]
        else:
            scored_indices = [(idx, float(score)) for idx, score in enumerate(similarities) if float(score) > -500.0]
        scored_indices.sort(key=lambda x: x[1], reverse=True)
        top_sentence_matches = scored_indices[:30]

        if not top_sentence_matches:
            return _empty()

        # Step 2: Window Expansion (±1 sentence) & Candidate Construction
        # Group chunks by video_id for fast sentence lookup
        video_chunks_map: Dict[str, List[Dict[str, Any]]] = {}
        for c in self.chunks:
            vid = c.get('video_id', '')
            if vid not in video_chunks_map:
                video_chunks_map[vid] = []
            video_chunks_map[vid].append(c)

        for vid in video_chunks_map:
            video_chunks_map[vid].sort(key=lambda x: x.get('sentence_idx') if x.get('sentence_idx') is not None else -1)

        expanded_candidates = []

        for idx, dense_score in top_sentence_matches:
            target_chunk = self.chunks[idx]
            vid_id = target_chunk.get('video_id', '')
            s_idx = target_chunk.get('sentence_idx')
            vid_sentences = video_chunks_map.get(vid_id, [])

            if s_idx is None:
                # Chunk predates sentence-level indexing (should be rare — _load_from_disk
                # evicts these on boot — but defends against e.g. an old export merged in
                # at runtime via /api/import/library). Treat it as an isolated window rather
                # than guessing a sentence position, so it can't silently merge with neighbors.
                window_sentences = [target_chunk]
            else:
                # Expand window to ±1 sentence
                matched_pos = next((i for i, sc in enumerate(vid_sentences) if sc['id'] == target_chunk['id']), 0)
                start_pos = max(0, matched_pos - 1)
                end_pos = min(len(vid_sentences) - 1, matched_pos + 1)
                window_sentences = vid_sentences[start_pos:end_pos + 1]

            combined_text = " ".join([s['text'] for s in window_sentences]).strip()
            min_start_sec = window_sentences[0].get('start_sec', 0.0)
            max_end_sec = window_sentences[-1].get('end_sec', 0.0)

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
                "visual_status": target_chunk.get('visual_status'),
                # Legacy (pre-sentence-index) chunks get a unique sentinel range keyed on
                # their position in self.chunks, so they sort deterministically but can
                # never numerically overlap/merge with a real sentence range (guarded
                # explicitly below via is_legacy_window too).
                "sentence_range": (
                    (window_sentences[0].get('sentence_idx'), window_sentences[-1].get('sentence_idx'))
                    if s_idx is not None else (idx, idx)
                ),
                "is_legacy_window": s_idx is None,
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
            # Check if same video, both sentence-indexed, and overlapping/adjacent ranges
            if last['video_id'] == candidate['video_id'] and not last['is_legacy_window'] and not candidate['is_legacy_window']:
                last_start_s, last_end_s = last['sentence_range']
                cand_start_s, cand_end_s = candidate['sentence_range']

                if cand_start_s <= last_end_s + 1:
                    new_start_s = min(last_start_s, cand_start_s)
                    new_end_s = max(last_end_s, cand_end_s)

                    # Reconstruct merged text without duplicate sentences
                    vid_sents = video_chunks_map.get(last['video_id'], [])
                    merged_sents = [s for s in vid_sents if new_start_s <= s.get('sentence_idx', 0) <= new_end_s]
                    prospective_duration = (merged_sents[-1]['end_sec'] - merged_sents[0]['start_sec']) if merged_sents else 0

                    # Cap how large a "small-to-big" merge can grow. Without this, a query
                    # whose retrieval signal is spread across most of one video's chunks —
                    # e.g. searching a video *about* databases for "database" — can chain-merge
                    # nearly every adjacent window into one candidate spanning almost the
                    # entire video. That's the exact failure this pipeline exists to avoid
                    # (IMPROVEMENT-PLAN.md 1.1: "jump to moment" landing on the whole video
                    # instead of a moment), and it can resurface here even with correct
                    # per-sentence data if enough of one video's chunks land in the candidate
                    # pool. Found via the eval harness (2.1), not by inspection.
                    if prospective_duration <= MAX_MERGED_WINDOW_SECONDS:
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
                    # else: merging would exceed the cap — treat candidate as the start of
                    # a new merged group instead of falling through silently unbounded.

            merged_candidates.append(candidate)

        # Step 4: Final ranking + relevance gate
        reranker_active = False
        if search_mode == 'visual_scenes':
            # No text cross-encoder here — it has no visual grounding, so letting it
            # re-rank CLIP scene matches would just replace an honest visual ranking with
            # an arbitrary textual one (2.8). Rank + gate directly on CLIP similarity.
            for cand in merged_candidates:
                cand['score'] = cand['dense_score']
            merged_candidates.sort(key=lambda x: x['score'], reverse=True)
            relevance_cutoff = VISUAL_RELEVANCE_THRESHOLD
            strong_cutoff = VISUAL_STRONG_THRESHOLD
        else:
            reranker = get_cross_encoder()
            if reranker is not None and merged_candidates:
                try:
                    pairs = [(query, cand['text']) for cand in merged_candidates]
                    rerank_scores = reranker.predict(pairs)
                    for idx, cand in enumerate(merged_candidates):
                        raw_rerank = float(rerank_scores[idx])
                        cand['score'] = round(1.0 / (1.0 + math.exp(-raw_rerank)), 4)
                        cand['rerank_score'] = raw_rerank
                    merged_candidates.sort(key=lambda x: x['score'], reverse=True)
                    reranker_active = True
                except Exception as e:
                    print(f"[Vault] CrossEncoder prediction error: {e}")
                    merged_candidates.sort(key=lambda x: x['score'], reverse=True)
            else:
                merged_candidates.sort(key=lambda x: x['score'], reverse=True)
            relevance_cutoff = RERANK_RELEVANCE_THRESHOLD
            strong_cutoff = RERANK_STRONG_THRESHOLD

        def _attach_match_reason(item):
            topic = item.get('section_topic', 'spoken content')
            concepts = item.get('implicit_concepts', [])
            if search_mode == 'visual_scenes':
                item['match_reason'] = f"Matched visual scene frame for '{topic}'"
            elif concepts and len(concepts) >= 2:
                item['match_reason'] = f"Matched: {concepts[0]} & {concepts[1]}"
            elif concepts:
                item['match_reason'] = f"Matched: {concepts[0]}"
            else:
                item['match_reason'] = f"Matched topic: {topic}"
            return item

        results = []
        near_misses = []
        message = None

        # 'spoken' mode's relevance_cutoff (RERANK_RELEVANCE_THRESHOLD=0.08) is calibrated
        # exclusively for sigmoid(cross-encoder logit) scores. When the reranker didn't run
        # (model failed to load — e.g. no network to fetch it from HuggingFace Hub the first
        # time, which has happened in practice — or raised during prediction), `cand['score']`
        # is left as the retrieval-stage score instead: an RRF-fused value that maxes out
        # around 0.03, or a raw cosine/BM25 score on yet another scale. Comparing THAT against
        # 0.08 isn't "stricter", it's wrong — RRF-fused scores can never clear it, so every
        # single query would silently return zero results despite good candidates existing.
        # Fall back to unranked top-K instead of pretending a calibrated cutoff still applies.
        if search_mode != 'visual_scenes' and not reranker_active and merged_candidates:
            for item in self._suppress_overlapping(merged_candidates)[:top_k]:
                item['confidence'] = 'unranked'
                results.append(_attach_match_reason(item))
            message = ("Relevance reranker is unavailable right now, so these matches are "
                       "unranked best-effort results rather than confidence-scored ones.")
        else:
            qualifying = [c for c in merged_candidates if c['score'] >= relevance_cutoff]
            qualifying = self._suppress_overlapping(qualifying)
            if qualifying:
                for item in qualifying[:top_k]:
                    item['confidence'] = 'strong' if item['score'] >= strong_cutoff else 'possible'
                    results.append(_attach_match_reason(item))
            elif merged_candidates:
                # Nothing cleared the relevance bar — this is deliberately an empty result
                # set, not a best-effort guess (2.2). Surface the closest few candidates
                # separately so the UI can say "closest matches" instead of a bare void (3.2).
                for item in self._suppress_overlapping(merged_candidates)[:3]:
                    item['confidence'] = 'weak'
                    near_misses.append(_attach_match_reason(item))

        resp = {
            "query": query,
            "results": results,
            "near_misses": near_misses,
            "execution_time_ms": round((time.time() - start_time) * 1000, 2),
            "total_chunks_scanned": len(self.chunks),
            "library_video_count": len(self.videos),
            "search_mode": search_mode,
            "degraded": search_mode != 'visual_scenes' and not reranker_active,
        }
        if message:
            resp["message"] = message
        return resp

    def get_suggested_queries(self) -> List[str]:
        """
        Suggested queries from real indexed topics (IMPROVEMENT-PLAN.md 3.1). The old
        version walked chunks in index order and cycled through 6 templates regardless of
        which concepts landed in which slot, producing grammatically-broken pairings like
        "How do english lesson and weather compare?" — the first thing a new user saw.

        Now: rank concepts by (corpus IDF × recurrence) so genuinely distinctive, recurring
        topics surface instead of arbitrary index-order pairings, take the top 4 distinct
        ones, and use one clean template. Cached until the index changes (invalidated by
        _invalidate_suggested_queries_cache, called from reindex/delete_video/import_library).
        """
        if self._suggested_queries_cache is not None:
            return self._suggested_queries_cache

        if not self.chunks:
            self._suggested_queries_cache = []
            return []

        idf_lookup = MultimodalEngine.compute_corpus_idf([c.get('text', '') for c in self.chunks if not c.get('is_visual_only')])

        GENERIC_STOP_CONCEPTS = {
            "available", "right", "going", "said", "think", "know", "really", "good",
            "make", "well", "like", "time", "people", "want", "get", "thing", "video",
            "first", "something", "anything", "everything", "welcome", "today", "greatest",
            "world", "parents", "brother", "sister", "friend", "guy", "guys", "day", "way",
            "see", "look", "come", "go", "back", "take", "give", "also", "even", "much",
            "many", "some", "other", "new", "old", "one", "two", "three", "number", "part",
            "lot", "lots", "kind", "kinds", "sort", "sorts", "type", "types", "need", "work",
            "call", "tell", "say", "talk", "talking", "used", "using", "use", "sure", "okay",
            "yeah", "right", "here", "there", "never", "always", "every", "feel", "feels"
        }

        def _is_meaningful(concept: str) -> bool:
            c_lower = concept.strip().lower()
            if not c_lower or len(c_lower) < 3:
                return False
            if " " not in c_lower and c_lower in GENERIC_STOP_CONCEPTS:
                return False
            return True

        concept_freq: Dict[str, int] = {}
        concept_display: Dict[str, str] = {}
        for chunk in self.chunks:
            if chunk.get('is_visual_only') or chunk.get('text', '').startswith('[Visual Scene'):
                continue

            sec_topic = chunk.get('section_topic', '')
            if sec_topic and len(sec_topic) > 3:
                for part in sec_topic.split('&'):
                    p = part.strip()
                    if _is_meaningful(p):
                        k = p.lower()
                        concept_freq[k] = concept_freq.get(k, 0) + 2
                        concept_display.setdefault(k, p)

            for concept in chunk.get('implicit_concepts', []):
                if _is_meaningful(concept):
                    key = concept.lower().strip()
                    concept_freq[key] = concept_freq.get(key, 0) + 1
                    concept_display.setdefault(key, concept)

        def _score(key: str) -> float:
            words = key.split()
            weights = [idf_lookup.get(w, 1.0) for w in words if w]
            idf_weight = sum(weights) / len(weights) if weights else 1.0
            return idf_weight * math.log1p(concept_freq[key])

        ranked = sorted(concept_freq.keys(), key=_score, reverse=True)

        suggestions = []
        for key in ranked:
            disp = concept_display[key].strip()
            phrase = f"Where did I talk about {disp}?"
            if phrase not in suggestions:
                suggestions.append(phrase)
            if len(suggestions) >= 4:
                break

        self._suggested_queries_cache = suggestions
        return suggestions

    def _invalidate_suggested_queries_cache(self):
        self._suggested_queries_cache = None

    def get_stats(self) -> Dict[str, Any]:
        """Return comprehensive library stats including status counts and visual coverage."""
        total_seconds = sum(v.get('total_seconds', 0) for v in self.videos.values() if v.get('status') == 'fully_indexed')
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        indexed_count = sum(1 for v in self.videos.values() if v.get('status') == 'fully_indexed')
        failed_count = sum(1 for v in self.videos.values() if v.get('status') == 'failed')
        indexing_count = sum(1 for v in self.videos.values() if v.get('status') == 'indexing')
        is_fully_indexed = (len(self.videos) > 0 and failed_count == 0 and indexing_count == 0)

        # 'ok' = a real per-moment frame; excludes video-level shared YouTube thumbnails (2.10).
        visual_indexed_count = sum(1 for c in self.chunks if c.get('visual_status') == 'ok')

        return {
            "total_videos": len(self.videos),
            "indexed_count": indexed_count,
            "failed_count": failed_count,
            "indexing_count": indexing_count,
            "is_fully_indexed": is_fully_indexed,
            "total_chunks": len(self.chunks),
            "visual_indexed_count": visual_indexed_count,
            "total_hours": f"{hours}h {minutes}m",
            "embedding_model": "all-MiniLM-L6-v2 + CLIP" if HAS_DENSE_MODEL else "TF-IDF",
            "is_fitted": self.is_fitted
        }
