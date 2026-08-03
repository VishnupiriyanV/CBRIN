import React from 'react';
import { Search, X, Sparkles, SlidersHorizontal } from 'lucide-react';

interface SearchBarProps {
  query: string;
  setQuery: (q: string) => void;
  onSearch: (q: string, mode?: string) => void;
  isSearching: boolean;
  disabled?: boolean;
  searchMode: string;
  setSearchMode: (mode: string) => void;
  suggestedQueries: string[];
}

export const SEARCH_MODES = [
  { id: 'hybrid', label: 'HYBRID (TEXT + VISUAL)' },
  { id: 'questions', label: 'QUESTIONS ANSWERED' },
  { id: 'visual_scenes', label: 'VISUAL SCENES (CLIP)' },
  { id: 'topics', label: 'TOPICS & SUMMARIES' },
];

export const SearchBar: React.FC<SearchBarProps> = ({
  query,
  setQuery,
  onSearch,
  isSearching,
  disabled,
  searchMode,
  setSearchMode,
  suggestedQueries,
}) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim() && !disabled) {
      onSearch(query, searchMode);
    }
  };

  const handleSelectSample = (sample: string) => {
    if (!disabled) {
      setQuery(sample);
      onSearch(sample, searchMode);
    }
  };

  const handleModeChange = (modeId: string) => {
    setSearchMode(modeId);
    if (query.trim() && !disabled) {
      onSearch(query, modeId);
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto space-y-4">
      {/* Eyebrow and Search Mode Selector */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <span className="eyebrow-mono">SEARCH YOUR CONTENT LIBRARY</span>
        
        {/* Search Mode Pills */}
        <div className="flex flex-wrap items-center gap-1.5">
          <div className="flex items-center gap-1 text-[10px] font-mono text-ink-mute mr-1">
            <SlidersHorizontal className="w-3 h-3" />
            <span>MODE:</span>
          </div>
          {SEARCH_MODES.map((mode) => (
            <button
              key={mode.id}
              type="button"
              onClick={() => handleModeChange(mode.id)}
              disabled={disabled}
              className={`px-2.5 py-1 rounded-full text-[10px] font-mono transition-all border ${
                searchMode === mode.id
                  ? 'bg-canvas-card text-accent-sunset border-accent-sunset'
                  : 'bg-canvas-soft text-ink-mute border-hairline hover:text-ink hover:border-hairline-bright'
              } disabled:opacity-40`}
            >
              {mode.label}
            </button>
          ))}
        </div>
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
            placeholder="Type a plain-language topic or question..."
            disabled={disabled}
            className="w-full pl-12 pr-28 py-4 bg-canvas-soft border border-hairline rounded-lg text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright transition-all text-sm sm:text-base disabled:opacity-40"
          />

          {/* Clear Button */}
          {query && (
            <button
              type="button"
              onClick={() => { setQuery(''); onSearch('', searchMode); }}
              className="absolute right-24 p-1 text-ink-mute hover:text-ink transition-colors"
              title="Clear search"
            >
              <X className="w-4 h-4" />
            </button>
          )}

          {/* Search Action Button */}
          <button
            type="submit"
            disabled={isSearching || !query.trim() || disabled}
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

      {/* Dynamic Suggested Queries from Indexed Library (Zero static mock samples) */}
      {suggestedQueries.length > 0 && (
        <div className="space-y-2">
          <span className="text-[10px] text-ink-mute font-mono uppercase tracking-wider block">
            Suggested queries from your library:
          </span>
          <div className="flex flex-wrap gap-2">
            {suggestedQueries.map((sample, idx) => (
              <button
                key={idx}
                onClick={() => handleSelectSample(sample)}
                disabled={disabled}
                className="px-3 py-1 rounded-full border border-hairline bg-canvas-card hover:bg-canvas-soft hover:border-hairline-bright text-xs text-ink-body transition-all text-left truncate max-w-xs disabled:opacity-40 font-sans"
              >
                "{sample}"
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
