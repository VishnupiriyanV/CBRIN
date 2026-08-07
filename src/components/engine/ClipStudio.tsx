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

  const runAnalyze = async () => {
    if (!selectedVideoId) return;
    setError(null);
    setJob(null);
    try {
      const { job_id } = await engineAnalyze(selectedVideoId, 6);
      pollRef.current = setInterval(async () => {
        try {
          const j = await engineGetJob(job_id);
          setJob(j);
          if (j.status === 'done' || j.status === 'failed') {
            if (pollRef.current) clearInterval(pollRef.current);
            if (j.status === 'done') {
              const fetched = await engineGetClips(selectedVideoId);
              setClips(fetched);
            }
          }
        } catch (err) {
          console.error('Analyze job poll failed:', err);
          if (pollRef.current) clearInterval(pollRef.current);
        }
      }, 1200);
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
      <div className="bg-canvas-card border border-hairline rounded-2xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-canvas-soft border border-hairline flex items-center justify-center text-accent-sunset">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-ink">ENGINE — Clip Studio</h3>
              <p className="text-[10px] font-mono text-ink-mute">Narrative-aware clip generation</p>
            </div>
          </div>
          <button
            onClick={() => setShowBrandKit(!showBrandKit)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-hairline hover:border-hairline-bright text-xs font-medium text-ink-mute hover:text-ink transition-all"
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
            className="flex-1 bg-canvas-soft border border-hairline rounded-lg px-3 py-2 text-xs text-ink outline-none disabled:opacity-40"
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
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-accent-sunset/40 bg-accent-sunset/10 hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-accent-sunset transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
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
            <div className="h-1.5 rounded-full bg-canvas-soft border border-hairline/60 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${job.status === 'failed' ? 'bg-red-500' : 'bg-accent-sunset'}`}
                style={{ width: `${Math.max(2, (job.progress || 0) * 100)}%` }}
              />
            </div>
            {job.status === 'failed' && (
              <p className="text-[10px] font-mono text-red-400">{job.error}</p>
            )}
          </div>
        )}

        {error && <p className="text-[10px] font-mono text-red-400">{error}</p>}
      </div>

      {/* Degraded-mode notice — mirrors the search layer's amber banner treatment. Softer
          tone for a partial LLM run (some transcript windows failed) than a full heuristic
          fallback (no LLM ran at all). */}
      {isDegraded && (
        <div
          className={
            isPartial
              ? 'bg-yellow-950/20 border border-yellow-800/20 rounded-xl p-3 text-xs text-yellow-300/90 font-mono text-center flex items-center justify-center gap-2 animate-fade-in'
              : 'bg-amber-950/30 border border-amber-800/30 rounded-xl p-3 text-xs text-amber-300 font-mono text-center flex items-center justify-center gap-2 animate-fade-in'
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
              <ClipCard key={clip.id} clip={clip} rank={idx + 1} />
            ))}
          </div>
        </div>
      ) : !isRunning ? (
        <div className="bg-canvas-soft/60 border border-hairline rounded-2xl p-10 text-center space-y-2">
          <p className="text-sm text-ink-body">No clips yet for this video.</p>
          <p className="text-xs text-ink-mute">Run Analyze to generate ranked, sentence-clean clip candidates.</p>
        </div>
      ) : null}
    </div>
  );
};
