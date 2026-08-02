import React, { useState } from 'react';
import { VideoItem } from '../types';
import { X, Video, Plus, Sparkles, Check, Play, ExternalLink } from 'lucide-react';
import { ingestVideoUrl } from '../services/api';

interface LibraryModalProps {
  isOpen: boolean;
  onClose: () => void;
  videos: VideoItem[];
  onVideoIngested: (video: VideoItem) => void;
}

export const LibraryModal: React.FC<LibraryModalProps> = ({
  isOpen,
  onClose,
  videos,
  onVideoIngested,
}) => {
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestSuccessMsg, setIngestSuccessMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const totalChunks = videos.reduce((sum, v) => sum + v.chunk_count, 0);

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!youtubeUrl.trim()) return;

    setIsIngesting(true);
    setIngestSuccessMsg(null);

    const response = await ingestVideoUrl(youtubeUrl);

    setIsIngesting(false);
    if (response.success && response.video) {
      onVideoIngested(response.video);
      setYoutubeUrl('');
      setIngestSuccessMsg(response.message);
      setTimeout(() => setIngestSuccessMsg(null), 4000);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 backdrop-blur-md animate-fade-in">
      <div 
        className="bg-canvas-card border border-hairline-bright rounded-xl w-full max-w-3xl overflow-hidden shadow-2xl flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-hairline bg-canvas">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full border border-hairline bg-canvas-soft flex items-center justify-center text-accent-sunset">
              <Video className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Indexed Creator Library</h2>
              <p className="eyebrow-mono text-[9px] text-ink-mute">
                {videos.length} VIDEOS // {totalChunks} TRANSCRIPT CHUNKS
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-full transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Ingest Form Bar */}
        <div className="p-6 border-b border-hairline bg-canvas-soft/40 space-y-3">
          <span className="eyebrow-mono">INDEX NEW CONTENT</span>
          <form onSubmit={handleIngest} className="flex gap-2">
            <input
              type="text"
              value={youtubeUrl}
              onChange={(e) => setYoutubeUrl(e.target.value)}
              placeholder="Paste YouTube Video URL (e.g. https://youtube.com/watch?v=...)"
              className="flex-1 px-4 py-2.5 bg-canvas border border-hairline rounded-lg text-xs sm:text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
            />
            <button
              type="submit"
              disabled={isIngesting || !youtubeUrl.trim()}
              className="px-4 py-2.5 bg-canvas-card border border-hairline-bright hover:border-accent-sunset hover:bg-accent-sunset hover:text-black rounded-lg text-xs font-medium text-ink disabled:opacity-40 transition-all flex items-center gap-1.5 shrink-0"
            >
              {isIngesting ? (
                <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"></span>
              ) : (
                <Plus className="w-4 h-4" />
              )}
              <span>{isIngesting ? 'Ingesting...' : 'Ingest'}</span>
            </button>
          </form>

          {ingestSuccessMsg && (
            <div className="p-3 bg-emerald-950/40 border border-emerald-800/50 rounded-lg text-xs text-emerald-400 flex items-center gap-2 animate-fade-in">
              <Check className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>{ingestSuccessMsg}</span>
            </div>
          )}
        </div>

        {/* Video List */}
        <div className="p-6 overflow-y-auto space-y-3 divide-y divide-hairline/40">
          {videos.map((vid) => (
            <div key={vid.id} className="pt-3 first:pt-0 flex items-start gap-4 group">
              <img
                src={vid.thumbnail_url}
                alt={vid.title}
                className="w-24 h-14 object-cover rounded border border-hairline bg-canvas-soft shrink-0"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-accent-sunset uppercase tracking-wider">
                    {vid.category}
                  </span>
                  <span className="text-ink-mute text-xs">•</span>
                  <span className="text-xs font-mono text-ink-mute">{vid.duration_formatted}</span>
                </div>
                <h4 className="text-xs sm:text-sm font-medium text-ink truncate group-hover:text-accent-sunset transition-colors">
                  {vid.title}
                </h4>
                <p className="text-[11px] text-ink-mute font-mono mt-0.5">
                  {vid.chunk_count} chunks indexed • Added {vid.uploaded_at}
                </p>
              </div>

              {vid.youtube_id && (
                <a
                  href={`https://youtube.com/watch?v=${vid.youtube_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-2 text-ink-mute hover:text-ink transition-colors"
                  title="Watch on YouTube"
                >
                  <ExternalLink className="w-4 h-4" />
                </a>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
