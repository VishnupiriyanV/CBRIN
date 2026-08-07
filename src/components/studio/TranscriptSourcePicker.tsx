import React, { useEffect, useRef } from 'react';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { VideoItem, ParsedTranscriptInfo } from '../../types';
import { studioParseTranscript } from '../../services/api';
import { Pill } from '../ui/Pill';
import { CappedTextarea } from '../ui/CappedTextarea';

interface TranscriptSourcePickerProps {
  videos: VideoItem[];
  source: 'paste' | 'library';
  onSourceChange: (s: 'paste' | 'library') => void;
  transcriptText: string;
  onTranscriptTextChange: (t: string) => void;
  videoId: string;
  onVideoIdChange: (id: string) => void;
  parsed: ParsedTranscriptInfo | null;
  onParsed: (p: ParsedTranscriptInfo | null) => void;
  /** Tool 6's hard requirement (creator-tools-integration-spec.md §6): block before a run is
   * spent, not after a 422 comes back. */
  requireTimestamps?: boolean;
}

// Shared by the Show Notes and Clip-Moment Finder tools — both accept either a fresh paste
// (SRT/VTT/plain, classified via the parse_transcript pre-flight) or an already-indexed
// library video (real cue data, no parsing needed).
export const TranscriptSourcePicker: React.FC<TranscriptSourcePickerProps> = ({
  videos, source, onSourceChange, transcriptText, onTranscriptTextChange,
  videoId, onVideoIdChange, parsed, onParsed, requireTimestamps = false,
}) => {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const indexedVideos = videos.filter((v) => v.status === 'fully_indexed');

  useEffect(() => {
    if (source !== 'paste') return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!transcriptText.trim()) {
      onParsed(null);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const info = await studioParseTranscript(transcriptText);
        onParsed(info);
      } catch {
        onParsed(null);
      }
    }, 500);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcriptText, source]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <Pill selected={source === 'paste'} onClick={() => onSourceChange('paste')}>Paste transcript</Pill>
        <Pill selected={source === 'library'} onClick={() => onSourceChange('library')} disabled={indexedVideos.length === 0}>
          Use an indexed video
        </Pill>
      </div>

      {source === 'paste' ? (
        <div className="space-y-2">
          <CappedTextarea
            rows={8}
            placeholder="Paste an SRT, WebVTT, or plain-text transcript..."
            value={transcriptText}
            onChange={(e) => onTranscriptTextChange(e.target.value)}
          />
          {parsed && (
            <div className={`text-[11px] font-mono flex items-center gap-1.5 ${parsed.has_timestamps ? 'text-ink' : requireTimestamps ? 'text-danger' : 'text-ink-body'}`}>
              {parsed.has_timestamps ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
              {parsed.has_timestamps
                ? `${parsed.format.toUpperCase()} detected — ${parsed.sentence_count} cue(s), real timestamps.`
                : requireTimestamps
                  ? 'No timestamps found. This tool needs SRT/VTT or a timestamped export — plain text can\'t produce a usable moment map.'
                  : 'No timestamps found — plain text. Chapters will have no times unless you supply an episode duration below.'}
            </div>
          )}
        </div>
      ) : (
        <select
          value={videoId}
          onChange={(e) => onVideoIdChange(e.target.value)}
          className="w-full bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink focus:outline-none focus:border-hairline-bright"
        >
          <option value="">Select an indexed video…</option>
          {indexedVideos.map((v) => (
            <option key={v.id} value={v.id}>{v.title}</option>
          ))}
        </select>
      )}
    </div>
  );
};
