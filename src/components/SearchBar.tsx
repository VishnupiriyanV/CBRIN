import React from 'react';
import { Search, X, Sparkles, SlidersHorizontal, History } from 'lucide-react';

interface SearchBarProps {
  query: string;
  setQuery: (q: string) => void;
  onSearch: (q: string, mode?: string) => void;
  isSearching: boolean;
  disabled?: boolean;
  searchMode: string;
  setSearchMode: (mode: string) => void;
  suggestedQueries: string[];
  queryHistory?: string[];
  inputRef?: React.RefObject<HTMLInputElement>;
}

// Two honest modes (IMPROVEMENT-PLAN.md 2.4). The old 'hybrid' / 'questions' / 'topics'
// all ran identical backend code and gave no actual mode-dependent behavior — 'spoken' and
// 'visual_scenes' are the only two search modes that are genuinely different pipelines.
export const SEARCH_MODES = [
  { id: 'spoken', label: 'SPOKEN' },
  { id: 'visual_scenes', label: 'ON-SCREEN (CLIP)' },
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
  queryHistory = [],
  inputRef,
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
    <div className="w-full max-w-4xl mx-auto">
      {/* Outer Container Card (Doppelrand Architecture) */}
      <div className="bg-[#121215]/90 border border-hairline/90 rounded-lg p-5 sm:p-7 space-y-5">
        
        {/* Top Header Row: Eyebrow + Mode Tabs */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="eyebrow-mono text-[10px]">SEARCH YOUR CONTENT</span>
          </div>

          {/* Search Mode Segmented Pills */}
          <div className="flex items-center gap-1 bg-canvas border border-hairline p-1 rounded-lg overflow-x-auto scrollbar-none">
            <div className="flex items-center gap-1 px-2 text-[10px] font-mono text-ink-mute shrink-0">
              <SlidersHorizontal className="w-3 h-3 text-accent-sunset" />
              <span className="hidden sm:inline">MODE:</span>
            </div>
            {SEARCH_MODES.map((mode) => (
              <button
                key={mode.id}
                type="button"
                onClick={() => handleModeChange(mode.id)}
                disabled={disabled}
                className={`px-3 py-1 rounded-lg text-[10px] font-mono whitespace-nowrap transition-all ${
                  searchMode === mode.id
                    ? 'bg-canvas-card text-accent-sunset border border-accent-sunset/50'
                    : 'text-ink-mute hover:text-ink hover:bg-canvas-soft'
                } disabled:opacity-40`}
              >
                {mode.label}
              </button>
            ))}
          </div>
        </div>

        {/* Input Bar Form */}
        <form onSubmit={handleSubmit} className="relative group">
          <div className="relative flex items-center">
            <div className="absolute left-4 text-ink-mute group-focus-within:text-accent-sunset transition-colors pointer-events-none z-10">
              <Search className="w-4.5 h-4.5 sm:w-5 sm:h-5" />
            </div>

            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type a topic, spoken phrase, or natural question... (press / to focus)"
              disabled={disabled}
              className="w-full pl-11 sm:pl-12 pr-28 sm:pr-32 py-3.5 sm:py-4 bg-canvas border border-hairline rounded-lg text-ink placeholder:text-ink-mute/70 focus:outline-none focus:border-hairline-bright focus:ring-1 focus:ring-accent-sunset/30 transition-all text-sm sm:text-base disabled:opacity-40 font-sans"
            />

            {/* Clear Button */}
            {query && (
              <button
                type="button"
                onClick={() => { setQuery(''); onSearch('', searchMode); }}
                className="absolute right-24 sm:right-28 p-1.5 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-full transition-colors z-10"
                title="Clear search"
              >
                <X className="w-4 h-4" />
              </button>
            )}

            {/* Search Action Button */}
            <button
              type="submit"
              disabled={isSearching || !query.trim() || disabled}
              className="absolute right-2 sm:right-2.5 px-3.5 sm:px-4 py-2 sm:py-2.5 rounded-md border border-accent-sunset/40 bg-accent-sunset/15 hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-semibold text-accent-sunset disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5 z-10 shrink-0"
            >
              {isSearching ? (
                <span className="w-3.5 h-3.5 border-2 border-accent-sunset border-t-transparent rounded-full animate-spin"></span>
              ) : (
                <Sparkles className="w-3.5 h-3.5" />
              )}
              <span>Search</span>
            </button>
          </div>
        </form>

        {/* Recent Searches (IMPROVEMENT-PLAN.md 3.6) */}
        {queryHistory.length > 0 && (
          <div className="space-y-2 pt-1">
            <span className="text-[10px] text-ink-mute font-mono uppercase tracking-wider flex items-center gap-1">
              <History className="w-3 h-3" />
              Recent searches:
            </span>
            <div className="flex flex-wrap gap-2">
              {queryHistory.map((sample, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSelectSample(sample)}
                  disabled={disabled}
                  className="px-3 py-1.5 rounded-full border border-hairline/60 bg-canvas/50 hover:bg-canvas-soft hover:border-hairline-bright text-xs text-ink-mute hover:text-ink transition-all text-left truncate max-w-xs disabled:opacity-40 font-sans"
                >
                  {sample}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Dynamic Suggested Queries */}
        {suggestedQueries.length > 0 && (
          <div className="space-y-2 pt-1">
            <span className="text-[10px] text-ink-mute font-mono uppercase tracking-wider block">
              Suggested queries from your library:
            </span>
            <div className="flex flex-wrap gap-2">
              {suggestedQueries.map((sample, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSelectSample(sample)}
                  disabled={disabled}
                  className="px-3 py-1.5 rounded-full border border-hairline/80 bg-canvas/70 hover:bg-canvas-soft hover:border-accent-sunset/40 hover:text-accent-sunset text-xs text-ink-body transition-all text-left truncate max-w-xs disabled:opacity-40 font-sans"
                >
                  "{sample}"
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
