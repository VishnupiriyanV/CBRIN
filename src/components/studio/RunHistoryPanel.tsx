import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react';
import { ToolRun } from '../../types';
import { studioDeleteRun, studioListRuns } from '../../services/api';
import { Panel, PanelHeading } from '../ui/Panel';

interface RunHistoryPanelProps {
  toolLabels: Record<string, string>;
}

// creator-tools-integration-spec.md §0.2: run history is "a big retention lever, cheap to
// build, users expect it" — one flat list across all six tools, expandable per run.
export const RunHistoryPanel: React.FC<RunHistoryPanelProps> = ({ toolLabels }) => {
  const [runs, setRuns] = useState<ToolRun[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    studioListRuns(undefined, 100).then(setRuns).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleDelete = async (runId: string) => {
    await studioDeleteRun(runId);
    load();
  };

  return (
    <Panel className="space-y-3">
      <PanelHeading className="mb-0">Run History</PanelHeading>
      {loading && <p className="text-xs text-ink-mute">Loading…</p>}
      {!loading && runs.length === 0 && <p className="text-xs text-ink-mute">No runs yet.</p>}
      <div className="space-y-2">
        {runs.map((run) => {
          const isOpen = expanded === run.id;
          return (
            <div key={run.id} className="bg-canvas-soft border border-hairline rounded-lg">
              <div className="flex items-center justify-between p-3">
                <button
                  onClick={() => setExpanded(isOpen ? null : run.id)}
                  className="flex items-center gap-2 text-left flex-1 min-w-0"
                >
                  {isOpen ? <ChevronUp className="w-3.5 h-3.5 text-ink-mute shrink-0" /> : <ChevronDown className="w-3.5 h-3.5 text-ink-mute shrink-0" />}
                  <span className="text-xs font-medium text-ink">{toolLabels[run.tool_id] || run.tool_id}</span>
                  <span className="text-[11px] font-mono text-ink-mute">{new Date(run.created_at * 1000).toLocaleString()}</span>
                </button>
                <button onClick={() => handleDelete(run.id)} className="text-ink-mute hover:text-red-400 shrink-0">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
              {isOpen && (
                <pre className="px-3 pb-3 text-[11px] font-mono text-ink-body overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify(run.output, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
};
