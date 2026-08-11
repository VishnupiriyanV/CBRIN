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
  // `text` is the quote to display: trimmed server-side to the sentences that actually
  // matched. `full_text` is the untrimmed merged window, present only when trimming
  // actually happened — the UI offers it back behind "Show full passage" so the shorter
  // default never costs the user context they wanted.
  text: string;
  full_text?: string;
  // Time span of the trimmed quote. Distinct from start_sec/end_sec, which still describe
  // the full window and are what "Jump" and the copied citation use.
  focus_start_sec?: number;
  focus_end_sec?: number;
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

// POST /api/answer. `answer` is null whenever there is nothing trustworthy to show — the
// quotes didn't answer the question, no LLM is configured, the rate limit was hit, or the
// call failed. All of those are the same thing to the UI: render results only. `reason` is
// for debugging, not for display.
export interface AnswerResponse {
  answer: string | null;
  // 1-based indices into the results array that was sent, already validated server-side to
  // be in range.
  citations: number[];
  truncated?: boolean;
  reason?: string;
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

// What word-boundary snapping did to a clip's bounds — set by the analysis run
// (word_timing.snap_clip_bounds) and overwritten by POST /engine/clips/{id}/adjust
// (word_timing.snap_to_words), so it always describes the CURRENT start_sec/end_sec.
// `snapped: false` with a reason naming the snap window is a deliberate refusal, not a
// failure: the boundary sat in silence with no word edge in range, and leaving it alone
// beats dragging it seconds across the gap. That's the case worth telling the user about,
// since the handle they dragged comes back looking untouched either way.
export interface BoundarySnap {
  snapped: boolean;
  start_moved_by: number; // seconds, signed (positive = start moved later)
  end_moved_by: number;   // seconds, signed (positive = end moved later)
  reason: string;         // per-edge outcomes, start first, joined by "; "
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
  // The beat type covering the clip's opening sentence, preferring "hook" — feeds
  // clip_scoring's hook_strength beat_bonus. Not present on older persisted clips.
  opening_beat_type?: string | null;
  signals: ClipSignals;
  // Explainable cues behind derived signals (currently just hook_strength) — separate from
  // `signals` because clip_scoring.score_candidate's composite is a weighted sum keyed by
  // WEIGHTS, so anything added to `signals` without a matching weight throws server-side.
  signal_details?: { hook_cues?: Record<string, number> };
  composite: number;
  reason: string;
  degraded: boolean;
  // Present once analyze_video's mode/degraded_reason are populated (see narrative_engine.py
  // analyze_video). Older persisted clips predate this contract and won't have it — render a
  // sensible fallback rather than assuming it's always set.
  degraded_reason?: string | null;
  analysis_mode?: 'llm' | 'llm_partial' | 'heuristic';
  timing_precise: boolean;
  // Absent on clips persisted before boundary snapping existed.
  boundary_snap?: BoundarySnap;
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

// --- STUDIO (Layer 4): text-in/text-out creator tools ---

export interface StudioToolInfo {
  id: string;
  label: string;
  description: string;
  needs_timestamps: boolean;
}

export interface VoiceProfile {
  niche: string;
  audience: string;
  tone: string[];
  banned_words: string[];
  sample_content: string[];
  default_platforms: string[];
  cta_style: string;
  auto_seeded: boolean;
}

export interface StudioUsageSummary {
  runs_this_hour: number;
  runs_today: number;
  runs_this_month: number;
  tokens_in_month: number;
  tokens_out_month: number;
  model: string;
  limits: { max_input_words: number; max_runs_per_hour: number };
}

export interface ToolRun {
  id: string;
  tool_id: string;
  inputs: Record<string, any>;
  output: Record<string, any>;
  meta: Record<string, any>;
  created_at: number;
}

export interface ParsedTranscriptInfo {
  format: 'srt' | 'vtt' | 'plain';
  has_timestamps: boolean;
  sentence_count: number;
  duration_sec: number | null;
  word_count: number;
}

export interface TranscriptSourceSentence {
  sentence_idx: number;
  text: string;
  start_sec: number;
  end_sec: number;
}

export interface GuardrailNotes {
  frameworks_missing?: string[];
  banned_words_removed?: string[];
  low_diversity?: boolean;
  dominant_formula?: string;
}

export interface RepurposerOutput {
  linkedin: { hook: string; body: string; cta: string };
  thread: { n: number; text: string }[];
  notes: string[];
  carousel: { title: string; slides: { n: number; headline: string; body: string }[]; caption: string };
  extraction: { core_argument: string; frameworks: string[]; strongest_example: string; contrarian_line: string };
  guardrail_notes: GuardrailNotes;
  run_id: string;
  tool_id: string;
}

export interface ShowNotesChapter {
  time: string | null;
  title: string;
  estimated: boolean;
}

export interface ShowNotesOutput {
  summary: string;
  show_notes: string[];
  chapters: ShowNotesChapter[];
  titles: string[];
  promo: string;
  timestamp_mode: 'real' | 'estimated' | 'none';
  run_id: string;
  tool_id: string;
}

export interface TitleIdea {
  text: string;
  formula: string;
  why: string;
  promise: string;
  char_count: number;
  over_limit: boolean;
}

export interface HookIdea {
  text: string;
  style: string;
}

export interface ThumbnailIdea {
  text: string;
  word_count: number;
  over_word_limit: boolean;
}

export interface TitlesOutput {
  titles: TitleIdea[];
  hooks: HookIdea[];
  thumbnail_text: ThumbnailIdea[];
  guardrail_notes: GuardrailNotes;
  run_id: string;
  tool_id: string;
}

export type CommentFlag = 'hostile' | 'sensitive' | 'business' | 'spam' | null;

export interface ReplyItem {
  comment: string;
  flag: CommentFlag;
  flag_reason: string;
  suggested_reply: string | null;
}

export interface RepliesOutput {
  replies: ReplyItem[];
  run_id: string;
  tool_id: string;
}

export interface CaptionResult {
  caption: string;
  hashtags: string[];
  char_count: number;
  char_limit: number;
  over_limit: boolean;
}

export type CaptionsOutput = Record<string, CaptionResult | string | undefined>;

export interface MomentItem {
  start: string;
  end: string;
  score: number;
  reason: string;
  suggested_title: string;
  type: string;
  visual_dependent: boolean;
}

export interface MomentsOutput {
  moments: MomentItem[];
  run_id: string;
  tool_id: string;
}

// --- STUDIO COPILOT (Layer 4 Agent) ---

export interface AgentToolStep {
  tool: string;
  args: Record<string, any>;
  summary: string;
  data?: Record<string, any>;
}

export interface AgentChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  steps?: AgentToolStep[];
  timestamp: string;
}

export interface AgentUsage {
  prompt_tokens: number;
  completion_tokens: number;
  model: string;
}

export interface AgentChatResponse {
  reply: string;
  steps: AgentToolStep[];
  usage?: AgentUsage;
}

// Typed SSE events from POST /api/studio/agent/chat/stream — see agent_engine.run_agent_turn_stream.
export type AgentStreamEvent =
  | { type: 'token'; content: string }
  | { type: 'tool_start'; tool: string; args: Record<string, any> }
  | { type: 'tool_result'; tool: string; args: Record<string, any>; summary: string; data?: Record<string, any> }
  | { type: 'step'; summary: string }
  | { type: 'usage'; usage: AgentUsage }
  | { type: 'done'; reply: string }
  | { type: 'error'; message: string };

// --- Autonomous Content Pack artifact (agent_tools.generate_content_pack) ---

export interface ContentPackClip {
  rank: number;
  title: string;
  hook: string;
  start_time?: string;
  end_time?: string;
  duration?: number;
  score?: number;
  transcript?: string;
}

export interface ContentPack {
  video_id: string;
  video_title: string;
  goal?: string;
  clips: ContentPackClip[];
  repurposed: Record<string, any> | null;
  titles: Record<string, any> | null;
  show_notes: Record<string, any> | null;
  captions: Record<string, any> | null;
  sources: Array<{ video_id: string; title: string }>;
  errors: Record<string, string>;
}

// A parsed "[video title @ mm:ss]" inline citation from an agent reply.
export interface Citation {
  raw: string;
  title: string;
  timestamp: string;
  seconds: number;
}
