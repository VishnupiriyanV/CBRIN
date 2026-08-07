import React from 'react';
import { cn } from './cn';

// STRATEGY.md §8: hairline borders carry all elevation — no shadows, no glows, one 2px
// radius. The previous note here observed that engine components had drifted to
// rounded-sm; the radius scale in tailwind.config.js now collapses every radius token to
// 2px, so that drift can't recur.
export const Panel: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, children, ...rest }) => (
  <div className={cn('bg-canvas-card border border-hairline rounded-sm p-5', className)} {...rest}>
    {children}
  </div>
);

export const PanelHeading: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, children, ...rest }) => (
  <div className={cn('eyebrow-mono mb-3', className)} {...rest}>
    {children}
  </div>
);
