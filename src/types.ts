export interface VideoItem {
  id: string;
  youtube_id?: string;
  title: string;
  channel: string;
  duration_formatted: string;
  total_seconds: number;
  thumbnail_url: string;
  chunk_count: number;
  uploaded_at: string;
  category: string;
}

export interface ChunkResult {
  id: string;
  video_id: string;
  video_title: string;
  channel: string;
  youtube_id?: string;
  start_sec: number;
  end_sec: number;
  start_timestamp: string;
  end_timestamp: string;
  text: string;
  score: number; // 0.0 to 1.0 similarity score
  matched_concepts: string[];
  thumbnail_url: string;
}

export interface SearchResponse {
  query: string;
  results: ChunkResult[];
  execution_time_ms: number;
  total_chunks_scanned: number;
  library_video_count: number;
}

export interface IngestRequest {
  youtube_url: string;
  custom_title?: string;
}

export interface LibraryStats {
  total_videos: number;
  total_chunks: number;
  total_hours: string;
  last_indexed: string;
}
