import React, { useState } from 'react';
import { TitlesOutput } from '../../../types';
import { useStudioRun } from '../../../hooks/useStudioRun';
import { Button } from '../../ui/Button';
import { OutputBlock } from '../../ui/OutputBlock';
import { Tag } from '../../ui/Pill';

export const TitlesTool: React.FC = () => {
  const [topic, setTopic] = useState('');
  const [niche, setNiche] = useState('');
  const [audienceLevel, setAudienceLevel] = useState('');
  const [pastTitles, setPastTitles] = useState('');
  const { output, running, error, run } = useStudioRun<TitlesOutput>();

  const canSubmit = topic.trim().length > 0 && !running;

  const handleSubmit = () => {
    run('titles', {
      topic, niche: niche || undefined, audience_level: audienceLevel || undefined,
      past_titles: pastTitles.split('\n').map((t) => t.trim()).filter(Boolean),
    });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <input
          type="text" placeholder="Video topic" value={topic} onChange={(e) => setTopic(e.target.value)}
          className="w-full bg-canvas-soft border border-hairline rounded-lg p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
        />
        <div className="grid grid-cols-2 gap-2">
          <input
            type="text" placeholder="Niche (optional)" value={niche} onChange={(e) => setNiche(e.target.value)}
            className="bg-canvas-soft border border-hairline rounded-lg p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
          />
          <input
            type="text" placeholder="Audience level (optional)" value={audienceLevel} onChange={(e) => setAudienceLevel(e.target.value)}
            className="bg-canvas-soft border border-hairline rounded-lg p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
          />
        </div>
        <textarea
          rows={3} placeholder="Past titles that performed well, one per line (optional)"
          value={pastTitles} onChange={(e) => setPastTitles(e.target.value)}
          className="w-full bg-canvas-soft border border-hairline rounded-lg p-2.5 text-sm text-ink placeholder:text-ink-mute resize-y focus:outline-none focus:border-hairline-bright"
        />
        <Button variant="primary" disabled={!canSubmit} loading={running} onClick={handleSubmit}>
          Generate titles &amp; hooks
        </Button>
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-800/30 rounded-lg p-3 text-xs text-red-300 font-mono">{error}</div>
      )}

      {output && (
        <div className="space-y-4 pt-4 border-t border-hairline">
          <OutputBlock title="Titles" copyText={output.titles.map((t) => t.text).join('\n')}>
            <div className="space-y-3">
              {output.titles.map((t, i) => (
                <div key={i} className="space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-ink font-medium">{t.text}</p>
                    <Tag>{t.formula.replace(/_/g, ' ')}</Tag>
                    <Tag tone={t.over_limit ? 'warning' : 'default'}>{t.char_count} chars</Tag>
                  </div>
                  {t.promise && <p className="text-[11px] text-ink-mute">Must deliver: {t.promise}</p>}
                </div>
              ))}
            </div>
          </OutputBlock>

          <OutputBlock title="Hooks" copyText={output.hooks.map((h) => h.text).join('\n')}>
            <div className="space-y-2">
              {output.hooks.map((h, i) => (
                <p key={i}><Tag>{h.style}</Tag> {h.text}</p>
              ))}
            </div>
          </OutputBlock>

          <OutputBlock title="Thumbnail Text (text only — no image generation)" copyText={output.thumbnail_text.map((t) => t.text).join('\n')}>
            <div className="flex flex-wrap gap-2">
              {output.thumbnail_text.map((t, i) => (
                <Tag key={i} tone={t.over_word_limit ? 'warning' : 'default'}>{t.text}</Tag>
              ))}
            </div>
          </OutputBlock>
        </div>
      )}
    </div>
  );
};
