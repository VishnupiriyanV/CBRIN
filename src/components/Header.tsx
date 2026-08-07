import React, { useState, useRef, useEffect } from 'react';
import { Plus, Search, Sparkles, FileVideo, CheckCircle2, AlertTriangle, Eye, ChevronDown, Activity, Wand2 } from 'lucide-react';
import { CbrinLogo } from './CbrinLogo';
import { LibraryStats } from '../types';

export type AppView = 'search' | 'engine' | 'studio';

interface HeaderProps {
  totalVideos: number;
  totalChunks: number;
  stats: LibraryStats | null;
  onOpenLibrary: () => void;
  onOpenIngest: () => void;
  onOpenProgress: () => void;
  activeView?: AppView;
  onChangeView?: (view: AppView) => void;
}

export const Header: React.FC<HeaderProps> = ({
  totalVideos,
  totalChunks,
  stats,
  onOpenLibrary,
  onOpenIngest,
  onOpenProgress,
  activeView = 'search',
  onChangeView,
}) => {
  const isFullyIndexed = stats?.is_fully_indexed ?? (totalVideos > 0);
  const failedCount = stats?.failed_count ?? 0;
  const visualIndexedCount = stats?.visual_indexed_count ?? 0;

  return (
    <header className="border-b border-hairline/80 sticky top-0 z-40 bg-canvas/85">
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-4">
        
        {/* Left: Active View Title & Telemetry */}
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-sm font-medium text-ink capitalize flex items-center gap-1.5 font-mono">
            {activeView === 'search' && <Search className="w-3.5 h-3.5 text-ink-body" />}
            {activeView === 'engine' && <Sparkles className="w-3.5 h-3.5 text-ink-body" />}
            {activeView === 'studio' && <Wand2 className="w-3.5 h-3.5 text-ink-body" />}
            <span>{activeView}</span>
          </span>

          {/* Library Telemetry Capsule */}
          {totalVideos > 0 && (
            <button
              onClick={onOpenProgress}
              className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded-sm border border-hairline/80 bg-canvas-card/80 hover:bg-canvas-soft hover:border-hairline-bright transition-all text-[11px] font-mono group cursor-pointer overflow-hidden shrink"
              title="Click to view full indexing pipeline telemetry & progress"
            >
              {failedCount > 0 ? (
                <div className="flex items-center gap-1.5 text-danger shrink-0">
                  <AlertTriangle className="w-3 h-3 shrink-0" />
                  <span>{failedCount} FAILED</span>
                </div>
              ) : isFullyIndexed ? (
                <div className="flex items-center gap-1.5 text-ink shrink-0">
                  <span className="w-1.5 h-1.5 rounded-sm bg-ink shrink-0"></span>
                  <span className="shrink-0">100% INDEXED</span>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-ink-body shrink-0">
                  <span className="w-1.5 h-1.5 rounded-sm bg-ink-body shrink-0"></span>
                  <span className="shrink-0">Indexing</span>
                </div>
              )}

              <span className="text-hairline-bright shrink-0">•</span>

              <div className="flex items-center gap-1 text-ink-mute group-hover:text-ink shrink-0">
                <Sparkles className="w-3 h-3 text-ink-body shrink-0" />
                <span>{totalChunks} CHUNKS</span>
              </div>
            </button>
          )}
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 shrink-0">
          
          {/* Library Drawer Action */}
          <button
            onClick={onOpenLibrary}
            className="px-3 py-1.5 rounded-sm border border-hairline bg-canvas-card hover:bg-canvas-soft hover:border-hairline-bright text-xs font-medium text-ink transition-all flex items-center gap-1.5"
          >
            <Search className="w-3.5 h-3.5 text-ink-mute" />
            <span className="hidden sm:inline">Library</span>
          </button>

          {/* Index New Action */}
          <button
            onClick={onOpenIngest}
            className="px-3.5 py-1.5 rounded-sm border border-accent-sunset/40 bg-accent-sunset/10 hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-ink-body hover:text-black transition-all flex items-center gap-1.5"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Index New</span>
          </button>
        </div>
      </div>
    </header>
  );
};
