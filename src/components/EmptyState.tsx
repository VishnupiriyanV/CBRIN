import React from 'react';
import { SearchX, Sparkles } from 'lucide-react';

interface EmptyStateProps {
  query: string;
  onSelectSample: (sample: string) => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ query, onSelectSample }) => {
  return (
    <div className="bg-canvas-soft border border-hairline rounded-lg p-10 text-center max-w-2xl mx-auto my-8 space-y-4">
      <div className="w-12 h-12 rounded-full border border-hairline-bright bg-canvas-card mx-auto flex items-center justify-center text-ink-mute">
        <SearchX className="w-6 h-6 text-accent-sunset" />
      </div>

      <div className="space-y-1">
        <span className="eyebrow-mono text-[9px] block text-ink-mute">RELEVANCE THRESHOLD NOT MET</span>
        <h3 className="text-base sm:text-lg font-medium text-ink">
          No spoken moments found for "{query}"
        </h3>
      </div>

      <p className="text-xs sm:text-sm text-ink-body max-w-md mx-auto leading-relaxed">
        Vault only displays results that clear a minimum semantic relevance score. Try asking a different natural-language question or explore these suggestions:
      </p>

      <div className="pt-2 flex flex-wrap justify-center gap-2">
        <button
          onClick={() => onSelectSample("when did I talk about imposter syndrome")}
          className="px-3 py-1.5 rounded-full border border-hairline bg-canvas-card hover:border-hairline-bright text-xs text-ink-body transition-all"
        >
          "imposter syndrome"
        </button>
        <button
          onClick={() => onSelectSample("how did I recover from burnout")}
          className="px-3 py-1.5 rounded-full border border-hairline bg-canvas-card hover:border-hairline-bright text-xs text-ink-body transition-all"
        >
          "creator burnout"
        </button>
        <button
          onClick={() => onSelectSample("monetizing podcast with brand deals")}
          className="px-3 py-1.5 rounded-full border border-hairline bg-canvas-card hover:border-hairline-bright text-xs text-ink-body transition-all"
        >
          "monetization & sponsorships"
        </button>
      </div>
    </div>
  );
};
