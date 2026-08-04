import React from 'react';
import { cn } from './cn';

// The selected/unselected pill recipe from ClipCard.tsx's preset multi-select, extracted so
// STUDIO's platform pickers, formula tags, and flag badges don't each reinvent it.
interface PillProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
}

export const Pill: React.FC<PillProps> = ({ selected = false, className, children, ...rest }) => (
  <button
    type="button"
    className={cn(
      'px-3 py-1 rounded-full text-[11px] font-mono border transition-all',
      selected
        ? 'border-accent-sunset bg-accent-sunset/10 text-accent-sunset'
        : 'border-hairline text-ink-mute hover:border-hairline-bright hover:text-ink',
      className
    )}
    {...rest}
  >
    {children}
  </button>
);

// Non-interactive variant for read-only tags (formula labels, flag reasons).
export const Tag: React.FC<React.HTMLAttributes<HTMLSpanElement> & { tone?: 'default' | 'warning' | 'danger' }> = ({
  tone = 'default',
  className,
  children,
  ...rest
}) => {
  const toneClasses = {
    default: 'border-hairline text-ink-mute',
    warning: 'border-amber-500/40 text-amber-400 bg-amber-500/10',
    danger: 'border-red-500/40 text-red-400 bg-red-500/10',
  }[tone];
  return (
    <span
      className={cn('px-2 py-0.5 rounded-full text-[10px] font-mono border inline-block', toneClasses, className)}
      {...rest}
    >
      {children}
    </span>
  );
};
