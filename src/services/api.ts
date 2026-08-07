import {
  SearchResponse, VideoItem, LibraryStats, EngineJob, ClipCandidate, BrandKit,
  StudioToolInfo, VoiceProfile, PlatformRules, PlatformRule, StudioUsageSummary, ToolRun,
  ParsedTranscriptInfo, TranscriptSourceSentence, AgentChatResponse, AgentStreamEvent,
} from '../types';

// Configurable via VITE_API_URL so changing the backend's port/host doesn't require a code
// change — and, critically, doesn't strand every already-persisted chunk whose keyframe_url
// was baked in as an absolute URL under the old hardcoded value (IMPROVEMENT-PLAN.md hygiene:
// "Hardcoded URLs"). Set it in a .env.local (see .env.example) if the backend isn't on
// http://localhost:8000.
export const API_ORIGIN = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE_URL = `${API_ORIGIN}/api`;

/**
 * Resolve a possibly-relative media URL (keyframe_url, local media path) against the
 * configured API origin. Absolute URLs (YouTube thumbnails, old persisted chunks that still
 * carry a baked-in absolute keyframe_url) pass through unchanged.
 */
export function resolveMediaUrl(path?: string | null): string | undefined {
  if (!path) return undefined;
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_ORIGIN}${path.startsWith('/') ? '' : '/'}${path}`;
}

/**
 * Check if the backend API is reachable.
 */
export async function checkBackendHealth(): Promise<{ healthy: boolean; details?: any }> {
  try {
    const response = await fetch(`${API_BASE_URL}/health`, { signal: AbortSignal.timeout(3000) });
    if (response.ok) {
      const data = await response.json();
      return { healthy: true, details: data };
    }
    return { healthy: false };
  } catch {
    return { healthy: false };
  }
}

/**
 * Multimodal semantic search via backend with search mode selection.
 */
export async function performSearch(query: string, searchMode: string = 'spoken'): Promise<SearchResponse> {
  const response = await fetch(`${API_BASE_URL}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: 10, search_mode: searchMode })
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Search failed' }));
    throw new Error(detail.detail || `Search failed (${response.status})`);
  }

  return await response.json();
}

/**
 * Fetch dynamic sample query suggestions based on real indexed topics (no hardcoded samples).
 */
export async function fetchSuggestedQueries(): Promise<string[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/suggested_queries`);
    if (!response.ok) return [];
    return await response.json();
  } catch (err) {
    // Swallowed to an empty list so the UI degrades gracefully, but logged so a real
    // backend failure doesn't silently look identical to "no suggestions yet" (hygiene:
    // "Silent excepts" in IMPROVEMENT-PLAN.md).
    console.error('fetchSuggestedQueries failed:', err);
    return [];
  }
}

/**
 * Fetch all indexed and failed videos from backend.
 */
export async function fetchLibraryVideos(): Promise<VideoItem[]> {
  const response = await fetch(`${API_BASE_URL}/library`);
  if (!response.ok) {
    throw new Error('Failed to fetch library');
  }
  return await response.json();
}

/**
 * Fetch library stats from backend.
 */
export async function fetchLibraryStats(): Promise<LibraryStats> {
  const response = await fetch(`${API_BASE_URL}/stats`);
  if (!response.ok) {
    throw new Error('Failed to fetch stats');
  }
  return await response.json();
}

/** Result of kicking off an ingest: either it started a background job (job_id present —
 * poll it via pollJob), or it short-circuited synchronously because the content was already
 * indexed (the dedup fast path in main.py, which never touches the job queue). */
export interface IngestStartResult {
  job_id?: string;
  video_id?: string;
  filename?: string;
  success?: boolean;
  message?: string;
  video?: VideoItem;
  new_chunks_count?: number;
}

export function isIngestJobStart(result: IngestStartResult): result is IngestStartResult & { job_id: string } {
  return typeof result.job_id === 'string';
}

/**
 * Ingest a YouTube video by URL via backend. Runs as a background job — poll the returned
 * job_id (see pollJob) rather than expecting the indexed result inline.
 */
export async function ingestVideoUrl(youtubeUrl: string): Promise<IngestStartResult> {
  const response = await fetch(`${API_BASE_URL}/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ youtube_url: youtubeUrl })
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Ingestion failed' }));
    throw new Error(detail.detail || `Ingestion failed (${response.status})`);
  }

  return await response.json();
}

/**
 * Upload a local video/audio file for Whisper transcription + CLIP visual indexing.
 * Runs as a background job (PRD §7.3 — Whisper on CPU is ~1x realtime, so this used to hold
 * the request open for the full duration of a long upload) — poll the returned job_id.
 * `modelTier` selects Whisper accuracy/speed: 'base' | 'small' | 'medium' (default 'small').
 */
export async function uploadLocalFile(file: File, modelTier: string = 'small'): Promise<IngestStartResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('model_tier', modelTier);

  const response = await fetch(`${API_BASE_URL}/upload_transcribe`, {
    method: 'POST',
    body: formData
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(detail.detail || `Upload failed (${response.status})`);
  }

  return await response.json();
}

/**
 * Fetch status/progress for any background job — ingest (upload/YouTube) or ENGINE.
 */
export async function getJob(jobId: string): Promise<EngineJob> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Job not found' }));
    throw new Error(detail.detail || `Job lookup failed (${response.status})`);
  }
  return await response.json();
}

/**
 * Poll a background job until it reaches a terminal state (done/failed), invoking
 * onProgress after every poll so the UI can render live stage/percentage instead of a bare
 * spinner.
 */
export async function pollJob(
  jobId: string,
  onProgress?: (job: EngineJob) => void,
  intervalMs: number = 1200
): Promise<EngineJob> {
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const job = await getJob(jobId);
    onProgress?.(job);
    if (job.status === 'done' || job.status === 'failed') {
      return job;
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
}

/**
 * Delete a video from the indexed library.
 */
export async function deleteLibraryVideo(videoId: string): Promise<{ success: boolean; message: string }> {
  const response = await fetch(`${API_BASE_URL}/library/${videoId}`, {
    method: 'DELETE'
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Deletion failed' }));
    throw new Error(detail.detail || `Deletion failed (${response.status})`);
  }

  return await response.json();
}


export async function engineAnalyze(videoId: string, maxClips: number = 6): Promise<{ job_id: string }> {
  const response = await fetch(`${API_BASE_URL}/engine/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_id: videoId, max_clips: maxClips })
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Analyze failed' }));
    throw new Error(detail.detail || `Analyze failed (${response.status})`);
  }
  return await response.json();
}

export async function engineGetJob(jobId: string): Promise<EngineJob> {
  const response = await fetch(`${API_BASE_URL}/engine/jobs/${jobId}`);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Job not found' }));
    throw new Error(detail.detail || `Job lookup failed (${response.status})`);
  }
  return await response.json();
}

export async function engineGetClips(videoId: string): Promise<ClipCandidate[]> {
  const response = await fetch(`${API_BASE_URL}/engine/clips/${videoId}`);
  if (!response.ok) return [];
  return await response.json();
}

export async function engineAdjustClip(clipId: string, startSec: number, endSec: number): Promise<ClipCandidate> {
  const response = await fetch(`${API_BASE_URL}/engine/clips/${clipId}/adjust`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start_sec: startSec, end_sec: endSec })
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Adjust failed' }));
    throw new Error(detail.detail || `Adjust failed (${response.status})`);
  }
  return await response.json();
}

export async function engineRender(clipId: string, presets: string[]): Promise<{ job_id: string }> {
  const response = await fetch(`${API_BASE_URL}/engine/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clip_id: clipId, presets })
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Render failed' }));
    throw new Error(detail.detail || `Render failed (${response.status})`);
  }
  return await response.json();
}

export function engineClipFileUrl(clipId: string, preset: string): string {
  return `${API_BASE_URL}/engine/clip_file/${encodeURIComponent(clipId)}/${encodeURIComponent(preset)}`;
}

export async function engineGetBrandKit(): Promise<BrandKit> {
  const response = await fetch(`${API_BASE_URL}/engine/brand_kit`);
  if (!response.ok) throw new Error(`Failed to fetch brand kit (${response.status})`);
  return await response.json();
}

export async function engineUpdateBrandKit(patch: Partial<BrandKit>): Promise<BrandKit> {
  const response = await fetch(`${API_BASE_URL}/engine/brand_kit`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch)
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Update failed' }));
    throw new Error(detail.detail || `Update failed (${response.status})`);
  }
  return await response.json();
}

export async function engineAutoseedBrandKit(force: boolean = false): Promise<BrandKit> {
  const response = await fetch(`${API_BASE_URL}/engine/brand_kit/autoseed?force=${force}`, { method: 'POST' });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Autoseed failed' }));
    throw new Error(detail.detail || `Autoseed failed (${response.status})`);
  }
  return await response.json();
}

export async function engineSendFeedback(clipId: string, verdict: 'winner' | 'dud'): Promise<{ label_count: number }> {
  const response = await fetch(`${API_BASE_URL}/engine/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clip_id: clipId, verdict })
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Feedback failed' }));
    throw new Error(detail.detail || `Feedback failed (${response.status})`);
  }
  return await response.json();
}

// --- STUDIO (Layer 4): text-in/text-out creator tools ---
//
// Generic JSON request helpers — the eight-line "fetch, check .ok, parse detail, throw"
// block above is repeated ~25 times in this file for every hand-written endpoint; STUDIO's
// dozen routes go through these instead rather than repeating it a dozen more times.

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: `Request to ${path} failed` }));
    throw new Error(detail.detail || `Request to ${path} failed (${response.status})`);
  }
  return await response.json();
}

function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path);
}

function postJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function putJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function deleteJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, { method: 'DELETE' });
}

export function studioListTools(): Promise<{ tools: StudioToolInfo[]; llm_configured: boolean }> {
  return getJson('/studio/tools');
}

/** Pre-flight classification of a paste — call before enabling generation so tool 6 can be
 * blocked and tool 2 can warn about estimates without spending a run. */
export function studioParseTranscript(text: string): Promise<ParsedTranscriptInfo> {
  return postJson('/studio/parse_transcript', { text });
}

export function studioTranscriptSource(
  videoId: string
): Promise<{ video_id: string; sentences: TranscriptSourceSentence[]; sentence_count: number }> {
  return getJson(`/studio/transcript_source/${encodeURIComponent(videoId)}`);
}

/** Every STUDIO tool runs as a background job (uniform code path, free progress) — poll the
 * returned job_id with the existing pollJob()/getJob() helpers above. */
export function studioRun(
  toolId: string, inputs: Record<string, any>, useVoiceProfile: boolean = true
): Promise<{ job_id: string }> {
  return postJson('/studio/run', { tool_id: toolId, inputs, use_voice_profile: useVoiceProfile });
}

export function studioRegenerate(runId: string, block: string): Promise<{ job_id: string }> {
  return postJson('/studio/regenerate', { run_id: runId, block });
}

export function studioListRuns(toolId?: string, limit: number = 50): Promise<ToolRun[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (toolId) params.set('tool_id', toolId);
  return getJson(`/studio/runs?${params.toString()}`);
}

export function studioGetRun(runId: string): Promise<ToolRun> {
  return getJson(`/studio/runs/${encodeURIComponent(runId)}`);
}

export function studioDeleteRun(runId: string): Promise<{ success: boolean }> {
  return deleteJson(`/studio/runs/${encodeURIComponent(runId)}`);
}

export function studioGetVoiceProfile(): Promise<VoiceProfile> {
  return getJson('/studio/voice_profile');
}

export function studioUpdateVoiceProfile(patch: Partial<VoiceProfile>): Promise<VoiceProfile> {
  return putJson('/studio/voice_profile', patch);
}

export function studioAutoseedVoiceProfile(force: boolean = false): Promise<VoiceProfile> {
  return postJson(`/studio/voice_profile/autoseed?force=${force}`);
}

export function studioGetPlatformRules(): Promise<PlatformRules> {
  return getJson('/studio/platform_rules');
}

export function studioUpdatePlatformRules(patch: Record<string, Partial<PlatformRule>>): Promise<PlatformRules> {
  return putJson('/studio/platform_rules', patch);
}

export function studioGetUsage(): Promise<StudioUsageSummary> {
  return getJson('/studio/usage');
}

