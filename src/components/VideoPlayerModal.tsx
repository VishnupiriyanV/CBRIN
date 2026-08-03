import React, { useEffect, useRef } from 'react';
import { ChunkResult } from '../types';
import { X, Clock, ExternalLink, HelpCircle, Layers } from 'lucide-react';

interface VideoPlayerModalProps {
  result: ChunkResult | null;
  onClose: () => void;
}

const API_BASE_URL = 'http://localhost:8000/api';

export const VideoPlayerModal: React.FC<VideoPlayerModalProps> = ({
  result,
  onClose,
}) => {
  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement>(null);

  if (!result) return null;

  const youtubeId = result.youtube_id;
  const startSec = result.start_sec || 0;
  const isLocal = result.is_local || !youtubeId;

  // YouTube embed vs Local media URL
  const embedUrl = youtubeId
    ? `https://www.youtube-nocookie.com/embed/${youtubeId}?start=${startSec}&autoplay=1&rel=0`
    : null;
  const directLink = youtubeId
    ? `https://www.youtube.com/watch?v=${youtubeId}&t=${startSec}s`
    : null;
  const localMediaUrl = isLocal ? `${API_BASE_URL}/media/${result.video_id}` : null;

  // Auto-seek local video on load
  useEffect(() => {
    if (mediaRef.current && startSec > 0) {
      mediaRef.current.currentTime = startSec;
    }
  }, [result, startSec]);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 backdrop-blur-md animate-fade-in">
      <div
        className="bg-canvas-card border border-hairline-bright rounded-xl w-full max-w-4xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-hairline bg-canvas">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-accent-sunset animate-pulse"></div>
            <div>
              <span className="eyebrow-mono text-[9px] block">JUMPED TO MOMENT // {result.start_timestamp}</span>
              <h2 className="text-sm sm:text-base font-semibold text-ink truncate max-w-lg">
                {result.video_title}
              </h2>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {directLink && (
              <a
                href={directLink}
                target="_blank"
                rel="noopener noreferrer"
                className="p-2 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-full transition-colors text-xs flex items-center gap-1"
                title="Open directly on YouTube"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            )}
            <button
              onClick={onClose}
              className="p-2 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-full transition-colors"
              title="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Video / Audio Embed Player */}
        <div className="relative aspect-video bg-black w-full border-b border-hairline flex items-center justify-center">
          {embedUrl ? (
            <iframe
              src={embedUrl}
              title={result.video_title}
              className="w-full h-full border-0"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
            ></iframe>
          ) : localMediaUrl ? (
            <video
              ref={mediaRef as React.RefObject<HTMLVideoElement>}
              src={`${localMediaUrl}#t=${startSec}`}
              controls
              autoPlay
              className="w-full h-full object-contain"
            />
          ) : (
            <div className="text-center text-ink-mute text-sm font-mono space-y-2 p-8">
              <p>Media stream unavailable for this video.</p>
              <p className="text-xs">Timestamp: {result.start_timestamp} - {result.end_timestamp}</p>
            </div>
          )}
        </div>

        {/* Spoken Segment Details Footer */}
        <div className="p-6 bg-canvas space-y-3 overflow-y-auto">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-accent-sunset" />
              <span className="text-xs font-mono text-ink font-medium">
                Segment: {result.start_timestamp} - {result.end_timestamp} ({result.end_sec - result.start_sec}s)
              </span>
            </div>
            <span className="text-xs font-mono text-ink-mute">
              {Math.round(result.score * 100)}% similarity match
            </span>
          </div>

          {result.section_topic && (
            <div className="flex items-center gap-1.5 text-xs font-mono text-ink-mute">
              <Layers className="w-3.5 h-3.5 text-accent-sunset" />
              <span>SECTION: {result.section_topic}</span>
            </div>
          )}

          <div className="bg-canvas-soft border border-hairline rounded-lg p-4 text-sm text-ink-body leading-relaxed">
            <p className="eyebrow-mono text-[9px] mb-1.5 text-accent-sunset">SPOKEN TRANSCRIPT</p>
            <p className="italic text-ink font-sans">"{result.text}"</p>
          </div>

          {result.questions_answered && result.questions_answered.length > 0 && (
            <div className="space-y-1 pt-1">
              <div className="flex items-center gap-1 text-[10px] font-mono text-ink-mute uppercase tracking-wider">
                <HelpCircle className="w-3 h-3 text-accent-sunset" />
                <span>ANSWERED QUESTION:</span>
              </div>
              <p className="text-xs text-ink italic font-sans pl-4 border-l border-hairline-bright">
                "{result.questions_answered[0]}"
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
