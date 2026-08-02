import React from 'react';
import { Database, Plus, Search, Sparkles, Video } from 'lucide-react';

interface HeaderProps {
  totalVideos: number;
  totalChunks: number;
  onOpenLibrary: () => void;
  onOpenIngest: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  totalVideos,
  totalChunks,
  onOpenLibrary,
  onOpenIngest,
}) => {
  return (
    <header className="border-b border-hairline bg-[#0a0a0a]/90 backdrop-blur-md sticky top-0 z-40">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        
        {/* Brand & Eyebrow Tag */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full border border-hairline-bright bg-canvas-soft flex items-center justify-center text-ink">
            <Search className="w-4 h-4 text-accent-sunset" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-lg tracking-tight text-ink">Vault</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full border border-hairline bg-canvas-card text-ink-mute tracking-widest uppercase">
                MVP v0.1
              </span>
            </div>
            <p className="eyebrow-mono text-[9px] -mt-0.5 text-ink-mute">
              CREATORBRAIN // LAYER 1 — SEMANTIC CONTENT SEARCH
            </p>
          </div>
        </div>

        {/* Right Stats & Actions */}
        <div className="flex items-center gap-3">
          {/* Library Stats Pill */}
          <button
            onClick={onOpenLibrary}
            className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full border border-hairline bg-canvas-card hover:border-hairline-bright transition-all text-xs text-ink-body group"
            title="View Indexed Content Library"
          >
            <Video className="w-3.5 h-3.5 text-ink-mute group-hover:text-ink transition-colors" />
            <span className="font-mono text-ink-mute">{totalVideos} Videos</span>
            <span className="text-hairline-bright">|</span>
            <span className="font-mono text-accent-sunset">{totalChunks} Chunks</span>
          </button>

          {/* Ingest Action Button */}
          <button
            onClick={onOpenIngest}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-full border border-hairline-bright bg-canvas-soft hover:bg-canvas-hover hover:border-ink-mute transition-all text-xs font-medium text-ink"
          >
            <Plus className="w-3.5 h-3.5 text-accent-sunset" />
            <span>Ingest Media</span>
          </button>
        </div>
      </div>
    </header>
  );
};
