import React, { useState } from 'react';
import { CaptionResult, CaptionsOutput } from '../../../types';
import { useStudioRun } from '../../../hooks/useStudioRun';
import { Button } from '../../ui/Button';
import { CappedTextarea } from '../../ui/CappedTextarea';
import { OutputBlock } from '../../ui/OutputBlock';
import { Pill, Tag } from '../../ui/Pill';

const PLATFORMS: { id: string; label: string }[] = [
  { id: 'tiktok', label: 'TikTok' },
  { id: 'instagram', label: 'Instagram' },
  { id: 'youtube_short', label: 'YouTube Shorts' },
  { id: 'youtube_long', label: 'YouTube (long-form)' },
  { id: 'x', label: 'X' },
  { id: 'linkedin', label: 'LinkedIn' },
];

function isCaptionResult(v: unknown): v is CaptionResult {
  return typeof v === 'object' && v !== null && 'caption' in v;
}

export const CaptionsTool: React.FC = () => {
  const [text, setText] = useState('');
  const [cta, setCta] = useState('');
  const [platforms, setPlatforms] = useState<string[]>(PLATFORMS.map((p) => p.id));
  const { output, running, error, run, regenerate, regeneratingBlock } = useStudioRun<CaptionsOutput>();

  const canSubmit = text.trim().length > 0 && platforms.length > 0 && !running;

  const togglePlatform = (id: string) => {
    setPlatforms((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  };

  const handleSubmit = () => {
    run('captions', { text, cta: cta || undefined, platforms });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <label className="eyebrow-mono block">Caption or description</label>
        <CappedTextarea
          rows={6}
          placeholder="Paste one caption or video description…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <input
          type="text" placeholder="CTA to preserve/adapt (optional)" value={cta}
          onChange={(e) => setCta(e.target.value)}
          className="w-full bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
        />
        <div className="flex flex-wrap gap-1.5">
          {PLATFORMS.map((p) => (
            <Pill key={p.id} selected={platforms.includes(p.id)} onClick={() => togglePlatform(p.id)}>
              {p.label}
            </Pill>
          ))}
        </div>
        <Button variant="primary" disabled={!canSubmit} loading={running} onClick={handleSubmit}>
          Reformat for {platforms.length} platform{platforms.length === 1 ? '' : 's'}
        </Button>
      </div>

      {error && (
        <div className="bg-canvas-card/40 border border-danger/30 rounded-sm p-3 text-xs text-danger font-mono">{error}</div>
      )}

      {output && (
        <div className="space-y-4 pt-4 border-t border-hairline">
          {PLATFORMS.filter((p) => isCaptionResult(output[p.id])).map((p) => {
            const result = output[p.id] as CaptionResult;
            return (
              <OutputBlock
                key={p.id}
                title={p.label}
                copyText={`${result.caption}\n\n${result.hashtags.join(' ')}`}
                onRegenerate={() => regenerate(output.run_id as string, p.id)}
                regenerating={regeneratingBlock === p.id}
                badge={<Tag tone={result.over_limit ? 'warning' : 'default'}>{result.char_count}/{result.char_limit}</Tag>}
              >
                <p>{result.caption}</p>
                {result.hashtags.length > 0 && (
                  <p className="text-ink-body mt-1">{result.hashtags.join(' ')}</p>
                )}
              </OutputBlock>
            );
          })}
        </div>
      )}
    </div>
  );
};
