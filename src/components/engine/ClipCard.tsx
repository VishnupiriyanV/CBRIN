import React, { useEffect, useRef, useState } from 'react';
import { Download, Play, ThumbsDown, ThumbsUp, Loader2, Scissors } from 'lucide-react';
import { BoundarySnap, ClipCandidate, RENDER_PRESETS, RenderPreset } from '../../types';
import { engineRender, engineGetJob, engineClipFileUrl, engineSendFeedback, engineAdjustClip } from '../../services/api';
import { ScoreBreakdown } from './ScoreBreakdown';
import { ClipGuarantees } from './ClipGuarantees';

interface ClipCardProps {
  clip: ClipCandidate;
  rank: number;
  // Adjusting replaces the clip server-side, so the parent owns the updated copy — without
  // this the card's own bounds would drift from the list the render button acts on.
  onAdjusted?: (clip: ClipCandidate) => void;
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

// Matches word_timing.SNAP_WINDOW_SEC. Only used to word the refusal message — the bound
// itself is enforced server-side, so a drift here misinforms, it doesn't misbehave.
const SNAP_WINDOW_LABEL = '1.2s';

function formatDelta(sec: number): string {
  return `${sec > 0 ? '+' : '−'}${Math.abs(sec).toFixed(2)}s`;
}

/**
 * Turn a BoundarySnap into something worth reading.
 *
 * The distinction that matters: "nothing moved" and "we refused to move it" look identical
 * in the timestamps, and only the second one is the user's business — they dragged a handle
 * into a silence and the snap declined rather than yanking it across the gap. `reason` is two
 * per-edge clauses joined by "; " (start first, see word_timing.snap_to_words), so each edge
 * gets explained next to its own number instead of dumping the raw backend string on screen.
 */
function describeSnap(snap: BoundarySnap): { held: boolean; headline: string; notes: string[] } {
  if (snap.reason === 'no word timing for this video') {
    return {
      held: true,
      headline: 'Saved exactly as entered',
      notes: ['This video has no word-level timing yet, so there was no word edge to snap to.'],
    };
  }

  const [startReason = '', endReason = ''] = snap.reason.split(';').map((r) => r.trim());
  const notes: string[] = [];
  if (startReason.startsWith('no word start')) {
    notes.push(`In-point kept where you put it — no word starts within ${SNAP_WINDOW_LABEL} of it.`);
  }
  if (endReason.startsWith('no word end')) {
    notes.push(`Out-point kept where you put it — no word ends within ${SNAP_WINDOW_LABEL} of it.`);
  }

  const moves: string[] = [];
  if (snap.start_moved_by) moves.push(`in ${formatDelta(snap.start_moved_by)}`);
  if (snap.end_moved_by) moves.push(`out ${formatDelta(snap.end_moved_by)}`);

  if (moves.length === 0) {
    return {
      held: true,
      // Both edges were searched and matched; they were already sitting on the word edge.
      headline: notes.length > 0 ? 'Bounds unchanged' : 'Already on the word boundary',
      notes,
    };
  }
  return { held: false, headline: `Snapped ${moves.join(', ')}`, notes };
}

export const ClipCard: React.FC<ClipCardProps> = ({ clip, rank, onAdjusted }) => {
  const [selectedPresets, setSelectedPresets] = useState<RenderPreset[]>(['tiktok']);
  const [trimOpen, setTrimOpen] = useState(false);
  const [startInput, setStartInput] = useState(clip.start_sec.toFixed(1));
  const [endInput, setEndInput] = useState(clip.end_sec.toFixed(1));
  const [adjusting, setAdjusting] = useState(false);
  const [adjustError, setAdjustError] = useState<string | null>(null);
  const [snap, setSnap] = useState<BoundarySnap | null>(null);
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

  // Resync the fields whenever the clip's bounds change under us — the snap almost always
  // lands somewhere other than what was typed, and fields left showing the request would
  // claim a trim that isn't what will be rendered.
  useEffect(() => {
    setStartInput(clip.start_sec.toFixed(1));
    setEndInput(clip.end_sec.toFixed(1));
  }, [clip.start_sec, clip.end_sec]);

  const applyTrim = async () => {
    const start = Number(startInput);
    const end = Number(endInput);
    if (!Number.isFinite(start) || !Number.isFinite(end) || startInput.trim() === '' || endInput.trim() === '') {
      setAdjustError('Enter both bounds in seconds.');
      return;
    }
    if (start < 0) {
      setAdjustError('In-point cannot be negative.');
      return;
    }
    if (end <= start) {
      setAdjustError('Out-point must come after the in-point.');
      return;
    }
    setAdjusting(true);
    setAdjustError(null);
    try {
      const updated = await engineAdjustClip(clip.id, start, end);
      setSnap(updated.boundary_snap ?? null);
      onAdjusted?.(updated);
    } catch (err: any) {
      setAdjustError(err.message || 'Adjust failed');
    } finally {
      setAdjusting(false);
    }
  };

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

      // Stop whatever was already polling before starting a new poll. Without this a second
      // Render click orphaned the first interval — and because the callback cleared
      // `pollRef.current` rather than its OWN handle, when that orphan's job finished it
      // killed the interval watching the job the user was actually waiting on. The newer
      // render then sat at its last status forever despite having completed server-side,
      // while the orphan kept polling and overwriting the UI with the old job's state.
      if (pollRef.current) clearInterval(pollRef.current);

      const handle = setInterval(async () => {
        const stop = () => {
          clearInterval(handle);
          if (pollRef.current === handle) pollRef.current = null;
        };
        try {
          const job = await engineGetJob(job_id);
          // A stale interval must not write over the current job's state either.
          if (pollRef.current !== handle) {
            clearInterval(handle);
            return;
          }
          setRenderStatus(job.status);
          setRenderMessage(job.message || job.stage);
          if (job.status === 'done' || job.status === 'failed') {
            stop();
            if (job.status === 'done' && job.result?.presets) {
              setRenderedPresets(new Set(Object.keys(job.result.presets)));
            }
          }
        } catch (err) {
          console.error('Render job poll failed:', err);
          stop();
        }
      }, 1500);
      pollRef.current = handle;
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

  const snapDescription = snap ? describeSnap(snap) : null;

  return (
    <div className="bg-canvas-card border border-hairline hover:border-hairline-bright rounded-sm p-5 space-y-4 transition-colors animate-fade-in">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="w-6 h-6 rounded-sm bg-canvas-soft border border-hairline flex items-center justify-center text-[10px] font-mono text-ink-body shrink-0">
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
                  <span className="text-ink-body" title="Word-level timing unavailable — using sentence-level boundaries">
                    approx. timing
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setTrimOpen((open) => !open)}
            title="Adjust trim boundaries"
            className={`p-1.5 rounded-sm border transition-colors ${trimOpen ? 'border-hairline-bright bg-canvas-soft text-ink' : 'border-hairline text-ink-mute hover:text-ink hover:border-hairline-bright'}`}
          >
            <Scissors className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => sendFeedback('winner')}
            disabled={feedbackSent !== null}
            title="Mark as a winner"
            className={`p-1.5 rounded-sm border transition-colors ${feedbackSent === 'winner' ? 'border-ink/60 bg-ink/10 text-ink' : 'border-hairline text-ink-mute hover:text-ink hover:border-hairline-bright'}`}
          >
            <ThumbsUp className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => sendFeedback('dud')}
            disabled={feedbackSent !== null}
            title="Mark as a dud"
            className={`p-1.5 rounded-sm border transition-colors ${feedbackSent === 'dud' ? 'border-danger/60 bg-danger/10 text-danger' : 'border-hairline text-ink-mute hover:text-ink hover:border-hairline-bright'}`}
          >
            <ThumbsDown className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {trimOpen && (
        <div className="bg-canvas-soft/60 border border-hairline rounded-sm p-3 space-y-2.5 animate-fade-in">
          <div className="flex items-end gap-2">
            <label className="flex-1 space-y-1">
              <span className="block text-[9px] font-mono uppercase tracking-wide text-ink-mute">In (s)</span>
              <input
                type="number"
                step="0.1"
                min="0"
                value={startInput}
                onChange={(e) => setStartInput(e.target.value)}
                className="w-full bg-canvas-card border border-hairline focus:border-hairline-bright rounded-sm px-2 py-1 text-xs font-mono text-ink outline-none"
              />
            </label>
            <label className="flex-1 space-y-1">
              <span className="block text-[9px] font-mono uppercase tracking-wide text-ink-mute">Out (s)</span>
              <input
                type="number"
                step="0.1"
                min="0"
                value={endInput}
                onChange={(e) => setEndInput(e.target.value)}
                className="w-full bg-canvas-card border border-hairline focus:border-hairline-bright rounded-sm px-2 py-1 text-xs font-mono text-ink outline-none"
              />
            </label>
            <button
              onClick={applyTrim}
              disabled={adjusting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-hairline hover:border-hairline-bright bg-canvas-card text-[10px] font-mono text-ink-body hover:text-ink transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            >
              {adjusting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Scissors className="w-3.5 h-3.5" />}
              <span>Snap</span>
            </button>
          </div>

          {adjustError && <p className="text-[10px] font-mono text-danger">{adjustError}</p>}

          {snapDescription && !adjustError && (
            <div className="space-y-1">
              {/* Muted for a held boundary, brighter for one that moved — the two outcomes are
                  indistinguishable from the numbers alone, which is the whole reason this
                  panel reports the reason at all. */}
              <p className={`text-[10px] font-mono ${snapDescription.held ? 'text-ink-mute' : 'text-ink-body'}`}>
                {snapDescription.headline}
              </p>
              {snapDescription.notes.map((note) => (
                <p key={note} className="text-[10px] leading-relaxed text-ink-mute">{note}</p>
              ))}
            </div>
          )}

          <p className="text-[9px] leading-relaxed text-ink-mute/70">
            Each boundary snaps to the nearest word edge within {SNAP_WINDOW_LABEL}. A boundary
            dropped in silence is left exactly where you put it rather than dragged across the gap.
          </p>
        </div>
      )}

      {clip.quotable_line && (
        <blockquote className="text-xs text-ink-body italic border-l-2 border-accent-sunset/50 pl-3 py-0.5">
          "{clip.quotable_line}"
        </blockquote>
      )}

      <ScoreBreakdown signals={clip.signals} reason={clip.reason} />

      {/* Proven properties, kept separate from the scored signals above. These are not
          weighted into the composite — they either hold or they don't. */}
      <ClipGuarantees clip={clip} />

      <div className="pt-3 border-t border-hairline/60 space-y-2.5">
        <div className="flex flex-wrap gap-1.5">
          {RENDER_PRESETS.map((preset) => (
            <button
              key={preset}
              onClick={() => togglePreset(preset)}
              className={`px-2.5 py-1 rounded-sm border text-[10px] font-mono transition-all ${
                selectedPresets.includes(preset)
                  ? 'border-accent-sunset bg-accent-sunset/10 text-ink-body'
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
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-sm border border-accent-sunset/40 bg-accent-sunset/10 hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-ink-body transition-all disabled:opacity-40 disabled:cursor-not-allowed"
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
            <span className="text-[10px] font-mono text-danger">{renderMessage}</span>
          )}
        </div>

        {renderedPresets.size > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {Array.from(renderedPresets).map((preset) => (
              <a
                key={preset}
                href={engineClipFileUrl(clip.id, preset)}
                download={`${clip.id}-${preset}.mp4`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-accent-sunset/40 bg-accent-sunset/10 hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-[10px] font-semibold text-ink-body transition-all"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Download {PRESET_LABELS[preset as RenderPreset] || preset}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
