import React from 'react';

interface AnswerCardProps {
  answer: string;
  /** 1-based indices into the result list, already validated server-side to be in range. */
  citations: number[];
  isLoading?: boolean;
  /** Scroll to and highlight the cited result card. */
  onCitationClick: (resultIndex: number) => void;
}

/**
 * The short synthesized answer above the results.
 *
 * Deliberately quiet: it is a convenience on top of the moments, not a replacement for them.
 * The transcript quotes remain the source of truth and the reason the product exists — so
 * this is one or two lines with visible citations back into the list, never a wall of prose
 * that would tempt someone to trust it instead of the recording. If there's no answer, this
 * component isn't rendered at all (App decides), so there is no empty or "sorry" state here.
 */
export const AnswerCard: React.FC<AnswerCardProps> = ({
  answer,
  citations,
  isLoading,
  onCitationClick,
}) => {
  if (isLoading) {
    return (
      <div className="border-l-2 border-hairline-bright pl-4 py-1 animate-fade-in">
        <div className="eyebrow-mono text-ink-faint">Answer</div>
        <div className="mt-1.5 h-4 w-2/3 rounded-sm bg-canvas-soft animate-pulse" />
      </div>
    );
  }

  return (
    <div className="border-l-2 border-hairline-bright pl-4 py-1 animate-fade-in">
      <div className="eyebrow-mono text-ink-faint">Answer</div>
      <p className="mt-1.5 text-[15px] text-ink leading-relaxed max-w-[68ch]">
        {answer}
        {citations.length > 0 && (
          <span className="ml-1.5 inline-flex gap-1 align-baseline">
            {citations.map((c) => (
              <button
                key={c}
                // 1-based in the label because that's what the model cited and what reads
                // naturally; converted to a 0-based list index at the boundary.
                onClick={() => onCitationClick(c - 1)}
                className="text-[11px] font-mono text-ink-mute hover:text-ink transition-colors duration-100"
                title={`Jump to result ${c}`}
              >
                [{c}]
              </button>
            ))}
          </span>
        )}
      </p>
      <p className="mt-1 text-[10px] font-mono text-ink-faint">
        Summarized from the quotes below — the transcript is the source of truth.
      </p>
    </div>
  );
};
