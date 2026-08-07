import React, { useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { RepliesOutput } from '../../../types';
import { useStudioRun } from '../../../hooks/useStudioRun';
import { Button } from '../../ui/Button';
import { CopyButton } from '../../ui/CopyButton';
import { Tag } from '../../ui/Pill';

const TONES = ['warm', 'short', 'witty', 'professional'];
const LENGTHS: { value: string; label: string }[] = [
  { value: 'one-liner', label: 'One-liner' },
  { value: 'considered', label: 'Considered' },
];

export const RepliesTool: React.FC = () => {
  const [commentsText, setCommentsText] = useState('');
  const [tone, setTone] = useState('warm');
  const [length, setLength] = useState('one-liner');
  const { output, running, error, run, regenerate, regeneratingBlock } = useStudioRun<RepliesOutput>();

  const comments = commentsText.split('\n').map((c) => c.trim()).filter(Boolean);
  const canSubmit = comments.length > 0 && !running;

  const handleSubmit = () => {
    run('replies', { comments, tone, length });
  };

  const safeReplies = output?.replies.filter((r) => r.flag === null) ?? [];
  const flaggedReplies = output?.replies.filter((r) => r.flag !== null) ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <label className="eyebrow-mono block">Comments (one per line, up to ~50)</label>
        <textarea
          rows={8}
          placeholder={'Great video, learned a lot!\nCan you make one about X?\n...'}
          value={commentsText}
          onChange={(e) => setCommentsText(e.target.value)}
          className="w-full bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink placeholder:text-ink-mute resize-y focus:outline-none focus:border-hairline-bright"
        />
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-mono text-ink-mute">Tone</span>
            <select value={tone} onChange={(e) => setTone(e.target.value)} className="bg-canvas-soft border border-hairline rounded-sm px-2.5 py-1 text-[11px] font-mono text-ink">
              {TONES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-mono text-ink-mute">Length</span>
            <select value={length} onChange={(e) => setLength(e.target.value)} className="bg-canvas-soft border border-hairline rounded-sm px-2.5 py-1 text-[11px] font-mono text-ink">
              {LENGTHS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
            </select>
          </div>
        </div>
        <Button variant="primary" disabled={!canSubmit} loading={running} onClick={handleSubmit}>
          Suggest replies
        </Button>
      </div>

      {error && (
        <div className="bg-canvas-card/40 border border-danger/30 rounded-sm p-3 text-xs text-danger font-mono">{error}</div>
      )}

      {output && (
        <div className="space-y-6 pt-4 border-t border-hairline">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="eyebrow-mono">Suggested Replies ({safeReplies.length})</span>
              <button
                onClick={() => regenerate(output.run_id, 'replies')}
                disabled={regeneratingBlock === 'replies'}
                className="text-[11px] font-mono text-ink-mute hover:text-ink disabled:opacity-40"
              >
                {regeneratingBlock === 'replies' ? 'Regenerating…' : 'Regenerate all'}
              </button>
            </div>
            <div className="space-y-2">
              {safeReplies.map((r, i) => (
                <div key={i} className="bg-canvas-soft border border-hairline rounded-sm p-3 space-y-2">
                  <p className="text-xs text-ink-mute">"{r.comment}"</p>
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm text-ink">{r.suggested_reply}</p>
                    {r.suggested_reply && <CopyButton text={r.suggested_reply} className="shrink-0" />}
                  </div>
                </div>
              ))}
              {safeReplies.length === 0 && <p className="text-xs text-ink-mute">No comments were safe for an AI-suggested reply.</p>}
            </div>
          </div>

          {flaggedReplies.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-ink-body" />
                <span className="eyebrow-mono text-ink-body">Handle Personally ({flaggedReplies.length})</span>
              </div>
              {/* No copy button, no regenerate — these comments were never sent to the
                  reply-generation call at all (structural guardrail, not a UI omission). */}
              <div className="space-y-2">
                {flaggedReplies.map((r, i) => (
                  <div key={i} className="bg-canvas-card/20 border border-hairline-bright/30 rounded-sm p-3 space-y-1">
                    <div className="flex items-center gap-2">
                      <Tag tone="danger">{r.flag}</Tag>
                      {r.flag_reason && <span className="text-[11px] text-ink-body">{r.flag_reason}</span>}
                    </div>
                    <p className="text-xs text-ink-body">"{r.comment}"</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
