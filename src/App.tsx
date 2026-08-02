import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { SearchBar } from './components/SearchBar';
import { ResultCard } from './components/ResultCard';
import { VideoPlayerModal } from './components/VideoPlayerModal';
import { LibraryModal } from './components/LibraryModal';
import { EmptyState } from './components/EmptyState';
import { ChunkResult, VideoItem, SearchResponse } from './types';
import { INITIAL_VIDEOS, INITIAL_CHUNKS } from './services/mockData';
import { performSearch } from './services/api';
import { Sparkles, Layers, Sliders, ShieldCheck, Zap } from 'lucide-react';

export const App: React.FC = () => {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);
  const [selectedResult, setSelectedResult] = useState<ChunkResult | null>(null);
  const [isLibraryOpen, setIsLibraryOpen] = useState(false);
  const [videos, setVideos] = useState<VideoItem[]>(INITIAL_VIDEOS);
  const [chunks, setChunks] = useState<ChunkResult[]>(INITIAL_CHUNKS);
  const [hasSearched, setHasSearched] = useState(false);

  // Default initial search on load to showcase the core wow factor immediately!
  useEffect(() => {
    handleSearch("when did I talk about imposter syndrome");
  }, []);

  const handleSearch = async (searchQuery: string) => {
    if (!searchQuery || !searchQuery.trim()) {
      setSearchResponse(null);
      setHasSearched(false);
      return;
    }

    setIsSearching(true);
    setHasSearched(true);

    try {
      const response = await performSearch(searchQuery, chunks);
      setSearchResponse(response);
    } catch (err) {
      console.error("Search error:", err);
    } finally {
      setIsSearching(false);
    }
  };

  const handleVideoIngested = (newVideo: VideoItem) => {
    setVideos(prev => [newVideo, ...prev]);
    // Perform re-search if query exists
    if (query) {
      handleSearch(query);
    }
  };

  const totalChunks = videos.reduce((acc, v) => acc + v.chunk_count, 0);

  return (
    <div className="min-h-screen bg-canvas text-ink flex flex-col antialiased selection:bg-accent-sunset selection:text-black">
      
      {/* Top Header */}
      <Header
        totalVideos={videos.length}
        totalChunks={totalChunks}
        onOpenLibrary={() => setIsLibraryOpen(true)}
        onOpenIngest={() => setIsLibraryOpen(true)}
      />

      {/* Main Content Body */}
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-10">
        
        {/* Hero Banner Section */}
        <div className="text-center space-y-3 max-w-2xl mx-auto">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-hairline bg-canvas-card text-[11px] font-mono text-ink-mute">
            <Zap className="w-3 h-3 text-accent-sunset" />
            <span>SEMANTIC EMBEDDING VS KEYWORD SEARCH</span>
          </div>
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-medium tracking-tight text-ink leading-tight">
            Search your spoken content library in plain language.
          </h1>
          <p className="text-sm sm:text-base text-ink-body font-sans">
            Type any topic or concept you remember discussing. Vault indexes your audio/video back-catalog and jumps to the exact moment.
          </p>
        </div>

        {/* Search Bar Input & Samples */}
        <SearchBar
          query={query}
          setQuery={setQuery}
          onSearch={handleSearch}
          isSearching={isSearching}
        />

        {/* Results Section */}
        <div className="space-y-6 pt-4 border-t border-hairline">
          
          {/* Eyebrow and Results Meta */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="eyebrow-mono">RESULTS</span>
              {searchResponse && (
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full border border-hairline bg-canvas-soft text-ink-mute">
                  {searchResponse.results.length} MOMENTS FOUND
                </span>
              )}
            </div>

            {searchResponse && (
              <span className="text-[11px] font-mono text-ink-mute hidden sm:inline">
                SCANNED {searchResponse.total_chunks_scanned} CHUNKS IN {searchResponse.execution_time_ms}ms
              </span>
            )}
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
                />
              ))}
            </div>
          ) : hasSearched && !isSearching ? (
            /* Empty State */
            <EmptyState
              query={query}
              onSelectSample={(sample) => {
                setQuery(sample);
                handleSearch(sample);
              }}
            />
          ) : null}
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-hairline py-8 bg-canvas text-center text-xs font-mono text-ink-mute space-y-2">
        <p>VAULT // CREATORBRAIN LAYER 1 MVP</p>
        <p className="text-[10px]">DESIGNED WITH xAI SPECIFICATIONS // NO DROP SHADOWS • OLED BLACK • HAIRLINE BORDERS</p>
      </footer>

      {/* Jump to Moment Video Modal */}
      <VideoPlayerModal
        result={selectedResult}
        onClose={() => setSelectedResult(null)}
      />

      {/* Library Drawer/Modal */}
      <LibraryModal
        isOpen={isLibraryOpen}
        onClose={() => setIsLibraryOpen(false)}
        videos={videos}
        onVideoIngested={handleVideoIngested}
      />
    </div>
  );
};

export default App;
