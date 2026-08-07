import React, { useState } from 'react';
import { ShowNotesOutput, VideoItem, ParsedTranscriptInfo, TranscriptSourceSentence } from '../../../types';
import { useStudioRun } from '../../../hooks/useStudioRun';
import { studioTranscriptSource } from '../../../services/api';
import { Button } from '../../ui/Button';
import { OutputBlock } from '../../ui/OutputBlock';
import { Tag } from '../../ui/Pill';
import { TranscriptSourcePicker } from '../TranscriptSourcePicker';

interface ShowNotesToolProps {
  videos: VideoItem[];
}

export const ShowNotesTool: React.FC<ShowNotesToolProps> = ({ videos }) => {
  const [source, setSource] = useState<'paste' | 'library'>('paste');
  const [transcriptText, setTranscriptText] = useState('');
  const [videoId, setVideoId] = useState('');
  const [sentences, setSentences] = useState<TranscriptSourceSentence[]>([]);
  const [parsed, setParsed] = useState<ParsedTranscriptInfo | null>(null);
  const [durationHint, setDurationHint] = useState('');
  const [episodeTitle, setEpisodeTitle] = useState('');
  const [guestName, setGuestName] = useState('');
  const { output, running, error, run } = useStudioRun<ShowNotesOutput>();

  const handleVideoIdChange = async (id: string) => {
    setVideoId(id);
    if (!id) { setSentences([]); return; }
    try {
      const res = await studioTranscriptSource(id);
      setSentences(res.sentences);
    } catch {
      setSentences([]);
    }
  };

  const canSubmit = !running && (
    (source === 'paste' && transcriptText.trim().length > 0) ||
    (source === 'library' && sentences.length > 0)
  );

  const handleSubmit = () => {
    const inputs: Record<string, any> =
      source === 'library'
        ? { source: 'library', sentences }
        : { source: 'paste', transcript_text: transcriptText, duration_hint_sec: durationHint ? Number(durationHint) : undefined };
    inputs.episode_title = episodeTitle || undefined;
    inputs.guest_name = guestName || undefined;
    run('show_notes', inputs);
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <label className="eyebrow-mono block">Transcript</label>
        <TranscriptSourcePicker
          videos={videos}
          source={source}
          onSourceChange={setSource}
          transcriptText={transcriptText}
          onTranscriptTextChange={setTranscriptText}
          videoId={videoId}
          onVideoIdChange={handleVideoIdChange}
          parsed={parsed}
          onParsed={setParsed}
        />
        {source === 'paste' && parsed && !parsed.has_timestamps && (
          <input
            type="number"
            placeholder="Episode duration in seconds (optional — enables estimated chapter times)"
            value={durationHint}
            onChange={(e) => setDurationHint(e.target.value)}
            className="w-full bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
          />
        )}
        <div className="grid grid-cols-2 gap-2">
          <input
            type="text" placeholder="Episode title (optional)" value={episodeTitle}
            onChange={(e) => setEpisodeTitle(e.target.value)}
            className="bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
          />
          <input
            type="text" placeholder="Guest name (optional)" value={guestName}
            onChange={(e) => setGuestName(e.target.value)}
            className="bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
          />
        </div>
        <Button variant="primary" disabled={!canSubmit} loading={running} onClick={handleSubmit}>
          Generate show notes
        </Button>
      </div>

      {error && (
        <div className="bg-canvas-card/40 border border-danger/30 rounded-sm p-3 text-xs text-danger font-mono">{error}</div>
      )}

      {output && (
        <div className="space-y-4 pt-4 border-t border-hairline">
          <OutputBlock title="Summary" copyText={output.summary}>
            <p>{output.summary}</p>
          </OutputBlock>

          <OutputBlock title="Show Notes" copyText={output.show_notes.join('\n')}>
            <ul className="list-disc list-inside space-y-1">
              {output.show_notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </OutputBlock>

          <OutputBlock
            title="Chapters"
            copyText={output.chapters.map((c) => `${c.time ?? '(no time)'} ${c.title}`).join('\n')}
            badge={
              output.timestamp_mode === 'estimated' ? <Tag tone="warning">estimated</Tag> :
              output.timestamp_mode === 'none' ? <Tag tone="warning">no timestamps</Tag> : undefined
            }
          >
            <div className="space-y-1 font-mono text-xs">
              {output.chapters.map((c, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-ink-body">{c.time ?? '--:--'}</span>
                  <span className="text-ink-body">{c.title}</span>
                  {c.estimated && <Tag tone="warning">est.</Tag>}
                </div>
              ))}
            </div>
          </OutputBlock>

          <OutputBlock title="Title Options" copyText={output.titles.join('\n')}>
            <ul className="list-disc list-inside space-y-1">
              {output.titles.map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          </OutputBlock>

          <OutputBlock title="Promo Blurb" copyText={output.promo}>
            <p>{output.promo}</p>
          </OutputBlock>
        </div>
      )}
    </div>
  );
};
