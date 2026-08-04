import React from 'react';
import { cn } from './cn';

// prd.md §11: cards stay at 8px radius, hairline borders carry all elevation — no shadows.
// The engine components drifted to rounded-2xl; new STUDIO surfaces use this instead of
// repeating the Tailwind string.
export const Panel: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, children, ...rest }) => (
  <div className={cn('bg-canvas-card border border-hairline rounded-lg p-5', className)} {...rest}>
    {children}
  </div>
);

export const PanelHeading: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, children, ...rest }) => (
  <div className={cn('eyebrow-mono mb-3', className)} {...rest}>
    {children}
  </div>
);
