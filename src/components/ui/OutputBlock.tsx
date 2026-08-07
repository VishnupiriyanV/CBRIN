import React from 'react';
import { RefreshCw } from 'lucide-react';
import { CopyButton } from './CopyButton';
import { cn } from './cn';

interface OutputBlockProps {
  title: string;
  /** Plain-text version of this block's content — omit to hide the copy control (e.g. a
   * flagged reply, which the guardrails deliberately give no copy button). */
  copyText?: string;
  onRegenerate?: () => void;
  regenerating?: boolean;
  badge?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}

// Every STUDIO tool's output is a stack of these — title, per-block copy, per-block
// regenerate, and an optional badge (estimated / over-limit / flagged / degraded).
// creator-tools-integration-spec.md §0.2: copy-per-block is "non-negotiable", regenerate is
// "one block, not the whole job".
export const OutputBlock: React.FC<OutputBlockProps> = ({
  title, copyText, onRegenerate, regenerating = false, badge, className, children,
}) => (
  <div className={cn('bg-canvas-soft border border-hairline rounded-sm p-4 space-y-2', className)}>
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 min-w-0">
        <span className="eyebrow-mono">{title}</span>
        {badge}
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        {onRegenerate && (
          <button
            type="button"
            onClick={onRegenerate}
            disabled={regenerating}
            className="px-2.5 py-1 rounded-sm border border-hairline text-[11px] font-mono text-ink-mute hover:border-hairline-bright hover:text-ink transition-all disabled:opacity-40 inline-flex items-center gap-1.5"
          >
            <RefreshCw className={cn('w-3 h-3', regenerating && 'animate-spin')} />
            Regenerate
          </button>
        )}
        {copyText !== undefined && <CopyButton text={copyText} />}
      </div>
    </div>
    <div className="text-sm text-ink-body whitespace-pre-wrap">{children}</div>
  </div>
);
