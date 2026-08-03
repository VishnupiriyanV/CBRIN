import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { SearchBar } from './components/SearchBar';
import { ResultCard } from './components/ResultCard';
import { VideoPlayerModal } from './components/VideoPlayerModal';
import { LibraryModal } from './components/LibraryModal';
import { HighlightsPanel } from './components/HighlightsPanel';
import { EmptyState } from './components/EmptyState';
import { ChunkResult, VideoItem, SearchResponse, LibraryStats, Highlight } from './types';
import { performSearch, fetchLibraryVideos, fetchLibraryStats, checkBackendHealth, fetchSuggestedQueries, addHighlight, removeHighlight, fetchHighlights, exportSearchJSON, exportSearchCSV } from './services/api';
import { Zap, Plus, Video, WifiOff, FileDown, ChevronDown } from 'lucide-react';

export const App: React.FC = () => {
  const [query, setQuery] = useState('');
  const [searchMode, setSearchMode] = useState('hybrid');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<ChunkResult | null>(null);
  const [isLibraryOpen, setIsLibraryOpen] = useState(false);
  const [isHighlightsOpen, setIsHighlightsOpen] = useState(false);
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [suggestedQueries, setSuggestedQueries] = useState<string[]>([]);
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [exportResultsOpen, setExportResultsOpen] = useState(false);

  // Refresh library data & health check
  const refreshData = useCallback(async () => {
    const health = await checkBackendHealth();
    setBackendOnline(health.healthy);

    if (health.healthy) {
      try {
        const [libraryData, statsData, queriesData, highlightsData] = await Promise.all([
          fetchLibraryVideos(),
          fetchLibraryStats(),
          fetchSuggestedQueries(),
          fetchHighlights()
        ]);
        setVideos(libraryData);
        setStats(statsData);
        setSuggestedQueries(queriesData);
        setHighlights(highlightsData);
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

    try {
      const response = await performSearch(searchQuery, mode);
      setSearchResponse(response);
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

  const handleToggleHighlight = async (result: ChunkResult) => {
    try {
      if (result.is_highlighted) {
        await removeHighlight(result.id);
      } else {
        await addHighlight(result.id, "");
      }
      // Refresh highlights
      const updated = await fetchHighlights();
      setHighlights(updated);

      // Update search results to reflect highlight status change
      if (searchResponse) {
        setSearchResponse({
          ...searchResponse,
          results: searchResponse.results.map(r =>
            r.id === result.id ? { ...r, is_highlighted: !r.is_highlighted } : r
          )
        });
      }
    } catch (err) {
      console.error("Highlight toggle error:", err);
    }
  };

  const handleRemoveHighlight = async (chunkId: string) => {
    try {
      await removeHighlight(chunkId);
      const updated = await fetchHighlights();
      setHighlights(updated);
      // Also update search results if visible
      if (searchResponse) {
        setSearchResponse({
          ...searchResponse,
          results: searchResponse.results.map(r =>
            r.id === chunkId ? { ...r, is_highlighted: false } : r
          )
        });
      }
    } catch (err) {
      console.error("Remove highlight error:", err);
    }
  };

  const totalChunks = stats?.total_chunks || videos.reduce((acc, v) => acc + v.chunk_count, 0);

  return (
    <div className="min-h-screen bg-canvas text-ink flex flex-col antialiased selection:bg-accent-sunset selection:text-black">

      {/* Backend Offline Notification Banner */}
      {backendOnline === false && (
        <div className="bg-red-950/60 border-b border-red-800/40 px-4 py-2.5 flex items-center justify-center gap-2 text-xs font-mono text-red-300 animate-fade-in">
          <WifiOff className="w-3.5 h-3.5" />
          <span>BACKEND OFFLINE — Start Python server: <code className="bg-red-900/40 px-1.5 py-0.5 rounded text-red-200">python backend/main.py</code></span>
        </div>
      )}

      {/* Top Bar */}
      <Header
        totalVideos={videos.length}
        totalChunks={totalChunks}
        stats={stats}
        onOpenLibrary={() => setIsLibraryOpen(true)}
        onOpenIngest={() => setIsLibraryOpen(true)}
        onOpenHighlights={() => setIsHighlightsOpen(true)}
        highlightCount={highlights.length}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-10">

        {/* Hero Section */}
        <div className="text-center space-y-3 max-w-2xl mx-auto">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-hairline bg-canvas-card text-[11px] font-mono text-ink-mute">
            <Zap className="w-3 h-3 text-accent-sunset" />
            <span>MULTIMODAL SEMANTIC & VISUAL SEARCH (WHISPER + CLIP)</span>
          </div>
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-medium tracking-tight text-ink leading-tight">
            Search your spoken content library in plain language.
          </h1>
          <p className="text-sm sm:text-base text-ink-body font-sans">
            Search what was spoken or shown on screen. Vault indexes your audio/video back-catalog and jumps to the exact moment.
          </p>
        </div>

        {/* Empty Library Onboarding Banner */}
        {videos.length === 0 ? (
          <div className="bg-canvas-soft border border-hairline rounded-lg p-10 text-center max-w-2xl mx-auto space-y-4">
            <div className="w-12 h-12 rounded-full border border-hairline-bright bg-canvas-card mx-auto flex items-center justify-center text-accent-sunset">
              <Video className="w-5 h-5" />
            </div>
            <div className="space-y-1">
              <span className="eyebrow-mono text-[9px] block text-ink-mute">LIBRARY EMPTY</span>
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
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full border border-hairline-bright bg-canvas-card hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-ink transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Plus className="w-4 h-4" />
              <span>Ingest Local Files, Folder, YouTube URL or Import Backup</span>
            </button>
          </div>
        ) : (
          /* Search Bar Input */
          <SearchBar
            query={query}
            setQuery={setQuery}
            onSearch={handleSearch}
            isSearching={isSearching}
            disabled={!backendOnline}
            searchMode={searchMode}
            setSearchMode={setSearchMode}
            suggestedQueries={suggestedQueries}
          />
        )}

        {/* Search Error */}
        {searchError && (
          <div className="bg-red-950/40 border border-red-800/30 rounded-lg p-4 text-xs text-red-300 font-mono text-center animate-fade-in">
            {searchError}
          </div>
        )}

        {/* Results Section */}
        {videos.length > 0 && (
          <div className="space-y-6 pt-4 border-t border-hairline">

            {/* Meta Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="eyebrow-mono">RESULTS</span>
                {searchResponse && (
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full border border-hairline bg-canvas-soft text-ink-mute">
                    {searchResponse.results.length} MOMENTS FOUND
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                {/* Export Search Results */}
                {searchResponse && searchResponse.results.length > 0 && (
                  <div className="relative">
                    <button
                      onClick={() => setExportResultsOpen(!exportResultsOpen)}
                      className="px-2.5 py-1 rounded-full border border-hairline bg-canvas-soft hover:border-hairline-bright text-[10px] font-mono text-ink-mute transition-all flex items-center gap-1"
                    >
                      <FileDown className="w-3 h-3" />
                      <span>EXPORT</span>
                      <ChevronDown className={`w-2.5 h-2.5 transition-transform ${exportResultsOpen ? 'rotate-180' : ''}`} />
                    </button>
                    {exportResultsOpen && (
                      <div className="absolute right-0 mt-1 w-36 bg-canvas-card border border-hairline-bright rounded-lg shadow-2xl overflow-hidden z-50 animate-fade-in">
                        <button
                          onClick={() => { exportSearchJSON(query, searchMode); setExportResultsOpen(false); }}
                          className="w-full px-3 py-2 text-left text-[11px] text-ink hover:bg-canvas-soft transition-colors"
                        >
                          Export as JSON
                        </button>
                        <button
                          onClick={() => { exportSearchCSV(query, searchMode); setExportResultsOpen(false); }}
                          className="w-full px-3 py-2 text-left text-[11px] text-ink hover:bg-canvas-soft transition-colors border-t border-hairline/40"
                        >
                          Export as CSV
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {searchResponse && (
                  <span className="text-[11px] font-mono text-ink-mute hidden sm:inline uppercase">
                    SCANNED {searchResponse.total_chunks_scanned} CHUNKS IN {searchResponse.execution_time_ms}ms // {searchResponse.search_mode}
                  </span>
                )}
              </div>
            </div>

            {/* Results List */}
            {searchResponse && searchResponse.results.length > 0 ? (
              <div className="space-y-4">
                {searchResponse.results.map((result) => (
                  <ResultCard
                    key={result.id}
                    result={result}
                    searchQuery={query}
                    onJumpToMoment={(res) => setSelectedResult(res)}
                    onToggleHighlight={handleToggleHighlight}
                  />
                ))}
              </div>
            ) : hasSearched && !isSearching ? (
              /* Empty State */
              <EmptyState query={query} />
            ) : null}
          </div>
        )}
      </main>

      {/* Minimal Footer */}
      <footer className="border-t border-hairline py-8 bg-canvas text-center text-xs font-mono text-ink-mute space-y-2">
        <p>VAULT // CREATORBRAIN LAYER 1 MVP</p>
        <p className="text-[10px]">ULTRA-MINIMALIST DESIGN // OLED BLACK // HAIRLINE BORDERS // ZERO EMOJIS</p>
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

      {/* Highlights Panel */}
      <HighlightsPanel
        isOpen={isHighlightsOpen}
        onClose={() => setIsHighlightsOpen(false)}
        highlights={highlights}
        onJumpToMoment={(h) => {
          setIsHighlightsOpen(false);
          setSelectedResult(h as any);
        }}
        onRemoveHighlight={handleRemoveHighlight}
      />
    </div>
  );
};

export default App;
