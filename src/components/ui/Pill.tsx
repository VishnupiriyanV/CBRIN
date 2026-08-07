import React from 'react';
import { cn } from './cn';

// Named `Pill` for continuity with existing call sites, but no longer pill-shaped —
// STRATEGY.md §8 locks the app to a single 2px radius. `rounded-sm` appeared 94 times
// in src/ and was the main reason every surface read as the same templated capsule soup.
interface PillProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
}

export const Pill: React.FC<PillProps> = ({ selected = false, className, children, ...rest }) => (
  <button
    type="button"
    className={cn(
      'px-2.5 py-1 rounded-sm text-[11px] border transition-colors duration-100',
      selected
        ? 'border-ink bg-ink text-canvas font-medium'
        : 'border-hairline text-ink-mute hover:border-hairline-bright hover:text-ink-body',
      className
    )}
    {...rest}
  >
    {children}
  </button>
);

// Read-only tag. Only `danger` carries a hue — everything else is a neutral step, because
// a four-colour status vocabulary in one view is the tell we're removing.
export const Tag: React.FC<React.HTMLAttributes<HTMLSpanElement> & { tone?: 'default' | 'warning' | 'danger' }> = ({
  tone = 'default',
  className,
  children,
  ...rest
}) => {
  const toneClasses = {
    default: 'border-hairline text-ink-mute',
    warning: 'border-hairline-bright text-ink-body',
    danger: 'border-danger/40 text-danger',
  }[tone];
  return (
    <span
      className={cn('px-2 py-0.5 rounded-sm text-[11px] border inline-block', toneClasses, className)}
      {...rest}
    >
      {children}
    </span>
  );
};
