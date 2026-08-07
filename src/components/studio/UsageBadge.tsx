import React, { useEffect, useState } from 'react';
import { Activity } from 'lucide-react';
import { StudioUsageSummary } from '../../types';
import { studioGetUsage } from '../../services/api';

// creator-tools-integration-spec.md §0.5: "a monthly spend alert on the API key" — this app
// has no billing, so the reconciliation is a visible usage meter instead (backend/usage.py).
export const UsageBadge: React.FC<{ refreshKey?: number }> = ({ refreshKey }) => {
  const [usage, setUsage] = useState<StudioUsageSummary | null>(null);

  useEffect(() => {
    studioGetUsage().then(setUsage).catch(() => setUsage(null));
  }, [refreshKey]);

  if (!usage) return null;

  return (
    <div
      className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-sm border border-hairline bg-canvas-soft text-[10px] font-mono text-ink-mute"
      title={`${usage.tokens_in_month.toLocaleString()} in / ${usage.tokens_out_month.toLocaleString()} out tokens this month`}
    >
      <Activity className="w-3 h-3 text-ink-body" />
      <span>{usage.runs_this_hour}/{usage.limits.max_runs_per_hour} this hour</span>
      <span className="text-hairline-bright">•</span>
      <span>{usage.runs_today} today</span>
    </div>
  );
};
