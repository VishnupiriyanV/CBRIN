/**
 * Recent search history, persisted in localStorage (IMPROVEMENT-PLAN.md 3.6).
 * Most-recent-first, deduplicated case-insensitively, capped at MAX_HISTORY.
 */
const STORAGE_KEY = 'vault_query_history';
const MAX_HISTORY = 8;

export function getQueryHistory(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((q) => typeof q === 'string') : [];
  } catch {
    return [];
  }
}

export function addToQueryHistory(query: string): string[] {
  const trimmed = query.trim();
  if (!trimmed) return getQueryHistory();

  try {
    const existing = getQueryHistory().filter((q) => q.toLowerCase() !== trimmed.toLowerCase());
    const updated = [trimmed, ...existing].slice(0, MAX_HISTORY);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    return updated;
  } catch {
    return getQueryHistory();
  }
}

export function clearQueryHistory(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
