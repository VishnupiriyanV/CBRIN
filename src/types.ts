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
  matched_concepts: string[];
  thumbnail_url: string;
  keyframe_url?: string | null;
  section_topic?: string;
  questions_answered?: string[];
  implicit_concepts?: string[];
  has_visual_embedding?: boolean;
  is_highlighted?: boolean;
  indexed_at?: string;
}

export interface SearchResponse {
  query: string;
  results: ChunkResult[];
  execution_time_ms: number;
  total_chunks_scanned: number;
  library_video_count: number;
  search_mode?: string;
  message?: string;
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
