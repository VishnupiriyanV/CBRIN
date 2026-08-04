import React from 'react';
import { SearchX } from 'lucide-react';
import { ChunkResult } from '../types';
import { ResultCard } from './ResultCard';

interface EmptyStateProps {
  query: string;
  nearMisses?: ChunkResult[];
  // Backend-supplied explanation for *why* nothing came back — e.g. "this library has no
  // per-moment visual data" (2.10) — distinct from the generic relevance-threshold case.
  // Previously computed by the backend but never actually rendered anywhere in the UI.
  message?: string;
  onJumpToMoment?: (result: ChunkResult) => void;
  onToggleHighlight?: (result: ChunkResult) => void;
  searchMode?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ query, nearMisses = [], message, onJumpToMoment, onToggleHighlight, searchMode }) => {
  return (
    <div className="space-y-6 my-8">
      <div className="bg-canvas-soft border border-hairline rounded-lg p-10 text-center max-w-2xl mx-auto space-y-4">
        <div className="w-12 h-12 rounded-full border border-hairline-bright bg-canvas-card mx-auto flex items-center justify-center text-ink-mute">
          <SearchX className="w-5 h-5 text-accent-sunset" />
        </div>

        <div className="space-y-1">
          <span className="eyebrow-mono text-[9px] block text-ink-mute">
            {message ? 'NO SEARCHABLE MATCH' : 'RELEVANCE THRESHOLD NOT MET'}
          </span>
          <h3 className="text-base sm:text-lg font-medium text-ink">
            No matching moments found for "{query}"
          </h3>
        </div>

        <p className="text-xs sm:text-sm text-ink-body max-w-md mx-auto leading-relaxed font-sans">
          {message || 'CBRIN filters out low-confidence results to ensure accuracy. Try rephrasing your topic, asking a direct question, or switching search modes above.'}
        </p>
      </div>

      {/* Near-misses: the closest candidates that didn't clear the relevance bar. Showing
          these — rather than a bare void — is the difference between an honest "nothing
          strong here" and a demo that confidently returns a wrong clip (IMPROVEMENT-PLAN.md 3.2). */}
      {nearMisses.length > 0 && onJumpToMoment && onToggleHighlight && (
        <div className="space-y-3 max-w-2xl mx-auto opacity-80">
          <span className="eyebrow-mono text-[9px] block text-ink-mute text-center">
            NOTHING STRONG — CLOSEST MATCHES
          </span>
          <div className="space-y-4">
            {nearMisses.map((result) => (
              <ResultCard
                key={result.id}
                result={result}
                searchQuery={query}
                onJumpToMoment={onJumpToMoment}
                onToggleHighlight={onToggleHighlight}
                searchMode={searchMode}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
