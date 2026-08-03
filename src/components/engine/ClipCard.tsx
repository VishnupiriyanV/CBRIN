import React, { useEffect, useRef, useState } from 'react';
import { Download, Play, ThumbsDown, ThumbsUp, Loader2 } from 'lucide-react';
import { ClipCandidate, RENDER_PRESETS, RenderPreset } from '../../types';
import { engineRender, engineGetJob, engineClipFileUrl, engineSendFeedback } from '../../services/api';
import { ScoreBreakdown } from './ScoreBreakdown';

interface ClipCardProps {
  clip: ClipCandidate;
  rank: number;
}

const PRESET_LABELS: Record<RenderPreset, string> = {
  tiktok: 'TikTok (9:16)',
  shorts: 'Shorts (9:16)',
  linkedin: 'LinkedIn (1:1)',
  x: 'X (16:9)',
};

function formatDuration(startSec: number, endSec: number): string {
  const dur = Math.max(0, Math.round(endSec - startSec));
  const m = Math.floor(dur / 60);
  const s = dur % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export const ClipCard: React.FC<ClipCardProps> = ({ clip, rank }) => {
  const [selectedPresets, setSelectedPresets] = useState<RenderPreset[]>(['tiktok']);
  const [renderJobId, setRenderJobId] = useState<string | null>(null);
  const [renderStatus, setRenderStatus] = useState<string | null>(null);
  const [renderMessage, setRenderMessage] = useState<string>('');
  const [renderedPresets, setRenderedPresets] = useState<Set<string>>(new Set());
  const [feedbackSent, setFeedbackSent] = useState<'winner' | 'dud' | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const togglePreset = (preset: RenderPreset) => {
    setSelectedPresets((prev) =>
      prev.includes(preset) ? prev.filter((p) => p !== preset) : [...prev, preset]
    );
  };

  const startRender = async () => {
    if (selectedPresets.length === 0) return;
    setRenderStatus('queued');
    setRenderMessage('Queuing render job...');
    try {
      const { job_id } = await engineRender(clip.id, selectedPresets);
      setRenderJobId(job_id);
      pollRef.current = setInterval(async () => {
        try {
          const job = await engineGetJob(job_id);
          setRenderStatus(job.status);
          setRenderMessage(job.message || job.stage);
          if (job.status === 'done' || job.status === 'failed') {
            if (pollRef.current) clearInterval(pollRef.current);
            if (job.status === 'done' && job.result?.presets) {
              setRenderedPresets(new Set(Object.keys(job.result.presets)));
            }
          }
        } catch (err) {
          console.error('Render job poll failed:', err);
          if (pollRef.current) clearInterval(pollRef.current);
        }
      }, 1500);
    } catch (err: any) {
      setRenderStatus('failed');
      setRenderMessage(err.message || 'Render failed to start');
    }
  };

  const sendFeedback = async (verdict: 'winner' | 'dud') => {
    try {
      await engineSendFeedback(clip.id, verdict);
      setFeedbackSent(verdict);
    } catch (err) {
      console.error('Feedback failed:', err);
    }
  };

  return (
    <div className="bg-canvas-card border border-hairline hover:border-hairline-bright rounded-xl p-5 space-y-4 transition-colors animate-fade-in">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="w-6 h-6 rounded-full bg-canvas-soft border border-hairline flex items-center justify-center text-[10px] font-mono text-accent-sunset shrink-0">
            {rank}
          </span>
          <div className="min-w-0">
            <h4 className="text-sm font-semibold text-ink truncate">{clip.title || 'Untitled clip'}</h4>
            <div className="flex items-center gap-2 text-[10px] font-mono text-ink-mute mt-0.5">
              <span>{formatDuration(clip.start_sec, clip.end_sec)}</span>
              <span className="text-hairline-bright">•</span>
              <span>{clip.start_sec.toFixed(1)}s → {clip.end_sec.toFixed(1)}s</span>
              {!clip.timing_precise && (
                <>
                  <span className="text-hairline-bright">•</span>
                  <span className="text-amber-400" title="Word-level timing unavailable — using sentence-level boundaries">
                    approx. timing
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => sendFeedback('winner')}
            disabled={feedbackSent !== null}
            title="Mark as a winner"
            className={`p-1.5 rounded-full border transition-colors ${feedbackSent === 'winner' ? 'border-emerald-500/60 bg-emerald-500/10 text-emerald-400' : 'border-hairline text-ink-mute hover:text-ink hover:border-hairline-bright'}`}
          >
            <ThumbsUp className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => sendFeedback('dud')}
            disabled={feedbackSent !== null}
            title="Mark as a dud"
            className={`p-1.5 rounded-full border transition-colors ${feedbackSent === 'dud' ? 'border-red-500/60 bg-red-500/10 text-red-400' : 'border-hairline text-ink-mute hover:text-ink hover:border-hairline-bright'}`}
          >
            <ThumbsDown className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {clip.quotable_line && (
        <blockquote className="text-xs text-ink-body italic border-l-2 border-accent-sunset/50 pl-3 py-0.5">
          "{clip.quotable_line}"
        </blockquote>
      )}

      <ScoreBreakdown signals={clip.signals} reason={clip.reason} />

      <div className="pt-3 border-t border-hairline/60 space-y-2.5">
        <div className="flex flex-wrap gap-1.5">
          {RENDER_PRESETS.map((preset) => (
            <button
              key={preset}
              onClick={() => togglePreset(preset)}
              className={`px-2.5 py-1 rounded-full border text-[10px] font-mono transition-all ${
                selectedPresets.includes(preset)
                  ? 'border-accent-sunset bg-accent-sunset/10 text-accent-sunset'
                  : 'border-hairline text-ink-mute hover:border-hairline-bright hover:text-ink'
              }`}
            >
              {PRESET_LABELS[preset]}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={startRender}
            disabled={selectedPresets.length === 0 || renderStatus === 'queued' || renderStatus === 'running'}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border border-accent-sunset/40 bg-accent-sunset/10 hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-accent-sunset transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {renderStatus === 'queued' || renderStatus === 'running' ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            <span>Render</span>
          </button>

          {renderStatus && renderStatus !== 'done' && (
            <span className="text-[10px] font-mono text-ink-mute">{renderMessage}</span>
          )}
          {renderStatus === 'failed' && (
            <span className="text-[10px] font-mono text-red-400">{renderMessage}</span>
          )}
        </div>

        {renderedPresets.size > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {Array.from(renderedPresets).map((preset) => (
              <a
                key={preset}
                href={engineClipFileUrl(clip.id, preset)}
                download
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-hairline bg-canvas-soft hover:border-hairline-bright text-[10px] font-mono text-ink hover:text-accent-sunset transition-all"
              >
                <Download className="w-3 h-3" />
                {PRESET_LABELS[preset as RenderPreset] || preset}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
