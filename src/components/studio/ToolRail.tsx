import React from 'react';
import { Clock, Settings2, User } from 'lucide-react';
import { StudioToolInfo } from '../../types';
import { cn } from '../ui/cn';

export type StudioSection = string | 'voice_profile' | 'platform_rules' | 'history';

interface ToolRailProps {
  tools: StudioToolInfo[];
  active: StudioSection;
  onSelect: (section: StudioSection) => void;
}

export const ToolRail: React.FC<ToolRailProps> = ({ tools, active, onSelect }) => {
  const item = (id: StudioSection, label: string, icon?: React.ReactNode) => (
    <button
      key={id}
      onClick={() => onSelect(id)}
      className={cn(
        'w-full text-left px-3 py-2 rounded-sm text-xs font-medium transition-all flex items-center gap-2',
        active === id ? 'bg-canvas-card text-ink border border-hairline-bright' : 'text-ink-mute hover:text-ink hover:bg-canvas-soft border border-transparent'
      )}
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  );

  return (
    <nav className="space-y-1 w-full sm:w-56 shrink-0">
      <div className="eyebrow-mono px-3 mb-1">Tools</div>
      {tools.map((t) => item(t.id, t.label))}
      <div className="eyebrow-mono px-3 mb-1 mt-4">Settings</div>
      {item('voice_profile', 'Voice Profile', <User className="w-3.5 h-3.5" />)}
      {item('platform_rules', 'Platform Rules', <Settings2 className="w-3.5 h-3.5" />)}
      {item('history', 'Run History', <Clock className="w-3.5 h-3.5" />)}
    </nav>
  );
};
