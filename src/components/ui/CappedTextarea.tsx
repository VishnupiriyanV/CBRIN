import React, { useMemo } from 'react';
import { cn } from './cn';

// creator-tools-integration-spec.md §0.5: hard input cap ~15k words. The backend rejects
// oversized input with a 422 before any LLM call is made (usage.py), but surfacing the
// count live means the creator sees the problem before they hit submit, not after a
// wasted round-trip.
const DEFAULT_MAX_WORDS = 15000;

interface CappedTextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  maxWords?: number;
}

function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

export const CappedTextarea: React.FC<CappedTextareaProps> = ({
  maxWords = DEFAULT_MAX_WORDS, value, className, ...rest
}) => {
  const words = useMemo(() => countWords(String(value ?? '')), [value]);
  const overCap = words > maxWords;
  const nearCap = !overCap && words > maxWords * 0.9;

  return (
    <div className="space-y-1.5">
      <textarea
        value={value}
        className={cn(
          'w-full bg-canvas-soft border rounded-lg p-3 text-sm text-ink placeholder:text-ink-mute resize-y',
          'focus:outline-none focus:border-hairline-bright',
          overCap ? 'border-red-500/50' : 'border-hairline',
          className
        )}
        {...rest}
      />
      <div className={cn('text-[11px] font-mono text-right', overCap ? 'text-red-400' : nearCap ? 'text-amber-400' : 'text-ink-mute')}>
        {words.toLocaleString()} / {maxWords.toLocaleString()} words
        {overCap && ' — trim before submitting'}
      </div>
    </div>
  );
};
