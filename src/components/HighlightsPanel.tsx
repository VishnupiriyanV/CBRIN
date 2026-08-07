import React from 'react';
import { Highlight, ChunkResult } from '../types';
import { X, Bookmark, Clock, Play, Trash2, FileDown, Layers, MessageSquare } from 'lucide-react';
import { exportHighlightsJSON, resolveMediaUrl } from '../services/api';
import { relativeTime } from '../utils';

interface HighlightsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  highlights: Highlight[];
  onJumpToMoment: (highlight: Highlight) => void;
  onRemoveHighlight: (chunkId: string) => void;
}

export const HighlightsPanel: React.FC<HighlightsPanelProps> = ({
  isOpen,
  onClose,
  highlights,
  onJumpToMoment,
  onRemoveHighlight,
}) => {
  if (!isOpen) return null;

  const handleJump = (h: Highlight) => {
    // Convert Highlight to a ChunkResult-compatible object for the video modal
    const asResult: ChunkResult = {
      id: h.chunk_id,
      video_id: h.video_id,
      video_title: h.video_title,
      channel: h.channel,
      youtube_id: h.youtube_id,
      is_local: h.is_local,
      start_sec: h.start_sec,
      end_sec: h.end_sec,
      start_timestamp: h.start_timestamp,
      end_timestamp: h.end_timestamp,
      text: h.text,
      score: 1,
      matched_concepts: [],
      thumbnail_url: h.thumbnail_url,
      keyframe_url: h.keyframe_url,
      section_topic: h.section_topic,
    };
    onJumpToMoment(asResult as any);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 animate-fade-in">
      <div
        className="bg-canvas-card border border-hairline-bright rounded-sm w-full max-w-3xl overflow-hidden flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-hairline bg-canvas">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-sm border border-accent-sunset/40 bg-accent-sunset/10 flex items-center justify-center text-ink-body">
              <Bookmark className="w-4 h-4 fill-current" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Highlighted Moments</h2>
              <p className="eyebrow-mono text-[9px] text-ink-mute">
                {highlights.length} bookmarked moment{highlights.length !== 1 ? 's' : ''}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {highlights.length > 0 && (
              <button
                onClick={() => exportHighlightsJSON()}
                className="px-3 py-1.5 rounded-sm border border-hairline bg-canvas-soft hover:border-hairline-bright text-xs font-medium text-ink transition-all flex items-center gap-1.5"
                title="Export highlights"
              >
                <FileDown className="w-3.5 h-3.5 text-ink-mute" />
                <span>Export</span>
              </button>
            )}
            <button
              onClick={onClose}
              className="p-2 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-sm transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Highlights List */}
        <div className="p-6 overflow-y-auto space-y-3">
          {highlights.length === 0 ? (
            <div className="text-center py-12 space-y-3">
              <div className="w-12 h-12 rounded-sm border border-hairline-bright bg-canvas-soft mx-auto flex items-center justify-center text-ink-mute">
                <Bookmark className="w-5 h-5" />
              </div>
              <div>
                <p className="text-sm font-medium text-ink">No highlighted moments yet</p>
                <p className="text-xs text-ink-mute font-sans mt-1">
                  Search your library and click the bookmark icon on any result to save it here.
                </p>
              </div>
            </div>
          ) : (
            highlights.map((h) => (
              <div
                key={h.chunk_id}
                className="bg-canvas-soft border border-hairline rounded-sm p-4 hover:border-hairline-bright transition-all group"
              >
                <div className="flex items-start gap-3">
                  {/* Thumbnail */}
                  {(h.keyframe_url || h.thumbnail_url) && (
                    <img
                      src={resolveMediaUrl(h.keyframe_url) || resolveMediaUrl(h.thumbnail_url)}
                      alt={h.video_title}
                      className="w-20 h-12 object-cover rounded border border-hairline bg-canvas shrink-0 hidden sm:block"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  )}

                  {/* Content */}
                  <div className="flex-1 min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] font-mono text-ink-body">
                        {h.channel}
                      </span>
                      <div className="flex items-center gap-1 text-[11px] font-mono text-ink-mute">
                        <Clock className="w-3 h-3" />
                        <span>{h.start_timestamp} - {h.end_timestamp}</span>
                      </div>
                      <span className="text-[10px] font-mono text-ink-mute">
                        {relativeTime(h.highlighted_at)}
                      </span>
                    </div>

                    <h4 className="text-sm font-medium text-ink truncate group-hover:text-ink-body transition-colors">
                      {h.video_title}
                    </h4>

                    {h.section_topic && (
                      <div className="flex items-center gap-1 text-[10px] font-mono text-ink-mute">
                        <Layers className="w-3 h-3 text-ink-body" />
                        <span>{h.section_topic}</span>
                      </div>
                    )}

                    <p className="text-xs text-ink-body font-sans line-clamp-2 italic">
                      "{h.text}"
                    </p>

                    {h.note && (
                      <div className="flex items-start gap-1.5 text-[11px] text-ink-mute">
                        <MessageSquare className="w-3 h-3 mt-0.5 text-ink-body shrink-0" />
                        <span className="font-sans">{h.note}</span>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => handleJump(h)}
                      className="p-2 text-ink-mute hover:text-ink-body hover:bg-canvas rounded-sm transition-colors"
                      title="Jump to moment"
                    >
                      <Play className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => onRemoveHighlight(h.chunk_id)}
                      className="p-2 text-ink-mute hover:text-danger hover:bg-canvas rounded-sm transition-colors"
                      title="Remove highlight"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
