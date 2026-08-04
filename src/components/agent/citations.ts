import { Citation } from '../../types';

// Matches the agent's required inline citation form: [video title @ mm:ss] or [title @ h:mm:ss].
const CITATION_PATTERN = /\[([^\[\]@]+?)\s*@\s*(\d{1,2}:\d{2}(?::\d{2})?)\]/g;

export function timestampToSeconds(timestamp: string): number {
  const parts = timestamp.split(':').map((p) => parseInt(p, 10));
  if (parts.some((p) => Number.isNaN(p))) return 0;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0] || 0;
}

export interface TextSegment {
  kind: 'text';
  content: string;
}

export interface CitationSegment {
  kind: 'citation';
  citation: Citation;
}

export type ContentSegment = TextSegment | CitationSegment;

/** Splits agent reply text into plain-text and citation segments, in order, so the caller
 * can render citations as clickable chips inline without a full markdown parser. */
export function segmentContentWithCitations(text: string): ContentSegment[] {
  const segments: ContentSegment[] = [];
  let lastIndex = 0;

  for (const match of text.matchAll(CITATION_PATTERN)) {
    const [raw, title, timestamp] = match;
    const index = match.index ?? 0;
    if (index > lastIndex) {
      segments.push({ kind: 'text', content: text.slice(lastIndex, index) });
    }
    segments.push({
      kind: 'citation',
      citation: { raw, title: title.trim(), timestamp, seconds: timestampToSeconds(timestamp) },
    });
    lastIndex = index + raw.length;
  }

  if (lastIndex < text.length) {
    segments.push({ kind: 'text', content: text.slice(lastIndex) });
  }

  return segments;
}
