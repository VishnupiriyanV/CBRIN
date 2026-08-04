import React, { useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { RepurposerOutput } from '../../../types';
import { useStudioRun } from '../../../hooks/useStudioRun';
import { Button } from '../../ui/Button';
import { CappedTextarea } from '../../ui/CappedTextarea';
import { OutputBlock } from '../../ui/OutputBlock';
import { Tag } from '../../ui/Pill';

export const RepurposerTool: React.FC = () => {
  const [text, setText] = useState('');
  const [emphasize, setEmphasize] = useState('');
  const { output, running, error, run, regenerate, regeneratingBlock } = useStudioRun<RepurposerOutput>();

  const canSubmit = text.trim().length > 0 && !running;

  const handleSubmit = () => {
    run('repurposer', { text, emphasize: emphasize || undefined });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <label className="eyebrow-mono block">Newsletter or blog post</label>
        <CappedTextarea
          rows={12}
          placeholder="Paste the full text of a newsletter or blog post…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <input
          type="text"
          placeholder="Emphasize a specific angle (optional)"
          value={emphasize}
          onChange={(e) => setEmphasize(e.target.value)}
          className="w-full bg-canvas-soft border border-hairline rounded-lg p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
        />
        <Button variant="primary" disabled={!canSubmit} loading={running} onClick={handleSubmit}>
          Repurpose
        </Button>
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-800/30 rounded-lg p-3 text-xs text-red-300 font-mono">{error}</div>
      )}

      {output && (
        <div className="space-y-4 pt-4 border-t border-hairline">
          {(output.guardrail_notes?.frameworks_missing?.length ?? 0) > 0 && (
            <div className="bg-amber-950/30 border border-amber-800/30 rounded-lg p-3 text-xs text-amber-300 font-mono flex items-start gap-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>
                These named framework(s) from the source didn't survive verbatim into the output:{' '}
                {output.guardrail_notes.frameworks_missing!.join(', ')}.
              </span>
            </div>
          )}
          {output.guardrail_notes?.banned_words_removed?.length ? (
            <div className="bg-amber-950/30 border border-amber-800/30 rounded-lg p-3 text-xs text-amber-300 font-mono">
              Removed banned word(s) from the output: {output.guardrail_notes.banned_words_removed.join(', ')}.
            </div>
          ) : null}

          <OutputBlock
            title="LinkedIn Post"
            copyText={`${output.linkedin.hook}\n\n${output.linkedin.body}\n\n${output.linkedin.cta}`}
            onRegenerate={() => regenerate(output.run_id, 'linkedin')}
            regenerating={regeneratingBlock === 'linkedin'}
          >
            <p className="font-medium text-ink mb-1">{output.linkedin.hook}</p>
            <p>{output.linkedin.body}</p>
            <p className="text-ink-mute mt-1">{output.linkedin.cta}</p>
          </OutputBlock>

          <OutputBlock
            title="X / Twitter Thread"
            copyText={output.thread.map((t) => `${t.n}. ${t.text}`).join('\n\n')}
            onRegenerate={() => regenerate(output.run_id, 'thread')}
            regenerating={regeneratingBlock === 'thread'}
          >
            <div className="space-y-2">
              {output.thread.map((t) => (
                <p key={t.n}><span className="text-ink-mute">{t.n}.</span> {t.text}</p>
              ))}
            </div>
          </OutputBlock>

          <OutputBlock
            title="Short-form Notes"
            copyText={output.notes.join('\n\n')}
            onRegenerate={() => regenerate(output.run_id, 'notes')}
            regenerating={regeneratingBlock === 'notes'}
          >
            <div className="space-y-2">
              {output.notes.map((n, i) => <p key={i}>{n}</p>)}
            </div>
          </OutputBlock>

          <OutputBlock
            title="Instagram Carousel Outline"
            copyText={`${output.carousel.title}\n\n${output.carousel.slides.map((s) => `Slide ${s.n}: ${s.headline}\n${s.body}`).join('\n\n')}\n\nCaption: ${output.carousel.caption}`}
            onRegenerate={() => regenerate(output.run_id, 'carousel')}
            regenerating={regeneratingBlock === 'carousel'}
          >
            <p className="font-medium text-ink mb-2">{output.carousel.title}</p>
            <div className="space-y-2">
              {output.carousel.slides.map((s) => (
                <div key={s.n}>
                  <Tag>Slide {s.n}</Tag>
                  <p className="font-medium text-ink mt-1">{s.headline}</p>
                  <p>{s.body}</p>
                </div>
              ))}
            </div>
            <p className="text-ink-mute mt-2">{output.carousel.caption}</p>
          </OutputBlock>
        </div>
      )}
    </div>
  );
};
