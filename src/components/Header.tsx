import React, { useState, useRef, useEffect } from 'react';
import { Database, Plus, Search, Sparkles, FileVideo, CheckCircle2, AlertTriangle, Bookmark, FileDown, Eye, ChevronDown } from 'lucide-react';
import { LibraryStats } from '../types';
import { exportLibraryJSON, exportLibraryZIP, exportHighlightsJSON } from '../services/api';

interface HeaderProps {
  totalVideos: number;
  totalChunks: number;
  stats: LibraryStats | null;
  onOpenLibrary: () => void;
  onOpenIngest: () => void;
  onOpenHighlights: () => void;
  highlightCount: number;
}

export const Header: React.FC<HeaderProps> = ({
  totalVideos,
  totalChunks,
  stats,
  onOpenLibrary,
  onOpenIngest,
  onOpenHighlights,
  highlightCount,
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
    <header className="border-b border-hairline bg-canvas sticky top-0 z-40 backdrop-blur-xl bg-canvas/90">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
        
        {/* Brand Header */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-accent-sunset" />
            <h1 className="text-base font-semibold tracking-tight text-ink">Vault</h1>
          </div>
          <span className="hidden sm:inline-block eyebrow-mono text-[9px] text-ink-mute px-2 py-0.5 rounded-full border border-hairline bg-canvas-soft">
            CREATORBRAIN // LAYER 1
          </span>
        </div>

        {/* Dynamic Indexing Status & Stats */}
        <div className="flex items-center gap-2 sm:gap-3">
          
          {/* Indexing Health Indicator */}
          {totalVideos > 0 && (
            <div className="hidden md:flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border border-hairline bg-canvas-soft text-[10px] font-mono">
              {failedCount > 0 ? (
                <div className="flex items-center gap-1 text-red-400">
                  <AlertTriangle className="w-3 h-3 text-red-400" />
                  <span>{failedCount} FAILED INGESTION{failedCount > 1 ? 'S' : ''}</span>
                </div>
              ) : isFullyIndexed ? (
                <div className="flex items-center gap-1 text-emerald-400">
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  <span>100% FULLY INDEXED</span>
                </div>
              ) : (
                <div className="flex items-center gap-1 text-amber-400">
                  <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
                  <span>INDEXING IN PROGRESS</span>
                </div>
              )}
            </div>
          )}

          {/* Counters */}
          <div className="hidden sm:flex items-center gap-3 text-[11px] font-mono text-ink-mute">
            <div className="flex items-center gap-1">
              <FileVideo className="w-3.5 h-3.5 text-ink-mute" />
              <span>{totalVideos} MEDIA</span>
            </div>
            <div className="flex items-center gap-1">
              <Sparkles className="w-3.5 h-3.5 text-accent-sunset" />
              <span>{totalChunks} CHUNKS</span>
            </div>
            {/* Visual index coverage */}
            {totalChunks > 0 && (
              <div className="flex items-center gap-1" title={`${visualIndexedCount} of ${totalChunks} chunks have visual (CLIP) embeddings`}>
                <Eye className="w-3.5 h-3.5 text-ink-mute" />
                <span>{visualIndexedCount}/{totalChunks} VISUAL</span>
              </div>
            )}
          </div>

          {/* Highlights Button */}
          <button
            onClick={onOpenHighlights}
            className="relative px-3 py-1.5 rounded-full border border-hairline bg-canvas-card hover:bg-canvas-soft hover:border-hairline-bright text-xs font-medium text-ink transition-all flex items-center gap-1.5"
          >
            <Bookmark className={`w-3.5 h-3.5 ${highlightCount > 0 ? 'text-accent-sunset fill-current' : 'text-ink-mute'}`} />
            <span className="hidden sm:inline">{highlightCount > 0 ? highlightCount : ''}</span>
            {highlightCount > 0 && (
              <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-accent-sunset text-black text-[9px] font-mono flex items-center justify-center">
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
                <div className="absolute right-0 mt-2 w-48 bg-canvas-card border border-hairline-bright rounded-lg shadow-2xl overflow-hidden z-50 animate-fade-in">
                  <button
                    onClick={() => { exportLibraryJSON(); setExportOpen(false); }}
                    className="w-full px-4 py-2.5 text-left text-xs text-ink hover:bg-canvas-soft transition-colors flex items-center gap-2"
                  >
                    <FileDown className="w-3.5 h-3.5 text-ink-mute" />
                    Library (JSON)
                  </button>
                  <button
                    onClick={() => { exportLibraryZIP(); setExportOpen(false); }}
                    className="w-full px-4 py-2.5 text-left text-xs text-ink hover:bg-canvas-soft transition-colors flex items-center gap-2 border-t border-hairline/40"
                  >
                    <FileDown className="w-3.5 h-3.5 text-ink-mute" />
                    Library (ZIP)
                  </button>
                  {highlightCount > 0 && (
                    <button
                      onClick={() => { exportHighlightsJSON(); setExportOpen(false); }}
                      className="w-full px-4 py-2.5 text-left text-xs text-ink hover:bg-canvas-soft transition-colors flex items-center gap-2 border-t border-hairline/40"
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
            className="px-3 py-1.5 rounded-full border border-hairline-bright bg-canvas-card hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-ink transition-all flex items-center gap-1.5"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Index New</span>
          </button>
        </div>
      </div>
    </header>
  );
};
