export interface VideoItem {
  id: string;
  youtube_id?: string;
  is_local?: boolean;
  title: string;
  channel: string;
  duration_formatted: string;
  total_seconds: number;
  thumbnail_url: string;
  chunk_count: number;
  visual_chunk_count?: number;
  uploaded_at: string;
  category: string;
  status: 'fully_indexed' | 'indexing' | 'failed';
  error_message?: string | null;
  summary?: string;
  topics?: string[];
}

// 'unranked': the cross-encoder reranker was unavailable (failed to load / threw), so these
// are unranked best-effort retrieval results rather than confidence-scored ones — see
// SearchResponse.degraded.
export type MatchConfidence = 'strong' | 'possible' | 'weak' | 'unranked';

export interface ChunkResult {
  id: string;
  video_id: string;
  video_title: string;
  channel: string;
  youtube_id?: string;
  is_local?: boolean;
  start_sec: number;
  end_sec: number;
  start_timestamp: string;
  end_timestamp: string;
  text: string;
  score: number;
  confidence?: MatchConfidence;
  matched_concepts: string[];
  thumbnail_url: string;
  keyframe_url?: string | null;
  visual_status?: 'ok' | 'video-level' | 'failed';
  section_topic?: string;
  questions_answered?: string[];
  implicit_concepts?: string[];
  has_visual_embedding?: boolean;
  is_highlighted?: boolean;
  indexed_at?: string;
  match_reason?: string;
}

export interface SearchResponse {
  query: string;
  results: ChunkResult[];
  near_misses?: ChunkResult[];
  execution_time_ms: number;
  total_chunks_scanned: number;
  library_video_count: number;
  search_mode?: string;
  message?: string;
  // True when 'results' are unranked best-effort matches because the relevance reranker
  // was unavailable, not confidence-scored ones (see MatchConfidence 'unranked').
  degraded?: boolean;
}

export interface LibraryStats {
  total_videos: number;
  indexed_count: number;
  failed_count: number;
  indexing_count: number;
  is_fully_indexed: boolean;
  total_chunks: number;
  visual_indexed_count: number;
  total_highlights: number;
  total_hours: string;
  embedding_model: string;
  is_fitted: boolean;
}

// --- ENGINE (Layer 3): narrative-aware clip generation ---

export type EngineJobStatus = 'queued' | 'running' | 'done' | 'failed';

export interface EngineJob {
  id: string;
  kind: string;
  video_id?: string | null;
  status: EngineJobStatus;
  stage: string;
  progress: number;
  message: string;
  error?: string | null;
  result?: Record<string, any> | null;
  created_at: number;
  updated_at: number;
}

// Named, inspectable signals only — never a fabricated "predicted engagement %".
export interface ClipSignals {
  hook_strength: number;
  self_containedness: number;
  emotional_delta: number;
  quotability: number;
  boundary_cleanliness: number;
  taste_match?: number; // present only once >=10 creator feedback labels exist
}

export interface NarrativeBeat {
  beat_type: string;
  start_sentence_idx: number;
  end_sentence_idx: number;
  requires_setup_from_idx: number | null;
  title: string;
  why_it_lands: string;
  emotional_arc: Record<string, string>;
  self_contained: boolean;
  quotable_line: string;
}

export interface ClipCandidate {
  id: string;
  video_id: string;
  start_sentence_idx: number;
  end_sentence_idx: number;
  start_sec: number;
  end_sec: number;
  title: string;
  quotable_line: string;
  beats: NarrativeBeat[];
  signals: ClipSignals;
  composite: number;
  reason: string;
  degraded: boolean;
  timing_precise: boolean;
}

export interface BrandKit {
  fonts: { caption: string; display: string };
  colors: { primary: string; accent: string; text: string; stroke: string };
  caption: {
    position: string;
    case: string;
    size: string;
    max_words_per_cue: number;
    highlight_style: string;
    animation: string;
  };
  rhythm: { avg_shot_sec: number; wpm: number };
  safe_margins: { top: number; bottom: number };
  auto_seeded: boolean;
}

export const RENDER_PRESETS = ['tiktok', 'shorts', 'linkedin', 'x'] as const;
export type RenderPreset = typeof RENDER_PRESETS[number];

export interface Highlight {
  chunk_id: string;
  video_id: string;
  video_title: string;
  channel: string;
  text: string;
  start_sec: number;
  end_sec: number;
  start_timestamp: string;
  end_timestamp: string;
  thumbnail_url: string;
  keyframe_url?: string | null;
  youtube_id?: string;
  is_local?: boolean;
  section_topic?: string;
  note: string;
  highlighted_at: string;
}
