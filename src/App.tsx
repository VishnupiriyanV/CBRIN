import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Header, AppView } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { SearchBar } from './components/SearchBar';
import { ResultCard } from './components/ResultCard';
import { VideoPlayerModal } from './components/VideoPlayerModal';
import { LibraryModal } from './components/LibraryModal';
import { IndexingProgressModal } from './components/IndexingProgressModal';
import { EmptyState } from './components/EmptyState';
import { ClipStudio } from './components/engine/ClipStudio';
import { StudioView } from './components/studio/StudioView';
import { ChunkResult, VideoItem, SearchResponse, LibraryStats } from './types';
import { performSearch, fetchLibraryVideos, fetchLibraryStats, checkBackendHealth, fetchSuggestedQueries } from './services/api';
import { getQueryHistory, addToQueryHistory } from './services/queryHistory';
import { Plus, Video, WifiOff, FileDown, ChevronDown, Info, Filter } from 'lucide-react';

export const App: React.FC = () => {
  const [activeView, setActiveView] = useState<AppView>('search');
  const [query, setQuery] = useState('');
  const [searchMode, setSearchMode] = useState('spoken');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<ChunkResult | null>(null);
  const [isLibraryOpen, setIsLibraryOpen] = useState(false);
  const [isProgressOpen, setIsProgressOpen] = useState(false);
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [suggestedQueries, setSuggestedQueries] = useState<string[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [queryHistory, setQueryHistory] = useState<string[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [videoFilter, setVideoFilter] = useState<string>('all');
  const searchInputRef = useRef<HTMLInputElement>(null);
  const resultCardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    setQueryHistory(getQueryHistory());
  }, []);

  // Refresh library data & health check
  const refreshData = useCallback(async () => {
    const health = await checkBackendHealth();
    setBackendOnline(health.healthy);

    if (health.healthy) {
      try {
        const [libraryData, statsData, queriesData] = await Promise.all([
          fetchLibraryVideos(),
          fetchLibraryStats(),
          fetchSuggestedQueries()
        ]);
        setVideos(libraryData);
        setStats(statsData);
        setSuggestedQueries(queriesData);
      } catch (err) {
        console.error('Error fetching library data:', err);
      }
    }
  }, []);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  const handleSearch = async (searchQuery: string, mode: string = searchMode) => {
    if (!searchQuery || !searchQuery.trim()) {
      setSearchResponse(null);
      setHasSearched(false);
      setSearchError(null);
      return;
    }

    setIsSearching(true);
    setHasSearched(true);
    setSearchError(null);
    setSelectedIndex(-1);
    setVideoFilter('all');

    try {
      const response = await performSearch(searchQuery, mode);
      setSearchResponse(response);
      setQueryHistory(addToQueryHistory(searchQuery));
    } catch (err: any) {
      console.error("Search error:", err);
      setSearchError(err.message || 'Search failed. Is the Python backend server running?');
      setSearchResponse(null);
    } finally {
      setIsSearching(false);
    }
  };

  const handleVideoIngested = async () => {
    await refreshData();
    if (query.trim()) {
      try {
        const response = await performSearch(query, searchMode);
        setSearchResponse(response);
      } catch (err) {
        console.error("Re-search error:", err);
      }
    }
  };

  const totalChunks = stats?.total_chunks || videos.reduce((acc, v) => acc + v.chunk_count, 0);

  // Filter by video (IMPROVEMENT-PLAN.md 3.6) — client-side over the current result set,
  // no re-query needed.
  const resultVideoOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of searchResponse?.results || []) {
      if (!seen.has(r.video_id)) seen.set(r.video_id, r.video_title);
    }
    return Array.from(seen.entries());
  }, [searchResponse]);

  const filteredResults = useMemo(() => {
    const results = searchResponse?.results || [];
    return videoFilter === 'all' ? results : results.filter(r => r.video_id === videoFilter);
  }, [searchResponse, videoFilter]);

  // Keyboard nav (IMPROVEMENT-PLAN.md 3.6): '/' focuses search from anywhere; ArrowUp/Down
  // move through results and Enter opens the selected one, but only when focus isn't
  // already in a text field (so normal typing is never hijacked).
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const isTyping = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

      if (e.key === '/' && !isTyping) {
        e.preventDefault();
        searchInputRef.current?.focus();
        return;
      }

      if (isTyping || filteredResults.length === 0) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((i) => {
          const next = Math.min(i + 1, filteredResults.length - 1);
          resultCardRefs.current[filteredResults[next]?.id]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
          return next;
        });
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((i) => {
          const next = Math.max(i - 1, 0);
          resultCardRefs.current[filteredResults[next]?.id]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
          return next;
        });
      } else if (e.key === 'Enter' && selectedIndex >= 0 && selectedIndex < filteredResults.length) {
        setSelectedResult(filteredResults[selectedIndex]);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [filteredResults, selectedIndex]);

  return (
    <div className="min-h-screen bg-canvas text-ink flex flex-row antialiased selection:bg-accent-sunset selection:text-black">

      {/* Left Navigation Sidebar */}
      <Sidebar
        activeView={activeView}
        onChangeView={setActiveView}
        totalVideos={videos.length}
        totalChunks={totalChunks}
        stats={stats}
        backendOnline={backendOnline}
        onOpenLibrary={() => setIsLibraryOpen(true)}
        onOpenIngest={() => setIsLibraryOpen(true)}
        onOpenProgress={() => setIsProgressOpen(true)}
      />

      {/* Main Content Workspace Column */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-y-auto">

        {/* Backend Offline Notification Banner */}
        {backendOnline === false && (
          <div className="bg-canvas-card/60 border-b border-danger/40 px-4 py-2.5 flex items-center justify-center gap-2 text-xs font-mono text-danger animate-fade-in shrink-0">
            <WifiOff className="w-3.5 h-3.5" />
            <span>BACKEND OFFLINE — Start Python server: <code className="bg-canvas-card/40 px-1.5 py-0.5 rounded text-danger">python backend/main.py</code></span>
          </div>
        )}

        {/* Top Header Workspace Bar */}
        <Header
          totalVideos={videos.length}
          totalChunks={totalChunks}
          stats={stats}
          onOpenLibrary={() => setIsLibraryOpen(true)}
          onOpenIngest={() => setIsLibraryOpen(true)}
          onOpenProgress={() => setIsProgressOpen(true)}
          activeView={activeView}
          onChangeView={setActiveView}
        />

        {/* Main Container */}
        <main className={`flex-1 w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-10 ${activeView === 'engine' || activeView === 'studio' ? 'max-w-6xl' : 'max-w-5xl'}`}>

        {activeView === 'engine' ? (
          <ClipStudio videos={videos} backendOnline={backendOnline ?? false} />
        ) : activeView === 'studio' ? (
          <StudioView videos={videos} backendOnline={backendOnline ?? false} />
        ) : (
        <>
        {/* Hero Section */}
        <div className="text-center max-w-2xl mx-auto">
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-medium tracking-tight text-ink leading-tight">
            Search your spoken content library in plain language.
          </h1>
        </div>

        {/* Empty Library Onboarding Banner */}
        {videos.length === 0 ? (
          <div className="bg-canvas-soft/80 border border-hairline rounded-sm p-10 text-center max-w-2xl mx-auto space-y-4">
            <div className="w-12 h-12 rounded-sm border border-hairline-bright bg-canvas-card mx-auto flex items-center justify-center text-ink-body">
              <Video className="w-5 h-5" />
            </div>
            <div className="space-y-1">
              <span className="eyebrow-mono text-[9px] block text-ink-mute">Library empty</span>
              <h3 className="text-base sm:text-lg font-medium text-ink">
                No media files ingested yet
              </h3>
            </div>
            <p className="text-xs sm:text-sm text-ink-body max-w-md mx-auto leading-relaxed font-sans">
              Upload local video or audio files, select an entire folder, paste a YouTube URL, or import a backup to index transcript segments and start searching.
            </p>
            <button
              onClick={() => setIsLibraryOpen(true)}
              disabled={!backendOnline}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-sm border border-hairline-bright bg-canvas-card hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-ink transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Plus className="w-4 h-4" />
              <span>Ingest Local Files, Folder, YouTube URL or Import Backup</span>
            </button>
          </div>
        ) : (
          /* Search Bar Input Console */
          <SearchBar
            query={query}
            setQuery={setQuery}
            onSearch={handleSearch}
            isSearching={isSearching}
            disabled={!backendOnline}
            searchMode={searchMode}
            setSearchMode={setSearchMode}
            suggestedQueries={suggestedQueries}
            queryHistory={queryHistory}
            inputRef={searchInputRef}
          />
        )}

        {/* Search Error */}
        {searchError && (
          <div className="bg-canvas-card/40 border border-danger/30 rounded-sm p-4 text-xs text-danger font-mono text-center animate-fade-in">
            {searchError}
          </div>
        )}

        {/* Degraded-mode notice: the relevance reranker was unavailable server-side, so
            results below are unranked best-effort matches, not confidence-scored ones. */}
        {searchResponse?.degraded && (
          <div className="bg-canvas-card/30 border border-hairline-bright/30 rounded-sm p-3 text-xs text-ink-body font-mono text-center animate-fade-in">
            {searchResponse.message || 'Relevance reranker unavailable — showing unranked best-effort matches.'}
          </div>
        )}

        {/* Results Section (only displayed when a search has been executed) */}
        {hasSearched && (
          <div className="space-y-6 pt-4 border-t border-hairline animate-fade-in">

            {/* Meta Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="eyebrow-mono">Search results</span>
                {searchResponse && (
                  <span className="text-[10px] font-mono px-2.5 py-0.5 rounded-sm border border-hairline bg-canvas-soft text-ink-body">
                    {filteredResults.length}{videoFilter !== 'all' ? ` / ${searchResponse.results.length}` : ''} moments found
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                {/* Filter by video (IMPROVEMENT-PLAN.md 3.6) */}
                {resultVideoOptions.length > 1 && (
                  <div className="relative flex items-center gap-1 px-2 py-1 rounded-sm border border-hairline bg-canvas-soft text-[10px] font-mono text-ink-mute">
                    <Filter className="w-3 h-3 text-ink-body shrink-0" />
                    <select
                      value={videoFilter}
                      onChange={(e) => setVideoFilter(e.target.value)}
                      className="bg-transparent outline-none text-ink-mute hover:text-ink max-w-[10rem] truncate"
                    >
                      <option value="all">All videos</option>
                      {resultVideoOptions.map(([vid, title]) => (
                        <option key={vid} value={vid}>{title}</option>
                      ))}
                    </select>
                  </div>
                )}

                {/* Telemetry info toggle (Replaces full-weight header text) */}
                {searchResponse && (
                  <div className="relative group/telemetry">
                    <button className="px-2.5 py-1 rounded-sm border border-hairline bg-canvas-soft hover:border-hairline-bright text-[10px] font-mono text-ink-mute hover:text-ink transition-all flex items-center gap-1">
                      <Info className="w-3 h-3 text-ink-body" />
                      <span>Telemetry</span>
                    </button>
                    <div className="absolute right-0 top-full mt-1.5 hidden group-hover/telemetry:block bg-canvas-card border border-hairline-bright px-3 py-1.5 rounded-sm text-[10px] font-mono text-ink-mute whitespace-nowrap z-50 animate-fade-in">
                      SCANNED {searchResponse.total_chunks_scanned} CHUNKS IN {searchResponse.execution_time_ms}ms // {searchResponse.search_mode?.toUpperCase()} MODE
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Results List */}
            {searchResponse && searchResponse.results.length > 0 ? (
              <div className="space-y-4">
                {filteredResults.map((result, idx) => (
                  <div
                    key={result.id}
                    ref={(el) => { resultCardRefs.current[result.id] = el; }}
                    className={idx === selectedIndex ? 'rounded-sm ring-2 ring-accent-sunset/60' : ''}
                  >
                    <ResultCard
                      result={result}
                      searchQuery={query}
                      onJumpToMoment={(res) => setSelectedResult(res)}
                      searchMode={searchResponse?.search_mode || searchMode}
                    />
                  </div>
                ))}
              </div>
            ) : !isSearching ? (
              /* Empty State */
              <EmptyState
                query={query}
                nearMisses={searchResponse?.near_misses}
                message={searchResponse?.message}
                onJumpToMoment={(res) => setSelectedResult(res)}
                searchMode={searchResponse?.search_mode || searchMode}
              />
            ) : null}
          </div>
        )}

        {/* Initial Library Snapshot Cards (displayed before searching) */}
        {!hasSearched && videos.length > 0 && (
          <div className="space-y-4 pt-6 border-t border-hairline/60">
            <div className="flex items-center justify-between">
              <span className="eyebrow-mono">Indexed content in your CBRIN</span>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setIsProgressOpen(true)}
                  className="text-[11px] font-mono text-ink-mute hover:text-ink flex items-center gap-1"
                >
                  <span>Telemetry & pipeline</span> →
                </button>
                <button
                  onClick={() => setIsLibraryOpen(true)}
                  className="text-[11px] font-mono text-ink-body hover:underline"
                >
                  View all ({videos.length}) →
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {videos.slice(0, 3).map((vid) => (
                <div
                  key={vid.id}
                  onClick={() => setIsLibraryOpen(true)}
                  className="bg-[#121215] border border-hairline hover:border-hairline-bright rounded-sm p-4 space-y-3 cursor-pointer group transition-all"
                >
                  <div className="relative aspect-video rounded-sm overflow-hidden border border-hairline/60 bg-black/60">
                    <img
                      src={vid.thumbnail_url || 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><rect fill="%23191919" width="160" height="90"/><text x="80" y="50" fill="%237d8187" font-size="12" text-anchor="middle">No Thumbnail</text></svg>'}
                      alt={vid.title}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    />
                    <div className="absolute bottom-1.5 right-1.5 px-2 py-0.5 bg-black/80 rounded text-[10px] font-mono text-white">
                      {vid.duration_formatted}
                    </div>
                  </div>

                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-[10px] text-ink-body">
                      <span className="truncate">{vid.channel}</span>
                      <span className="font-mono text-ink-mute shrink-0">{vid.chunk_count} chunks</span>
                    </div>
                    <h4 className="text-xs font-semibold text-ink line-clamp-1 group-hover:text-ink-body transition-colors">
                      {vid.title}
                    </h4>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        </>
        )}
      </main>

      {/* Minimal Footer */}
      <footer className="border-t border-hairline py-6 bg-canvas text-center text-xs font-mono text-ink-mute">
        <p>© CBRIN</p>
      </footer>

      {/* Jump to Moment Video Modal */}
      <VideoPlayerModal
        result={selectedResult}
        onClose={() => setSelectedResult(null)}
      />

      {/* Library Drawer Modal */}
      <LibraryModal
        isOpen={isLibraryOpen}
        onClose={() => setIsLibraryOpen(false)}
        videos={videos}
        onVideoIngested={handleVideoIngested}
        backendOnline={backendOnline ?? false}
      />


      {/* Indexing Progress Telemetry Modal */}
      <IndexingProgressModal
        isOpen={isProgressOpen}
        onClose={() => setIsProgressOpen(false)}
        videos={videos}
        stats={stats}
        backendOnline={backendOnline ?? false}
        onRefresh={refreshData}
      />
      </div>
    </div>
  );
};

export default App;
