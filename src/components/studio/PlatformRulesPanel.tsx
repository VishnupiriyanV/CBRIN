import React, { useEffect, useState } from 'react';
import { PlatformRules } from '../../types';
import { studioGetPlatformRules, studioUpdatePlatformRules } from '../../services/api';
import { Panel, PanelHeading } from '../ui/Panel';

// Platform character limits and hashtag conventions shift over time
// (creator-tools-integration-spec.md §5) — editable here rather than baked into a prompt,
// so an update doesn't need a code change or redeploy.
export const PlatformRulesPanel: React.FC = () => {
  const [rules, setRules] = useState<PlatformRules | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    studioGetPlatformRules().then(setRules).catch((e) => setError(e.message));
  }, []);

  if (!rules) {
    return <Panel><p className="text-xs text-ink-mute">Loading platform rules…</p></Panel>;
  }

  const saveField = async (platform: string, field: 'char_limit' | 'hashtag_min' | 'hashtag_max', value: number) => {
    const patch = { [platform]: { [field]: value } };
    try {
      const updated = await studioUpdatePlatformRules(patch);
      setRules(updated);
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <Panel className="space-y-4">
      <PanelHeading className="mb-0">Platform Rules</PanelHeading>
      {error && <div className="bg-canvas-card/40 border border-danger/30 rounded-sm p-2.5 text-xs text-danger font-mono">{error}</div>}
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left">
          <thead>
            <tr className="text-ink-mute font-mono text-[10px] border-b border-hairline">
              <th className="py-2 pr-3">Platform</th>
              <th className="py-2 pr-3">Style</th>
              <th className="py-2 pr-3">Char limit</th>
              <th className="py-2 pr-3">Hashtags min</th>
              <th className="py-2 pr-3">Hashtags max</th>
              <th className="py-2 pr-3">Links</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(rules).map(([id, rule]) => (
              <tr key={id} className="border-b border-hairline/40">
                <td className="py-2 pr-3 text-ink font-medium">{rule.label}</td>
                <td className="py-2 pr-3 text-ink-mute">{rule.style}</td>
                <td className="py-2 pr-3">
                  <NumberInput value={rule.char_limit} onCommit={(v) => saveField(id, 'char_limit', v)} />
                </td>
                <td className="py-2 pr-3">
                  <NumberInput value={rule.hashtag_min} onCommit={(v) => saveField(id, 'hashtag_min', v)} />
                </td>
                <td className="py-2 pr-3">
                  <NumberInput value={rule.hashtag_max} onCommit={(v) => saveField(id, 'hashtag_max', v)} />
                </td>
                <td className="py-2 pr-3 text-ink-mute">{rule.links_clickable ? 'Clickable' : 'Not clickable'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
};

const NumberInput: React.FC<{ value: number; onCommit: (v: number) => void }> = ({ value, onCommit }) => (
  <input
    type="number"
    defaultValue={value}
    key={value}
    onBlur={(e) => {
      const v = Number(e.target.value);
      if (!Number.isNaN(v) && v !== value) onCommit(v);
    }}
    className="w-20 bg-canvas-soft border border-hairline rounded px-2 py-1 text-xs text-ink focus:outline-none focus:border-hairline-bright"
  />
);
