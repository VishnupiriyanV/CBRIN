import React, { useEffect, useRef, useState } from 'react';
import { Sparkles, Loader2, Settings2, AlertTriangle } from 'lucide-react';
import { VideoItem, ClipCandidate, EngineJob } from '../../types';
import { engineAnalyze, engineGetJob, engineGetClips } from '../../services/api';
import { ClipCard } from './ClipCard';
import { BrandKitPanel } from './BrandKitPanel';

interface ClipStudioProps {
  videos: VideoItem[];
  backendOnline: boolean;
}

export const ClipStudio: React.FC<ClipStudioProps> = ({ videos, backendOnline }) => {
  const [selectedVideoId, setSelectedVideoId] = useState<string>('');
  const [job, setJob] = useState<EngineJob | null>(null);
  const [clips, setClips] = useState<ClipCandidate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showBrandKit, setShowBrandKit] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const indexedVideos = videos.filter((v) => v.status === 'fully_indexed');

  useEffect(() => {
    if (!selectedVideoId && indexedVideos.length > 0) {
      setSelectedVideoId(indexedVideos[0].id);
    }
  }, [indexedVideos, selectedVideoId]);

  useEffect(() => {
    if (!selectedVideoId) return;
    engineGetClips(selectedVideoId).then(setClips).catch(() => setClips([]));
  }, [selectedVideoId]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // The adjust endpoint returns the persisted clip, so swap it in rather than refetching the
  // whole list — a refetch would also reorder nothing but would discard each card's local
  // render state for no gain.
  const handleClipAdjusted = (updated: ClipCandidate) => {
    setClips((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  };

  const runAnalyze = async () => {
    if (!selectedVideoId) return;
    setError(null);
    setJob(null);
    try {
      const { job_id } = await engineAnalyze(selectedVideoId, 6);

      // See ClipCard.startRender: re-running Analyze (or switching video and re-running)
      // orphaned the previous interval, and its callback cleared `pollRef.current` — the
      // NEW interval — when the old job finished. The analysis the user was watching then
      // hung at its last reported status forever.
      if (pollRef.current) clearInterval(pollRef.current);

      const handle = setInterval(async () => {
        const stop = () => {
          clearInterval(handle);
          if (pollRef.current === handle) pollRef.current = null;
        };
        try {
          const j = await engineGetJob(job_id);
          if (pollRef.current !== handle) {
            clearInterval(handle);
            return;
          }
          setJob(j);
          if (j.status === 'done' || j.status === 'failed') {
            stop();
            if (j.status === 'done') {
              const fetched = await engineGetClips(selectedVideoId);
              setClips(fetched);
            }
          }
        } catch (err) {
          console.error('Analyze job poll failed:', err);
          stop();
        }
      }, 1200);
      pollRef.current = handle;
    } catch (err: any) {
      setError(err.message || 'Analyze failed to start');
    }
  };

  const isRunning = job && job.status !== 'done' && job.status !== 'failed';
  const degradedClip = clips.find((c) => c.degraded);
  const isDegraded = clips.length > 0 && !!degradedClip;
  // llm_partial means real LLM beats plus a documented gap, not a total fallback — it gets a
  // softer tone than a full heuristic run so the two aren't visually indistinguishable (an
  // identical alarm for both trains people to stop reading either one).
  const isPartial = degradedClip?.analysis_mode === 'llm_partial';
  const degradedReason = degradedClip?.degraded_reason
    ?? 'No LLM key configured (or provider unavailable) — these clips use heuristic beat detection, a weaker but always-available fallback.';

  return (
    <div className="space-y-6">
      {/* Header row: video picker + analyze */}
      <div className="bg-canvas-card border border-hairline rounded-sm p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-sm bg-canvas-soft border border-hairline flex items-center justify-center text-ink-body">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-ink">ENGINE — Clip Studio</h3>
              <p className="text-[10px] font-mono text-ink-mute">Narrative-aware clip generation</p>
            </div>
          </div>
          <button
            onClick={() => setShowBrandKit(!showBrandKit)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-hairline hover:border-hairline-bright text-xs font-medium text-ink-mute hover:text-ink transition-all"
          >
            <Settings2 className="w-3.5 h-3.5" />
            <span>Brand Kit</span>
          </button>
        </div>

        {showBrandKit && (
          <div className="border-t border-hairline/60 pt-4">
            <BrandKitPanel />
          </div>
        )}

        <div className="flex items-center gap-3">
          <select
            value={selectedVideoId}
            onChange={(e) => setSelectedVideoId(e.target.value)}
            disabled={!backendOnline || indexedVideos.length === 0}
            className="flex-1 bg-canvas-soft border border-hairline rounded-sm px-3 py-2 text-xs text-ink outline-none disabled:opacity-40"
          >
            {indexedVideos.length === 0 ? (
              <option value="">No indexed videos yet</option>
            ) : (
              indexedVideos.map((v) => (
                <option key={v.id} value={v.id}>{v.title}</option>
              ))
            )}
          </select>
          <button
            onClick={runAnalyze}
            disabled={!backendOnline || !selectedVideoId || !!isRunning}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-sm border border-accent-sunset/40 bg-accent-sunset/10 hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-ink-body transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            {isRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            <span>Analyze</span>
          </button>
        </div>

        {job && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[10px] font-mono text-ink-mute">
              <span>{job.stage} — {job.message}</span>
              <span>{Math.round((job.progress || 0) * 100)}</span>
            </div>
            <div className="h-1.5 rounded-sm bg-canvas-soft border border-hairline/60 overflow-hidden">
              <div
                className={`h-full rounded-sm transition-all ${job.status === 'failed' ? 'bg-danger' : 'bg-accent-sunset'}`}
                style={{ width: `${Math.max(2, (job.progress || 0) * 100)}%` }}
              />
            </div>
            {job.status === 'failed' && (
              <p className="text-[10px] font-mono text-danger">{job.error}</p>
            )}
          </div>
        )}

        {error && <p className="text-[10px] font-mono text-danger">{error}</p>}
      </div>

      {/* Degraded-mode notice — mirrors the search layer's amber banner treatment. Softer
          tone for a partial LLM run (some transcript windows failed) than a full heuristic
          fallback (no LLM ran at all). */}
      {isDegraded && (
        <div
          className={
            isPartial
              ? 'bg-canvas-card/20 border border-hairline-bright/20 rounded-sm p-3 text-xs text-ink-body/90 font-mono text-center flex items-center justify-center gap-2 animate-fade-in'
              : 'bg-canvas-card/30 border border-hairline-bright/30 rounded-sm p-3 text-xs text-ink-body font-mono text-center flex items-center justify-center gap-2 animate-fade-in'
          }
        >
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>{degradedReason}</span>
        </div>
      )}

      {/* Clip list */}
      {clips.length > 0 ? (
        <div className="space-y-4">
          <span className="eyebrow-mono">{clips.length} RANKED CLIP{clips.length === 1 ? '' : 'S'}</span>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {clips.map((clip, idx) => (
              <ClipCard key={clip.id} clip={clip} rank={idx + 1} onAdjusted={handleClipAdjusted} />
            ))}
          </div>
        </div>
      ) : !isRunning ? (
        <div className="bg-canvas-soft/60 border border-hairline rounded-sm p-10 text-center space-y-2">
          <p className="text-sm text-ink-body">No clips yet for this video.</p>
          <p className="text-xs text-ink-mute">Run Analyze to generate ranked, sentence-clean clip candidates.</p>
        </div>
      ) : null}
    </div>
  );
};
