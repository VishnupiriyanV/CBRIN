import React, { useState } from 'react';
import { 
  Search, 
  Bot, 
  Sparkles, 
  Wand2, 
  FileVideo, 
  Bookmark, 
  Activity, 
  Plus, 
  ChevronLeft, 
  ChevronRight
} from 'lucide-react';
import { CbrinLogo } from './CbrinLogo';
import { LibraryStats } from '../types';

export type AppView = 'search' | 'agent' | 'engine' | 'studio';

interface SidebarProps {
  activeView: AppView;
  onChangeView: (view: AppView) => void;
  totalVideos: number;
  totalChunks: number;
  stats: LibraryStats | null;
  highlightCount: number;
  backendOnline: boolean | null;
  onOpenLibrary: () => void;
  onOpenIngest: () => void;
  onOpenHighlights: () => void;
  onOpenProgress: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  onChangeView,
  totalVideos,
  totalChunks,
  stats,
  highlightCount,
  backendOnline,
  onOpenLibrary,
  onOpenIngest,
  onOpenHighlights,
  onOpenProgress,
}) => {
  const [collapsed, setCollapsed] = useState(false);

  const isFullyIndexed = stats?.is_fully_indexed ?? (totalVideos > 0);
  const failedCount = stats?.failed_count ?? 0;

  const navItems: { id: AppView; label: string; icon: React.ComponentType<{ className?: string }>; shortcut?: string }[] = [
    {
      id: 'search',
      label: 'Search',
      icon: Search,
      shortcut: '/',
    },
    {
      id: 'agent',
      label: 'Agent',
      icon: Bot,
    },
    {
      id: 'engine',
      label: 'Engine',
      icon: Sparkles,
    },
    {
      id: 'studio',
      label: 'Studio',
      icon: Wand2,
    },
  ];

  return (
    <aside
      className={`relative z-30 flex flex-col h-screen sticky top-0 border-r border-hairline/80 bg-canvas/95 backdrop-blur-md transition-all duration-200 ease-out shrink-0 select-none ${
        collapsed ? 'w-16' : 'w-56 sm:w-60'
      }`}
    >
      {/* Brand Header */}
      <div className="h-14 px-3.5 border-b border-hairline/60 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5 overflow-hidden">
          <CbrinLogo />
          {!collapsed && (
            <span className="font-mono font-semibold tracking-tight text-ink text-sm">
              CBRIN
            </span>
          )}
        </div>

        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1 rounded-sm text-ink-mute hover:text-ink hover:bg-canvas-soft transition-colors cursor-pointer shrink-0"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronLeft className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Main Navigation List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-4">
        {/* Workspace Views */}
        <div className="space-y-0.5">
          {!collapsed && (
            <div className="px-2.5 py-1 text-[11px] text-ink-mute/60">
              Views
            </div>
          )}
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeView === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onChangeView(item.id)}
                className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-sm text-xs font-medium transition-all group cursor-pointer ${
                  isActive
                    ? 'bg-canvas-card text-ink border border-hairline-bright shadow-sm'
                    : 'text-ink-mute hover:text-ink hover:bg-canvas-soft border border-transparent'
                }`}
                title={collapsed ? item.label : undefined}
              >
                <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-ink-body' : 'text-ink-mute group-hover:text-ink'}`} />
                {!collapsed && (
                  <div className="flex-1 flex items-center justify-between min-w-0">
                    <span className="truncate">{item.label}</span>
                    {item.shortcut && (
                      <kbd className="text-[9px] font-mono px-1 py-0.2 rounded bg-canvas-soft border border-hairline text-ink-mute">
                        {item.shortcut}
                      </kbd>
                    )}
                  </div>
                )}
              </button>
            );
          })}
        </div>

        {/* Library & Tools */}
        <div className="space-y-0.5 pt-3 border-t border-hairline/40">
          {!collapsed && (
            <div className="px-2.5 py-1 text-[11px] text-ink-mute/60">
              Library
            </div>
          )}

          {/* Quick Ingest / Add */}
          <button
            onClick={onOpenIngest}
            disabled={backendOnline === false}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-sm text-xs font-medium text-ink-body hover:bg-accent-sunset/10 transition-colors group cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            title={collapsed ? "Add Content" : undefined}
          >
            <Plus className="w-4 h-4 shrink-0" />
            {!collapsed && <span className="truncate">Add Media</span>}
          </button>

          {/* Videos Library */}
          <button
            onClick={onOpenLibrary}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-sm text-xs font-medium text-ink-mute hover:text-ink hover:bg-canvas-soft transition-colors cursor-pointer"
            title={collapsed ? "Media Library" : undefined}
          >
            <FileVideo className="w-4 h-4 shrink-0 text-ink-mute" />
            {!collapsed && (
              <div className="flex-1 flex items-center justify-between min-w-0 font-mono text-[11px]">
                <span>Media</span>
                <span className="text-ink-mute/70">{totalVideos}</span>
              </div>
            )}
          </button>

          {/* Highlights */}
          <button
            onClick={onOpenHighlights}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-sm text-xs font-medium text-ink-mute hover:text-ink hover:bg-canvas-soft transition-colors cursor-pointer"
            title={collapsed ? "Saved Highlights" : undefined}
          >
            <Bookmark className="w-4 h-4 shrink-0 text-ink-body" />
            {!collapsed && (
              <div className="flex-1 flex items-center justify-between min-w-0 font-mono text-[11px]">
                <span>Saved</span>
                <span className="text-ink-body">{highlightCount}</span>
              </div>
            )}
          </button>

          {/* Telemetry Progress */}
          <button
            onClick={onOpenProgress}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-sm text-xs font-medium text-ink-mute hover:text-ink hover:bg-canvas-soft transition-colors cursor-pointer"
            title={collapsed ? "Telemetry" : undefined}
          >
            <Activity className="w-4 h-4 shrink-0 text-ink" />
            {!collapsed && (
              <div className="flex-1 flex items-center justify-between min-w-0 font-mono text-[11px]">
                <span>Telemetry</span>
                {failedCount > 0 ? (
                  <span className="text-danger">{failedCount} err</span>
                ) : isFullyIndexed ? (
                  <span className="text-ink">100%</span>
                ) : (
                  <span className="text-ink-body">Indexing</span>
                )}
              </div>
            )}
          </button>
        </div>
      </div>

      {/* Clean Status Footer */}
      <div className="p-2.5 border-t border-hairline/60 bg-canvas-soft/40">
        <div
          className={`flex items-center gap-2 px-2 py-1 rounded text-mono text-[10px] text-ink-mute ${
            collapsed ? 'justify-center' : 'justify-between'
          }`}
        >
          <div className="flex items-center gap-1.5 overflow-hidden">
            <span className={`w-1.5 h-1.5 rounded-sm shrink-0 ${backendOnline ? 'bg-ink' : 'bg-danger'}`} />
            {!collapsed && (
              <span className="truncate font-mono">
                {backendOnline ? 'API Connected' : 'API Offline'}
              </span>
            )}
          </div>
          {!collapsed && totalChunks > 0 && (
            <span className="font-mono text-ink-mute/70">{totalChunks} chunks</span>
          )}
        </div>
      </div>
    </aside>
  );
};
