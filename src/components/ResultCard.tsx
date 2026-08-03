import React from 'react';
import { ChunkResult } from '../types';
import { Play, Clock, ArrowUpRight, HelpCircle, Layers, Bookmark, Eye, FileText, User } from 'lucide-react';

interface ResultCardProps {
  result: ChunkResult;
  searchQuery: string;
  onJumpToMoment: (result: ChunkResult) => void;
  onToggleHighlight: (result: ChunkResult) => void;
}

const COMMON_STOPWORDS = new Set([
  'the', 'that', 'this', 'with', 'from', 'have', 'your', 'about', 'they', 'what', 'when',
  'like', 'just', 'more', 'some', 'been', 'also', 'into', 'over', 'such', 'than', 'them',
  'then', 'very', 'will', 'would', 'could', 'should', 'does', 'going', 'really', 'know',
  'think', 'well', 'here', 'there', 'where', 'which', 'their', 'were', 'being', 'each',
  'make', 'because', 'thing', 'things', 'come', 'came', 'made', 'want', 'kind', 'sort',
  'you', 'are', 'was', 'has', 'had', 'but', 'and', 'for', 'not', 'yes', 'yeah', 'okay',
  'sure', 'bunch', 'stuff', 'look', 'said', 'says', 'tell', 'told', 'actually', 'basically',
  'literally', 'something', 'anything', 'everything', 'nothing', 'how', 'did', 'who', 'why',
  'can', 'could', 'is', 'a', 'an', 'of', 'to', 'in', 'on', 'at', 'by'
]);

export const ResultCard: React.FC<ResultCardProps> = ({
  result,
  searchQuery,
  onJumpToMoment,
  onToggleHighlight,
}) => {
  const renderHighlightedSnippet = (text: string, query: string, matchedConcepts?: string[]) => {
    if (!text) return null;

    // Filter out stop words from query words
    const queryTokens = (query || '')
      .toLowerCase()
      .split(/\W+/)
      .filter(w => w.length > 2 && !COMMON_STOPWORDS.has(w));

    const candidatePhrases: string[] = [];

    // 1. Contiguous non-stopword query subphrases
    if (queryTokens.length >= 2) {
      candidatePhrases.push(queryTokens.join(' '));
      for (let i = 0; i < queryTokens.length - 1; i++) {
        candidatePhrases.push(`${queryTokens[i]} ${queryTokens[i + 1]}`);
      }
    }

    // 2. Matched key concepts
    if (matchedConcepts && matchedConcepts.length > 0) {
      candidatePhrases.push(...matchedConcepts);
    }

    // 3. Individual non-stopword query terms
    candidatePhrases.push(...queryTokens);

    // Find the longest candidate phrase that actually appears in the text
    let bestMatch: string | null = null;
    const lowerText = text.toLowerCase();

    for (const phrase of candidatePhrases) {
      if (!phrase || phrase.trim().length < 3) continue;
      const cleanPhrase = phrase.trim().toLowerCase();
      if (lowerText.includes(cleanPhrase)) {
        if (!bestMatch || cleanPhrase.length > bestMatch.length) {
          bestMatch = cleanPhrase;
        }
      }
    }

    if (!bestMatch) {
      return <span>{text}</span>;
    }

    const matchIndex = lowerText.indexOf(bestMatch);
    if (matchIndex === -1) return <span>{text}</span>;

    const before = text.slice(0, matchIndex);
    const matchedText = text.slice(matchIndex, matchIndex + bestMatch.length);
    const after = text.slice(matchIndex + bestMatch.length);

    return (
      <>
        <span>{before}</span>
        <mark className="highlight-match">{matchedText}</mark>
        <span>{after}</span>
      </>
    );
  };

  const relevancePercentage = Math.round(result.score * 100);

  const scoreColor = result.score >= 0.6 ? 'bg-emerald-500' :
                     result.score >= 0.4 ? 'bg-amber-500' :
                     'bg-orange-500';

  // Use keyframe thumbnail if available, otherwise fall back to video thumbnail
  const displayThumbnail = result.keyframe_url || result.thumbnail_url;

  return (
    <div className={`bg-canvas-card border rounded-lg p-5 hover:border-hairline-bright transition-all group relative ${result.is_highlighted ? 'border-accent-sunset/50' : 'border-hairline'}`}>
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">

        {/* Thumbnail + Main Content */}
        <div className="flex gap-4 flex-1 min-w-0">

          {/* Chunk Keyframe / Video Thumbnail */}
          {displayThumbnail && (
            <div className="relative shrink-0 hidden sm:block">
              <img
                src={displayThumbnail}
                alt={`${result.video_title} at ${result.start_timestamp}`}
                className="w-28 h-[72px] object-cover rounded border border-hairline bg-canvas-soft"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
              {/* Timestamp overlay on thumbnail */}
              <div className="absolute bottom-1 right-1 px-1.5 py-0.5 bg-black/80 rounded text-[9px] font-mono text-white">
                {result.start_timestamp}
              </div>
              {/* Visual indexing indicator on thumbnail */}
              <div className={`absolute top-1 left-1 p-0.5 rounded ${result.has_visual_embedding ? 'bg-emerald-500/80' : 'bg-canvas-soft/80'}`} title={result.has_visual_embedding ? 'CLIP Visual Indexed' : 'Text Only'}>
                {result.has_visual_embedding ? (
                  <Eye className="w-2.5 h-2.5 text-white" />
                ) : (
                  <FileText className="w-2.5 h-2.5 text-ink-mute" />
                )}
              </div>
            </div>
          )}

          {/* Text Content */}
          <div className="space-y-3 flex-1 min-w-0">

            {/* Header Metadata */}
            <div className="flex flex-wrap items-center gap-2">
              {/* Content Source Channel Badge with Icon & Tooltip */}
              <span
                className="px-2.5 py-0.5 rounded-full border border-hairline bg-canvas-soft text-[10px] font-mono text-accent-sunset uppercase tracking-wider flex items-center gap-1"
                title={`Content Creator / Channel: ${result.channel}`}
              >
                <User className="w-2.5 h-2.5 text-accent-sunset" />
                <span>CHANNEL: {result.channel}</span>
              </span>

              {/* Timestamp */}
              <div className="flex items-center gap-1 px-2.5 py-0.5 rounded-full border border-hairline bg-canvas-soft text-xs font-mono text-ink-mute">
                <Clock className="w-3 h-3 text-ink-mute" />
                <span>{result.start_timestamp} - {result.end_timestamp}</span>
              </div>

              {/* Similarity Score + One-line match reason */}
              <div className="ml-auto sm:ml-0 flex items-center gap-1.5 text-[11px] font-mono text-ink-mute">
                <span className={`w-1.5 h-1.5 rounded-full ${scoreColor}`}></span>
                <span className="font-semibold text-ink">{relevancePercentage}% match</span>
                {result.match_reason && (
                  <span className="text-[10px] text-accent-sunset/90 font-mono hidden md:inline truncate max-w-xs" title={result.match_reason}>
                    • {result.match_reason}
                  </span>
                )}
              </div>

              {/* Index type badge — visible on mobile where thumbnail is hidden */}
              <div className="sm:hidden flex items-center gap-1 text-[9px] font-mono">
                {result.has_visual_embedding ? (
                  <span className="px-1.5 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-800/40 text-emerald-400 flex items-center gap-0.5">
                    <Eye className="w-2.5 h-2.5" /> VISUAL
                  </span>
                ) : (
                  <span className="px-1.5 py-0.5 rounded-full bg-canvas-soft border border-hairline text-ink-mute flex items-center gap-0.5">
                    <FileText className="w-2.5 h-2.5" /> TEXT
                  </span>
                )}
              </div>
            </div>

            {/* Video Title */}
            <h3 className="font-medium text-base text-ink tracking-tight group-hover:text-accent-sunset transition-colors">
              {result.video_title}
            </h3>

            {/* Section Topic (if available) */}
            {result.section_topic && (
              <div className="flex items-center gap-1.5 text-xs font-mono text-ink-mute">
                <Layers className="w-3.5 h-3.5 text-accent-sunset" />
                <span>SECTION: {result.section_topic}</span>
              </div>
            )}

            {/* Spoken Text Snippet with Coherent Single Phrase Highlight */}
            <div className="bg-canvas-soft/60 border border-hairline/60 rounded-md p-3.5 text-sm text-ink-body leading-relaxed font-sans">
              <span className="text-ink-mute text-xs font-mono select-none mr-1.5">"</span>
              {renderHighlightedSnippet(result.text, searchQuery, result.implicit_concepts)}
              <span className="text-ink-mute text-xs font-mono select-none ml-1.5">"</span>
            </div>

            {/* Questions Answered (if available) */}
            {result.questions_answered && result.questions_answered.length > 0 && (
              <div className="space-y-1">
                <div className="flex items-center gap-1 text-[10px] font-mono text-ink-mute uppercase tracking-wider">
                  <HelpCircle className="w-3 h-3 text-accent-sunset" />
                  <span>ANSWERS QUESTION:</span>
                </div>
                <p className="text-xs text-ink italic font-sans pl-4 border-l border-hairline-bright">
                  "{result.questions_answered[0]}"
                </p>
              </div>
            )}

            {/* Key Concepts Pills */}
            {result.matched_concepts && result.matched_concepts.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {result.matched_concepts.slice(0, 5).map((concept, idx) => (
                  <span key={idx} className="px-2 py-0.5 rounded-full border border-hairline bg-canvas text-[10px] font-mono text-ink-mute">
                    {concept}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="sm:self-center flex sm:flex-col items-center justify-end gap-2 shrink-0 pt-2 sm:pt-0">
          {/* Bookmark / Highlight Button */}
          <button
            onClick={() => onToggleHighlight(result)}
            className={`p-2.5 rounded-full border transition-all ${
              result.is_highlighted
                ? 'bg-accent-sunset/10 border-accent-sunset/50 text-accent-sunset'
                : 'bg-canvas-soft border-hairline text-ink-mute hover:text-accent-sunset hover:border-accent-sunset/40'
            }`}
            title={result.is_highlighted ? 'Remove highlight' : 'Highlight this moment'}
          >
            <Bookmark className={`w-4 h-4 ${result.is_highlighted ? 'fill-current' : ''}`} />
          </button>

          {/* Jump to Moment */}
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
