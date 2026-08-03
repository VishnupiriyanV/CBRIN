import React from 'react';
import { ClipSignals } from '../../types';

const SIGNAL_LABELS: Record<string, string> = {
  hook_strength: 'Hook',
  self_containedness: 'Self-contained',
  emotional_delta: 'Emotional delta',
  quotability: 'Quotability',
  boundary_cleanliness: 'Clean boundaries',
  taste_match: 'Taste match',
};

interface ScoreBreakdownProps {
  signals: ClipSignals;
  reason: string;
}

// Per-signal horizontal bars only — deliberately no "%" or "predicted engagement" number
// anywhere here. These are named, inspectable signals with a weighted-sum composite, never
// a fabricated confidence score (ENGINE-PLAN.md: no Lens/performance-data layer exists).
export const ScoreBreakdown: React.FC<ScoreBreakdownProps> = ({ signals, reason }) => {
  const entries = Object.entries(signals) as [string, number][];

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-mono text-accent-sunset">{reason}</p>
      <div className="space-y-1.5">
        {entries.map(([key, value]) => (
          <div key={key} className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-ink-mute w-32 shrink-0">{SIGNAL_LABELS[key] || key}</span>
            <div className="flex-1 h-1.5 rounded-full bg-canvas-soft border border-hairline/60 overflow-hidden">
              <div
                className="h-full rounded-full bg-accent-sunset/80"
                style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
              />
            </div>
            <span className="text-[10px] font-mono text-ink-mute w-8 text-right">{value.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
