import { SearchResponse, VideoItem, LibraryStats, Highlight } from '../types';

const API_BASE_URL = 'http://localhost:8000/api';

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
export async function performSearch(query: string, searchMode: string = 'hybrid'): Promise<SearchResponse> {
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
  } catch {
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

/**
 * Ingest a YouTube video by URL via backend.
 */
export async function ingestVideoUrl(youtubeUrl: string): Promise<{
  success: boolean;
  message: string;
  video?: VideoItem;
  new_chunks_count?: number;
}> {
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
 */
export async function uploadLocalFile(file: File): Promise<{
  success: boolean;
  message: string;
  video?: VideoItem;
  new_chunks_count?: number;
}> {
  const formData = new FormData();
  formData.append('file', file);

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

// --- Highlights / Bookmark API ---

/**
 * Add a highlight/bookmark for a chunk result.
 */
export async function addHighlight(chunkId: string, note: string = ""): Promise<{ success: boolean; message: string; highlight?: Highlight }> {
  const response = await fetch(`${API_BASE_URL}/highlights`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chunk_id: chunkId, note })
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Highlight failed' }));
    throw new Error(detail.detail || `Highlight failed (${response.status})`);
  }

  return await response.json();
}

/**
 * Remove a highlight/bookmark.
 */
export async function removeHighlight(chunkId: string): Promise<{ success: boolean; message: string }> {
  const response = await fetch(`${API_BASE_URL}/highlights/${chunkId}`, {
    method: 'DELETE'
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Remove highlight failed' }));
    throw new Error(detail.detail || `Remove highlight failed (${response.status})`);
  }

  return await response.json();
}

/**
 * Fetch all highlighted/bookmarked moments.
 */
export async function fetchHighlights(): Promise<Highlight[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/highlights`);
    if (!response.ok) return [];
    return await response.json();
  } catch {
    return [];
  }
}

// --- Export API ---

/**
 * Export the full library as a downloadable JSON file.
 */
export function exportLibraryJSON(): void {
  const link = document.createElement('a');
  link.href = `${API_BASE_URL}/export/library?format=json`;
  link.download = 'vault_library_export.json';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Export the full library as a downloadable ZIP archive.
 */
export function exportLibraryZIP(): void {
  const link = document.createElement('a');
  link.href = `${API_BASE_URL}/export/library?format=zip`;
  link.download = 'vault_library_export.zip';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Export search results as a downloadable JSON file.
 */
export function exportSearchJSON(query: string, mode: string = 'hybrid'): void {
  const link = document.createElement('a');
  link.href = `${API_BASE_URL}/export/search?query=${encodeURIComponent(query)}&mode=${encodeURIComponent(mode)}&format=json`;
  link.download = `vault_search_${query.slice(0, 30).replace(/\s+/g, '_')}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Export search results as a downloadable CSV file.
 */
export function exportSearchCSV(query: string, mode: string = 'hybrid'): void {
  const link = document.createElement('a');
  link.href = `${API_BASE_URL}/export/search?query=${encodeURIComponent(query)}&mode=${encodeURIComponent(mode)}&format=csv`;
  link.download = `vault_search_${query.slice(0, 30).replace(/\s+/g, '_')}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Export highlights as a downloadable JSON file.
 */
export function exportHighlightsJSON(): void {
  const link = document.createElement('a');
  link.href = `${API_BASE_URL}/export/highlights`;
  link.download = 'vault_highlights_export.json';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// --- Import API ---

/**
 * Import a library backup file (JSON or ZIP).
 */
export async function importLibrary(file: File, mode: string = 'merge'): Promise<{
  success: boolean;
  message: string;
  videos_imported?: number;
  chunks_imported?: number;
}> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/import/library?mode=${encodeURIComponent(mode)}`, {
    method: 'POST',
    body: formData
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Import failed' }));
    throw new Error(detail.detail || `Import failed (${response.status})`);
  }

  return await response.json();
}
