import React from 'react';
import { Copy, Check } from 'lucide-react';
import { useCopyToClipboard } from '../../hooks/useCopyToClipboard';
import { cn } from './cn';

interface CopyButtonProps {
  text: string;
  label?: string;
  className?: string;
}

export const CopyButton: React.FC<CopyButtonProps> = ({ text, label = 'Copy', className }) => {
  const { copied, copy } = useCopyToClipboard();
  return (
    <button
      type="button"
      onClick={() => copy(text)}
      className={cn(
        'px-2.5 py-1 rounded-full border text-[11px] font-mono inline-flex items-center gap-1.5 transition-all',
        copied
          ? 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10'
          : 'border-hairline text-ink-mute hover:border-hairline-bright hover:text-ink',
        className
      )}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? 'Copied' : label}
    </button>
  );
};
