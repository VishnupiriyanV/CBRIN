import React from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from './cn';

// STRATEGY.md §8: no chromatic accent. Primary emphasis is a white-on-black inversion —
// the loudest thing available in a monochrome system, and it costs no colour.
// Previously these were sunset-orange capsules; the pill shape and the hue were both
// doing the same job (shouting), so both are gone.
const VARIANT_CLASSES: Record<'primary' | 'secondary' | 'ghost' | 'danger', string> = {
  primary:
    'border border-ink bg-ink text-canvas hover:bg-white hover:border-white',
  secondary:
    'border border-hairline bg-transparent text-ink-body hover:text-ink hover:border-hairline-bright',
  ghost:
    'border border-transparent text-ink-mute hover:text-ink hover:bg-canvas-hover',
  danger:
    'border border-danger/40 bg-transparent text-danger hover:bg-danger/10 hover:border-danger',
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  loading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'secondary',
  loading = false,
  disabled,
  className,
  children,
  ...rest
}) => (
  <button
    disabled={disabled || loading}
    className={cn(
      'px-3 py-1.5 rounded-sm text-xs font-medium transition-colors duration-100 inline-flex items-center gap-1.5',
      'active:translate-y-[0.5px]',
      'disabled:opacity-35 disabled:cursor-not-allowed disabled:active:translate-y-0',
      VARIANT_CLASSES[variant],
      className
    )}
    {...rest}
  >
    {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
    {children}
  </button>
);
