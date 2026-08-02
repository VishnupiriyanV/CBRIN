import React from 'react';
import { Search, X, Sparkles } from 'lucide-react';

interface SearchBarProps {
  query: string;
  setQuery: (q: string) => void;
  onSearch: (q: string) => void;
  isSearching: boolean;
}

const SAMPLE_QUERIES = [
  "when did I talk about imposter syndrome",
  "how did I recover from burnout",
  "monetizing podcast with brand deals",
  "storytelling retention hooks in YouTube videos",
  "studio audio setup and mic recommendations",
  "why newsletter growth matters for creators"
];

export const SearchBar: React.FC<SearchBarProps> = ({
  query,
  setQuery,
  onSearch,
  isSearching
}) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      onSearch(query);
    }
  };

  const handleSelectSample = (sample: string) => {
    setQuery(sample);
    onSearch(sample);
  };

  return (
    <div className="w-full max-w-3xl mx-auto space-y-4">
      {/* Eyebrow Label */}
      <div className="flex items-center justify-between">
        <span className="eyebrow-mono">SEARCH YOUR CONTENT LIBRARY</span>
        <span className="text-[11px] font-mono text-ink-mute">NATURAL LANGUAGE VECTOR SEARCH</span>
      </div>

      {/* Main Search Input Box */}
      <form onSubmit={handleSubmit} className="relative group">
        <div className="relative flex items-center">
          <div className="absolute left-4 text-ink-mute group-focus-within:text-accent-sunset transition-colors">
            <Search className="w-5 h-5" />
          </div>

          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a plain-language question (e.g., 'when did I discuss imposter syndrome')..."
            className="w-full pl-12 pr-28 py-4 bg-canvas-soft border border-hairline rounded-lg text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright transition-all text-sm sm:text-base"
          />

          {/* Clear button */}
          {query && (
            <button
              type="button"
              onClick={() => { setQuery(''); onSearch(''); }}
              className="absolute right-24 p-1 text-ink-mute hover:text-ink transition-colors"
              title="Clear search"
            >
              <X className="w-4 h-4" />
            </button>
          )}

          {/* Search Trigger Button */}
          <button
            type="submit"
            disabled={isSearching || !query.trim()}
            className="absolute right-2.5 px-4 py-2 bg-canvas-card border border-hairline-bright rounded-md text-xs font-medium text-ink hover:bg-canvas-hover hover:border-ink-mute disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5"
          >
            {isSearching ? (
              <span className="w-3.5 h-3.5 border-2 border-accent-sunset border-t-transparent rounded-full animate-spin"></span>
            ) : (
              <Sparkles className="w-3.5 h-3.5 text-accent-sunset" />
            )}
            <span>Search</span>
          </button>
        </div>
      </form>

      {/* Sample Query Suggestions */}
      <div className="space-y-2">
        <span className="text-[11px] text-ink-mute font-mono uppercase tracking-wider block">
          Try sample queries:
        </span>
        <div className="flex flex-wrap gap-2">
          {SAMPLE_QUERIES.map((sample, idx) => (
            <button
              key={idx}
              onClick={() => handleSelectSample(sample)}
              className="px-3 py-1 rounded-full border border-hairline bg-canvas-card hover:bg-canvas-soft hover:border-hairline-bright text-xs text-ink-body transition-all text-left truncate max-w-xs"
            >
              "{sample}"
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
