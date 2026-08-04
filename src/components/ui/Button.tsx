import React from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from './cn';

// The two recurring button recipes, previously copy-pasted inline throughout App.tsx /
// Header.tsx / ClipStudio.tsx: primary sunset-accent and secondary hairline-bordered.
const VARIANT_CLASSES: Record<'primary' | 'secondary' | 'ghost', string> = {
  primary:
    'border border-accent-sunset/40 bg-accent-sunset/10 text-accent-sunset hover:bg-accent-sunset hover:text-black hover:border-accent-sunset',
  secondary:
    'border border-hairline bg-canvas-card text-ink hover:bg-canvas-soft hover:border-hairline-bright',
  ghost: 'border border-transparent text-ink-mute hover:text-ink hover:bg-canvas-soft',
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
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
      'px-3.5 py-1.5 rounded-full text-xs font-medium transition-all inline-flex items-center gap-1.5',
      'disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent',
      VARIANT_CLASSES[variant],
      className
    )}
    {...rest}
  >
    {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
    {children}
  </button>
);
