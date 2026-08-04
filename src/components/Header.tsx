import React, { useState, useRef, useEffect } from 'react';
import { Plus, Search, Sparkles, FileVideo, CheckCircle2, AlertTriangle, Bookmark, FileDown, Eye, ChevronDown, Activity, Wand2, Bot } from 'lucide-react';
import { CbrinLogo } from './CbrinLogo';
import { LibraryStats } from '../types';
import { exportLibraryJSON, exportLibraryZIP, exportHighlightsJSON } from '../services/api';

export type AppView = 'agent' | 'search' | 'engine' | 'studio';

interface HeaderProps {
  totalVideos: number;
  totalChunks: number;
  stats: LibraryStats | null;
  onOpenLibrary: () => void;
  onOpenIngest: () => void;
  onOpenHighlights: () => void;
  onOpenProgress: () => void;
  highlightCount: number;
  activeView?: AppView;
  onChangeView?: (view: AppView) => void;
}

export const Header: React.FC<HeaderProps> = ({
  totalVideos,
  totalChunks,
  stats,
  onOpenLibrary,
  onOpenIngest,
  onOpenHighlights,
  onOpenProgress,
  highlightCount,
  activeView = 'agent',
  onChangeView,
}) => {
  const isFullyIndexed = stats?.is_fully_indexed ?? (totalVideos > 0);
  const failedCount = stats?.failed_count ?? 0;
  const visualIndexedCount = stats?.visual_indexed_count ?? 0;
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setExportOpen(false);
      }
    };
    if (exportOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [exportOpen]);

  return (
    <header className="border-b border-hairline/80 sticky top-0 z-40 bg-canvas/85">
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-4">
        
        {/* Left: Active View Title & Telemetry */}
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-sm font-medium text-ink capitalize flex items-center gap-1.5 font-mono">
            {activeView === 'search' && <Search className="w-3.5 h-3.5 text-accent-sunset" />}
            {activeView === 'agent' && <Bot className="w-3.5 h-3.5 text-accent-sunset" />}
            {activeView === 'engine' && <Sparkles className="w-3.5 h-3.5 text-accent-sunset" />}
            {activeView === 'studio' && <Wand2 className="w-3.5 h-3.5 text-accent-sunset" />}
            <span>{activeView}</span>
          </span>

          {/* Library Telemetry Capsule */}
          {totalVideos > 0 && (
            <button
              onClick={onOpenProgress}
              className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded-full border border-hairline/80 bg-canvas-card/80 hover:bg-canvas-soft hover:border-hairline-bright transition-all text-[11px] font-mono group cursor-pointer overflow-hidden shrink"
              title="Click to view full indexing pipeline telemetry & progress"
            >
              {failedCount > 0 ? (
                <div className="flex items-center gap-1.5 text-red-400 shrink-0">
                  <AlertTriangle className="w-3 h-3 shrink-0" />
                  <span>{failedCount} FAILED</span>
                </div>
              ) : isFullyIndexed ? (
                <div className="flex items-center gap-1.5 text-emerald-400 shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0"></span>
                  <span className="shrink-0">100% INDEXED</span>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-amber-400 shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0"></span>
                  <span className="shrink-0">INDEXING</span>
                </div>
              )}

              <span className="text-hairline-bright shrink-0">•</span>

              <div className="flex items-center gap-1 text-ink-mute group-hover:text-ink shrink-0">
                <Sparkles className="w-3 h-3 text-accent-sunset shrink-0" />
                <span>{totalChunks} CHUNKS</span>
              </div>
            </button>
          )}
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 shrink-0">
          
          {/* Highlights / Bookmarks Button */}
          <button
            onClick={onOpenHighlights}
            className="relative p-2 sm:px-3 sm:py-1.5 rounded-full border border-hairline bg-canvas-card hover:bg-canvas-soft hover:border-hairline-bright text-xs font-medium text-ink transition-all flex items-center gap-1.5"
            title="View bookmarked moments"
          >
            <Bookmark className={`w-3.5 h-3.5 ${highlightCount > 0 ? 'text-accent-sunset fill-current' : 'text-ink-mute'}`} />
            <span className="hidden sm:inline">Saved</span>
            {highlightCount > 0 && (
              <span className="w-4 h-4 rounded-full bg-accent-sunset text-black text-[9px] font-mono font-bold flex items-center justify-center">
                {highlightCount}
              </span>
            )}
          </button>

          {/* Export Dropdown */}
          {totalVideos > 0 && (
            <div className="relative" ref={exportRef}>
              <button
                onClick={() => setExportOpen(!exportOpen)}
                className="px-3 py-1.5 rounded-full border border-hairline bg-canvas-card hover:bg-canvas-soft hover:border-hairline-bright text-xs font-medium text-ink transition-all flex items-center gap-1"
              >
                <FileDown className="w-3.5 h-3.5 text-ink-mute" />
                <span className="hidden sm:inline">Export</span>
                <ChevronDown className={`w-3 h-3 text-ink-mute transition-transform ${exportOpen ? 'rotate-180' : ''}`} />
              </button>

              {exportOpen && (
                <div className="absolute right-0 mt-2 w-48 bg-canvas-card border border-hairline-bright rounded-lg overflow-hidden z-50 animate-fade-in py-1">
                  <button
                    onClick={() => { exportLibraryJSON(); setExportOpen(false); }}
                    className="w-full px-4 py-2 text-left text-xs text-ink hover:bg-canvas-soft transition-colors flex items-center gap-2"
                  >
                    <FileDown className="w-3.5 h-3.5 text-ink-mute" />
                    Library (JSON)
                  </button>
                  <button
                    onClick={() => { exportLibraryZIP(); setExportOpen(false); }}
                    className="w-full px-4 py-2 text-left text-xs text-ink hover:bg-canvas-soft transition-colors flex items-center gap-2 border-t border-hairline/40"
                  >
                    <FileDown className="w-3.5 h-3.5 text-ink-mute" />
                    Library (ZIP)
                  </button>
                  {highlightCount > 0 && (
                    <button
                      onClick={() => { exportHighlightsJSON(); setExportOpen(false); }}
                      className="w-full px-4 py-2 text-left text-xs text-ink hover:bg-canvas-soft transition-colors flex items-center gap-2 border-t border-hairline/40"
                    >
                      <Bookmark className="w-3.5 h-3.5 text-accent-sunset" />
                      Highlights (JSON)
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Library Drawer Action */}
          <button
            onClick={onOpenLibrary}
            className="px-3 py-1.5 rounded-full border border-hairline bg-canvas-card hover:bg-canvas-soft hover:border-hairline-bright text-xs font-medium text-ink transition-all flex items-center gap-1.5"
          >
            <Search className="w-3.5 h-3.5 text-ink-mute" />
            <span className="hidden sm:inline">Library</span>
          </button>

          {/* Index New Action */}
          <button
            onClick={onOpenIngest}
            className="px-3.5 py-1.5 rounded-full border border-accent-sunset/40 bg-accent-sunset/10 hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-accent-sunset hover:text-black transition-all flex items-center gap-1.5"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Index New</span>
          </button>
        </div>
      </div>
    </header>
  );
};
