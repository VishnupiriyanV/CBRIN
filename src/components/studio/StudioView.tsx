import React, { useEffect, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { StudioToolInfo, VideoItem } from '../../types';
import { studioListTools } from '../../services/api';
import { ToolRail, StudioSection } from './ToolRail';
import { UsageBadge } from './UsageBadge';
import { VoiceProfilePanel } from './VoiceProfilePanel';
import { PlatformRulesPanel } from './PlatformRulesPanel';
import { RunHistoryPanel } from './RunHistoryPanel';
import { RepurposerTool } from './tools/RepurposerTool';
import { ShowNotesTool } from './tools/ShowNotesTool';
import { TitlesTool } from './tools/TitlesTool';
import { RepliesTool } from './tools/RepliesTool';
import { CaptionsTool } from './tools/CaptionsTool';
import { MomentsTool } from './tools/MomentsTool';

interface StudioViewProps {
  videos: VideoItem[];
  backendOnline: boolean;
}

const TOOL_COMPONENTS: Record<string, React.ComponentType<{ videos: VideoItem[] }>> = {
  repurposer: RepurposerTool,
  show_notes: ShowNotesTool,
  titles: TitlesTool,
  replies: RepliesTool,
  captions: CaptionsTool,
  moments: MomentsTool,
};

// STUDIO (Layer 4): six text-in/text-out creator tools sharing the Voice Profile, Platform
// Rules, run history, and usage meter built in the shared foundation
export const StudioView: React.FC<StudioViewProps> = ({ videos, backendOnline }) => {
  const [tools, setTools] = useState<StudioToolInfo[]>([]);
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const [section, setSection] = useState<StudioSection>('repurposer');

  useEffect(() => {
    if (!backendOnline) return;
    studioListTools()
      .then((res) => {
        setTools(res.tools);
        setLlmConfigured(res.llm_configured);
      })
      .catch(() => setLlmConfigured(false));
  }, [backendOnline]);

  const toolLabels: Record<string, string> = Object.fromEntries(tools.map((t) => [t.id, t.label]));
  const ActiveTool = TOOL_COMPONENTS[section];
  const activeToolInfo = tools.find((t) => t.id === section);

  const getSectionTitle = () => {
    if (section === 'voice_profile') return 'Voice Profile';
    if (section === 'platform_rules') return 'Platform Rules';
    if (section === 'history') return 'Run History';
    return activeToolInfo?.label || 'Studio Tool';
  };

  const getSectionDescription = () => {
    if (section === 'voice_profile') return 'Creator brand tone, bio, and banned words configuration';
    if (section === 'platform_rules') return 'Social network formatting and platform constraints';
    if (section === 'history') return 'Past tool execution outputs and token usage history';
    return activeToolInfo?.description || '';
  };

  if (llmConfigured === false) {
    return (
      <div className="max-w-lg mx-auto text-center py-16 space-y-4">
        <div className="w-12 h-12 rounded-full border border-hairline-bright bg-canvas-card mx-auto flex items-center justify-center text-accent-sunset">
          <KeyRound className="w-5 h-5" />
        </div>
        <h3 className="text-base font-medium text-ink">No LLM API key configured</h3>
        <p className="text-xs text-ink-body leading-relaxed">
          STUDIO tools require an LLM API key. Set <code className="bg-canvas-soft px-1.5 py-0.5 rounded text-ink">VAULT_LLM_API_KEY</code> (and
          optionally <code className="bg-canvas-soft px-1.5 py-0.5 rounded text-ink">VAULT_LLM_MODEL</code>) in the backend environment and restart.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col sm:flex-row gap-6">
      <ToolRail tools={tools} active={section} onSelect={setSection} />
      <div className="flex-1 min-w-0 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-medium text-ink">{getSectionTitle()}</h2>
            <p className="text-xs text-ink-mute mt-0.5">{getSectionDescription()}</p>
          </div>
          <UsageBadge refreshKey={section === 'history' ? 1 : 0} />
        </div>

        {ActiveTool && <ActiveTool videos={videos} />}
        {section === 'voice_profile' && <VoiceProfilePanel />}
        {section === 'platform_rules' && <PlatformRulesPanel />}
        {section === 'history' && <RunHistoryPanel toolLabels={toolLabels} />}
      </div>
    </div>
  );
};
