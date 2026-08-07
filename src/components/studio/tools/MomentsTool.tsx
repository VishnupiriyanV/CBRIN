import React, { useState } from 'react';
import { MomentsOutput, VideoItem, ParsedTranscriptInfo, TranscriptSourceSentence } from '../../../types';
import { useStudioRun } from '../../../hooks/useStudioRun';
import { studioTranscriptSource } from '../../../services/api';
import { Button } from '../../ui/Button';
import { OutputBlock } from '../../ui/OutputBlock';
import { Tag } from '../../ui/Pill';
import { TranscriptSourcePicker } from '../TranscriptSourcePicker';

interface MomentsToolProps {
  videos: VideoItem[];
}

const CLIP_LENGTHS = ['15', '30', '60'];

export const MomentsTool: React.FC<MomentsToolProps> = ({ videos }) => {
  const [source, setSource] = useState<'paste' | 'library'>('paste');
  const [transcriptText, setTranscriptText] = useState('');
  const [videoId, setVideoId] = useState('');
  const [sentences, setSentences] = useState<TranscriptSourceSentence[]>([]);
  const [parsed, setParsed] = useState<ParsedTranscriptInfo | null>(null);
  const [streamTopic, setStreamTopic] = useState('');
  const [clipLength, setClipLength] = useState('30');
  const { output, running, error, run } = useStudioRun<MomentsOutput>();

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

  // Hard requirement (guardrail 3): block before spending a run, not after a 422.
  const timestampsMissing = source === 'paste' ? !!parsed && !parsed.has_timestamps : false;
  const canSubmit = !running && !timestampsMissing && (
    (source === 'paste' && transcriptText.trim().length > 0) ||
    (source === 'library' && sentences.length > 0)
  );

  const handleSubmit = () => {
    const inputs: Record<string, any> =
      source === 'library'
        ? { source: 'library', sentences }
        : { source: 'paste', transcript_text: transcriptText };
    inputs.stream_topic = streamTopic || undefined;
    inputs.clip_length_target = clipLength;
    run('moments', inputs);
  };

  return (
    <div className="space-y-6">
      <div className="bg-canvas-soft border border-hairline rounded-sm p-3 text-xs text-ink-mute">
        We find the moments. You cut them in 5 minutes instead of scrubbing for 3 hours. <strong className="text-ink">No video is produced here.</strong>
      </div>

      <div className="space-y-3">
        <label className="eyebrow-mono block">Timestamped transcript (required)</label>
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
          requireTimestamps
        />
        <div className="grid grid-cols-2 gap-2">
          <input
            type="text" placeholder="Stream topic (optional)" value={streamTopic}
            onChange={(e) => setStreamTopic(e.target.value)}
            className="bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright"
          />
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-mono text-ink-mute shrink-0">Target length</span>
            <select value={clipLength} onChange={(e) => setClipLength(e.target.value)} className="bg-canvas-soft border border-hairline rounded-sm px-2.5 py-1 text-[11px] font-mono text-ink flex-1">
              {CLIP_LENGTHS.map((s) => <option key={s} value={s}>{s}s</option>)}
            </select>
          </div>
        </div>
        <Button variant="primary" disabled={!canSubmit} loading={running} onClick={handleSubmit}>
          Find clip-worthy moments
        </Button>
      </div>

      {error && (
        <div className="bg-canvas-card/40 border border-danger/30 rounded-sm p-3 text-xs text-danger font-mono">{error}</div>
      )}

      {output && (
        <div className="space-y-3 pt-4 border-t border-hairline">
          <span className="eyebrow-mono">Moment Map ({output.moments.length})</span>
          {output.moments.map((m, i) => (
            <OutputBlock
              key={i}
              title={`${m.start} – ${m.end}`}
              copyText={`${m.start}-${m.end}  ${m.suggested_title}  (${m.type}, score ${m.score})`}
              badge={
                <div className="flex items-center gap-1">
                  <Tag>{m.type}</Tag>
                  {m.visual_dependent && <Tag tone="warning">visual-dependent</Tag>}
                </div>
              }
            >
              <p className="font-medium text-ink">{m.suggested_title}</p>
              <p className="text-ink-mute">{m.reason}</p>
              <p className="text-[11px] text-ink-mute mt-1">Score: {m.score}/10</p>
            </OutputBlock>
          ))}
        </div>
      )}
    </div>
  );
};
