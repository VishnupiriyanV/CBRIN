import React from 'react';
import { ChunkResult } from '../types';
import { Play, Clock, ArrowUpRight, CheckCircle2 } from 'lucide-react';

interface ResultCardProps {
  result: ChunkResult;
  searchQuery: string;
  onJumpToMoment: (result: ChunkResult) => void;
}

export const ResultCard: React.FC<ResultCardProps> = ({
  result,
  searchQuery,
  onJumpToMoment,
}) => {
  // Utility to highlight key matched concepts in the snippet text
  const renderHighlightedSnippet = (text: string, matchedConcepts: string[]) => {
    if (!matchedConcepts || matchedConcepts.length === 0) return text;

    // Create regex matching any of the matched concepts
    const escapedConcepts = matchedConcepts
      .map(c => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('|');

    if (!escapedConcepts) return text;

    const regex = new RegExp(`(${escapedConcepts})`, 'gi');
    const parts = text.split(regex);

    return (
      <>
        {parts.map((part, idx) => {
          const isMatch = matchedConcepts.some(
            c => c.toLowerCase() === part.toLowerCase()
          );
          if (isMatch) {
            return (
              <mark key={idx} className="highlight-match">
                {part}
              </mark>
            );
          }
          return <span key={idx}>{part}</span>;
        })}
      </>
    );
  };

  const relevancePercentage = Math.round(result.score * 100);

  return (
    <div className="bg-canvas-card border border-hairline rounded-lg p-5 hover:border-hairline-bright transition-all group relative">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        
        {/* Main Content Area */}
        <div className="space-y-3 flex-1">
          {/* Source Video Header & Metadata */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="px-2 py-0.5 rounded-full border border-hairline bg-canvas-soft text-[10px] font-mono text-accent-sunset uppercase tracking-wider">
              {result.channel}
            </span>

            {/* Timestamp Badge */}
            <div className="flex items-center gap-1 px-2.5 py-0.5 rounded-full border border-hairline bg-canvas-soft text-xs font-mono text-ink-mute">
              <Clock className="w-3 h-3 text-ink-mute" />
              <span>{result.start_timestamp} - {result.end_timestamp}</span>
            </div>

            {/* Similarity Match Badge */}
            <div className="ml-auto sm:ml-0 flex items-center gap-1 text-[11px] font-mono text-ink-mute">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
              <span>{relevancePercentage}% Match</span>
            </div>
          </div>

          {/* Video Title */}
          <h3 className="font-medium text-base text-ink tracking-tight group-hover:text-accent-sunset transition-colors">
            {result.video_title}
          </h3>

          {/* Spoken Text Snippet */}
          <div className="bg-canvas-soft/60 border border-hairline/60 rounded-md p-3.5 text-sm text-ink-body leading-relaxed font-sans">
            <span className="text-ink-mute text-xs font-mono select-none mr-2">“</span>
            {renderHighlightedSnippet(result.text, result.matched_concepts)}
            <span className="text-ink-mute text-xs font-mono select-none ml-1">”</span>
          </div>
        </div>

        {/* Action Button: Jump to Moment */}
        <div className="sm:self-center flex sm:flex-col items-center justify-end shrink-0 pt-2 sm:pt-0">
          <button
            onClick={() => onJumpToMoment(result)}
            className="w-full sm:w-auto px-4 py-2.5 rounded-full border border-hairline-bright bg-canvas-soft hover:bg-accent-sunset hover:text-black hover:border-accent-sunset text-xs font-medium text-ink transition-all flex items-center justify-center gap-2 group/btn"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Jump to moment</span>
            <ArrowUpRight className="w-3.5 h-3.5 text-ink-mute group-hover/btn:text-black transition-colors" />
          </button>
        </div>
      </div>
    </div>
  );
};
