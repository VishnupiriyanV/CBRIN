import React, { useEffect, useRef, useState } from 'react';
import { ChunkResult } from '../types';
import { API_ORIGIN, resolveMediaUrl } from '../services/api';
import { X, Clock, ExternalLink, HelpCircle, Layers, Play, AlertCircle, RefreshCw } from 'lucide-react';

interface VideoPlayerModalProps {
  result: ChunkResult | null;
  onClose: () => void;
}

const API_BASE_URL = `${API_ORIGIN}/api`;

export const VideoPlayerModal: React.FC<VideoPlayerModalProps> = ({
  result,
  onClose,
}) => {
  const mediaRef = useRef<HTMLVideoElement>(null);
  const [hasMediaError, setHasMediaError] = useState(false);
  const [iframeError, setIframeError] = useState(false);

  useEffect(() => {
    setHasMediaError(false);
    setIframeError(false);
  }, [result]);

  if (!result) return null;

  const youtubeId = result.youtube_id;
  const startSec = result.start_sec || 0;
  const isLocal = result.is_local || !youtubeId;

  // Formulate reliable YouTube Embed URL using standard domain + origin query parameters
  const originParam = typeof window !== 'undefined' ? encodeURIComponent(window.location.origin) : '';
  const embedUrl = youtubeId
    ? `https://www.youtube.com/embed/${youtubeId}?start=${startSec}&autoplay=1&rel=0&enablejsapi=1&origin=${originParam}`
    : null;

  const directYoutubeLink = youtubeId
    ? `https://www.youtube.com/watch?v=${youtubeId}&t=${startSec}s`
    : null;

  const localMediaUrl = isLocal ? `${API_BASE_URL}/media/${result.video_id}` : null;
  const displayPoster = resolveMediaUrl(result.keyframe_url) || resolveMediaUrl(result.thumbnail_url);

  // Auto-seek local video when loaded
  useEffect(() => {
    if (mediaRef.current && startSec > 0 && !hasMediaError) {
      try {
        mediaRef.current.currentTime = startSec;
      } catch (e) {
        console.warn('Seek error:', e);
      }
    }
  }, [result, startSec, hasMediaError]);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/85 backdrop-blur-md animate-fade-in">
      <div
        className="bg-canvas-card border border-hairline-bright rounded-2xl w-full max-w-4xl overflow-hidden shadow-2xl flex flex-col max-h-[92vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-hairline bg-canvas">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-accent-sunset animate-pulse"></div>
            <div>
              <span className="eyebrow-mono text-[9px] block">JUMPED TO MOMENT // {result.start_timestamp}</span>
              <h2 className="text-sm sm:text-base font-semibold text-ink truncate max-w-md sm:max-w-lg">
                {result.video_title}
              </h2>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {directYoutubeLink && (
              <a
                href={directYoutubeLink}
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1.5 rounded-full border border-hairline bg-canvas-soft hover:bg-accent-sunset hover:text-black hover:border-accent-sunset transition-all text-xs font-medium flex items-center gap-1.5"
                title="Open directly on YouTube"
              >
                <span>Watch on YouTube</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
            <button
              onClick={onClose}
              className="p-2 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-full transition-colors"
              title="Close player"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Video / Player Display Frame */}
        <div className="relative aspect-video bg-[#050505] w-full border-b border-hairline flex items-center justify-center overflow-hidden">
          {/* Option A: Embedded YouTube Iframe */}
          {embedUrl && !iframeError ? (
            <div className="relative w-full h-full">
              <iframe
                src={embedUrl}
                title={result.video_title}
                className="w-full h-full border-0"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                onError={() => setIframeError(true)}
              ></iframe>
            </div>
          ) : localMediaUrl && !hasMediaError ? (
            /* Option B: Local Video Stream */
            <video
              ref={mediaRef}
              src={`${localMediaUrl}#t=${startSec}`}
              controls
              autoPlay
              poster={displayPoster || undefined}
              onError={() => setHasMediaError(true)}
              className="w-full h-full object-contain"
            />
          ) : (
            /* Fallback Card: Displayed if video stream fails, YouTube blocks embed, or local file unavailable */
            <div className="relative w-full h-full flex flex-col items-center justify-center p-6 text-center">
              {/* Background Poster Blur */}
              {displayPoster && (
                <div
                  className="absolute inset-0 bg-cover bg-center opacity-25 filter blur-md scale-105 pointer-events-none"
                  style={{ backgroundImage: `url(${displayPoster})` }}
                />
              )}

              <div className="relative z-10 space-y-4 max-w-md bg-canvas-card/90 border border-hairline p-6 rounded-2xl backdrop-blur-xl shadow-2xl">
                {displayPoster && (
                  <img
                    src={displayPoster}
                    alt={result.video_title}
                    className="w-32 h-20 object-cover rounded-lg mx-auto border border-hairline shadow-md"
                  />
                )}

                <div className="space-y-1">
                  <div className="flex items-center justify-center gap-1.5 text-xs text-amber-400 font-mono">
                    <AlertCircle className="w-4 h-4" />
                    <span>DIRECT MEDIA STREAM RESTRICTED</span>
                  </div>
                  <p className="text-xs text-ink-body font-sans">
                    This video playback is optimized via YouTube or local reference. Click below to view this exact timestamp moment directly.
                  </p>
                </div>

                <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-2">
                  {directYoutubeLink ? (
                    <a
                      href={directYoutubeLink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="w-full sm:w-auto px-5 py-2.5 rounded-full bg-accent-sunset hover:bg-amber-400 text-black text-xs font-semibold transition-all flex items-center justify-center gap-2 shadow-md"
                    >
                      <Play className="w-4 h-4 fill-current" />
                      <span>Open on YouTube at {result.start_timestamp}</span>
                    </a>
                  ) : (
                    <button
                      onClick={() => { setHasMediaError(false); setIframeError(false); }}
                      className="px-4 py-2 rounded-full border border-hairline bg-canvas-soft hover:bg-canvas text-xs text-ink transition-all flex items-center gap-1.5"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                      <span>Retry Playback</span>
                    </button>
                  )}
                </div>
              </div>
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
              {result.confidence === 'strong' ? 'Strong match' : result.confidence === 'weak' ? 'Closest match' : 'Possible match'}
            </span>
          </div>

          {result.section_topic && (
            <div className="flex items-center gap-1.5 text-xs font-mono text-ink-mute">
              <Layers className="w-3.5 h-3.5 text-accent-sunset" />
              <span>SECTION: {result.section_topic}</span>
            </div>
          )}

          <div className="bg-canvas-soft border border-hairline rounded-xl p-4 text-sm text-ink-body leading-relaxed">
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
