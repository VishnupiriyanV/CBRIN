import React from 'react';
import { SearchX } from 'lucide-react';

interface EmptyStateProps {
  query: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ query }) => {
  return (
    <div className="bg-canvas-soft border border-hairline rounded-lg p-10 text-center max-w-2xl mx-auto my-8 space-y-4">
      <div className="w-12 h-12 rounded-full border border-hairline-bright bg-canvas-card mx-auto flex items-center justify-center text-ink-mute">
        <SearchX className="w-5 h-5 text-accent-sunset" />
      </div>

      <div className="space-y-1">
        <span className="eyebrow-mono text-[9px] block text-ink-mute">RELEVANCE THRESHOLD NOT MET</span>
        <h3 className="text-base sm:text-lg font-medium text-ink">
          No matching moments found for "{query}"
        </h3>
      </div>

      <p className="text-xs sm:text-sm text-ink-body max-w-md mx-auto leading-relaxed font-sans">
        Vault filters out low-confidence results to ensure accuracy. Try rephrasing your topic, asking a direct question, or switching search modes above.
      </p>
    </div>
  );
};
