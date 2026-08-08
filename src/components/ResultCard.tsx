import React, { useState } from 'react';
import { ChunkResult } from '../types';
import { resolveMediaUrl } from '../services/api';
import { Play, Eye, FileText, Copy, Check } from 'lucide-react';

interface ResultCardProps {
  result: ChunkResult;
  searchQuery: string;
  onJumpToMoment: (result: ChunkResult) => void;
  /** 'visual_scenes' (the "ON-SCREEN (CLIP)" mode) makes the frame the primary result — a
   * viewer is asking "what did this look like", so the photo leads and the transcript text
   * becomes supporting context, not the other way around like 'spoken' mode. */
  searchMode?: string;
}

// A separate, smaller list from backend/multimodal_engine.py's STOPWORDS by design, not by
// drift: this one only filters query tokens before phrase-matching for the in-snippet
// highlight below, not concept extraction. IMPROVEMENT-PLAN.md flags the two lists as
// "already disagree" — true, but consolidating them would mean the frontend fetching the
// backend's list at runtime for a cosmetic highlight heuristic, which isn't worth the
// coupling. Keep this comment in sync with intent if that tradeoff changes.
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
  searchMode,
}) => {
  const [copied, setCopied] = useState(false);
  const [showFullPassage, setShowFullPassage] = useState(false);
  const isVisualMode = searchMode === 'visual_scenes';

  // `full_text` is only sent when the backend actually trimmed the quote, so its presence
  // is the signal that there is more to show — no length comparison needed here.
  const hasFullPassage = Boolean(result.full_text);
  const displayText = showFullPassage && result.full_text ? result.full_text : result.text;

  const handleCopyCitation = async () => {
    // The actual repurposing workflow this product exists for (IMPROVEMENT-PLAN.md 3.6):
    // grab a quote with enough citation to drop straight into a script or show notes.
    // Copies whatever is currently on screen — if the reader expanded to the full passage,
    // that's the quote they mean, not the trimmed one.
    const citation = `"${displayText}" — ${result.video_title} @ ${result.start_timestamp}`;
    try {
      await navigator.clipboard.writeText(citation);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch (err) {
      console.error('Copy to clipboard failed:', err);
    }
  };

  const renderHighlightedSnippet = (rawText: string, query: string, matchedConcepts?: string[]) => {
    if (!rawText) return null;

    // Apply sentence capitalization to raw speech transcripts
    const formatSentenceCasing = (s: string) => {
      if (!s) return '';
      let formatted = s.trim();
      formatted = formatted.replace(/(^\s*|[.!?]\s+)([a-z])/g, (_, p1, p2) => p1 + p2.toUpperCase());
      formatted = formatted.replace(/\bi\b/g, 'I');
      if (formatted.length > 0) {
        formatted = formatted.charAt(0).toUpperCase() + formatted.slice(1);
      }
      return formatted;
    };

    const text = formatSentenceCasing(rawText);

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

  // A ms-marco cross-encoder logit (or a raw CLIP cosine similarity) run through sigmoid
  // is a ranking signal, not a probability of relevance, and its scale isn't comparable
  // across queries — showing it as "72% match" implies a precision the number doesn't have
  // (IMPROVEMENT-PLAN.md 2.3). Show a calibrated confidence bucket instead.
  const confidence = result.confidence ?? (result.score >= 0.75 ? 'strong' : result.score >= 0.5 ? 'possible' : 'weak');
  // 'unranked': the reranker was unavailable server-side, so this is a best-effort retrieval
  // match with no real confidence score behind it at all — distinct from 'weak' (a real,
  // if low, reranker score) and shown neutrally rather than implying any quality judgment.
  const confidenceLabel = confidence === 'strong' ? 'Strong match' :
                          confidence === 'possible' ? 'Possible match' :
                          confidence === 'unranked' ? 'Unranked (degraded)' :
                          'Closest match';
  // STRATEGY.md §8: confidence is encoded as the *length* of a monochrome rule, not as a
  // hue. The previous emerald/amber/slate/orange dot vocabulary put four colours in one
  // results list, which read as a status rainbow rather than as information.
  const confidenceFill = confidence === 'strong' ? 1 :
                         confidence === 'possible' ? 0.6 :
                         confidence === 'unranked' ? 0.15 :
                         0.3;

  // Use keyframe thumbnail if available, otherwise fall back to video thumbnail
  const displayThumbnail = resolveMediaUrl(result.keyframe_url) || resolveMediaUrl(result.thumbnail_url);

  return (
    <div className={`bg-canvas-card border rounded-sm p-5 hover:border-hairline-bright transition-all group relative border-hairline`}>
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">

        {/* Thumbnail + Main Content */}
        <div className={`flex gap-4 flex-1 min-w-0 ${isVisualMode ? 'flex-col sm:flex-row' : ''}`}>

          {/* Chunk Keyframe / Video Thumbnail — the primary result in visual search: a viewer
              searching "on-screen" is asking what something looked like, so the frame leads
              and is shown at every breakpoint (not hidden on mobile like the spoken-mode icon). */}
          {displayThumbnail && (
            <div className={`relative shrink-0 ${isVisualMode ? 'block w-full sm:w-64' : 'hidden sm:block'}`}>
              <img
                src={displayThumbnail}
                alt={`${result.video_title} at ${result.start_timestamp}`}
                className={
                  isVisualMode
                    ? 'w-full sm:w-64 aspect-video object-cover rounded-sm border-2 border-accent-sunset/60 bg-canvas-soft'
                    : 'w-28 h-[72px] object-cover rounded border border-hairline bg-canvas-soft'
                }
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
              {/* Timestamp overlay on thumbnail */}
              <div className="absolute bottom-1 right-1 px-1.5 py-0.5 bg-black/80 rounded text-[9px] font-mono text-white">
                {result.start_timestamp}
              </div>
              {/* Visual indexing indicator on thumbnail. 'video-level' (YouTube) means every
                  chunk of this video shares the same thumbnail, so it can't localize this
                  specific moment — shown distinctly from a real per-moment 'ok' frame
                  instead of claiming the same thing (IMPROVEMENT-PLAN.md 2.10). */}
              <div
                className={`absolute top-1 left-1 p-0.5 rounded ${result.visual_status === 'ok' ? 'bg-ink/80' : result.visual_status === 'video-level' ? 'bg-ink-body/80' : 'bg-canvas-soft/80'}`}
                title={
                  result.visual_status === 'ok' ? 'CLIP visual match — a real frame from this moment' :
                  result.visual_status === 'video-level' ? "Video-level thumbnail only — can't localize this specific moment" :
                  'Text only, no visual embedding'
                }
              >
                {result.visual_status === 'ok' || result.visual_status === 'video-level' ? (
                  <Eye className="w-2.5 h-2.5 text-white" />
                ) : (
                  <FileText className="w-2.5 h-2.5 text-ink-mute" />
                )}
              </div>
            </div>
          )}

          {/* Text Content */}
          <div className="space-y-3 flex-1 min-w-0">

            {/* Meta line.
                Previously five separate chrome elements (channel capsule, timestamp
                capsule, confidence dot, match reason, mobile index badge) stacked above
                the content, which made the transcript quote — the only thing the user
                came for — the fifth-loudest element on the card. It is now one quiet
                line of text, and the quote below is the largest thing in the card
                (STRATEGY.md §8). */}
            <div className="flex items-baseline gap-2 text-[11px] text-ink-mute">
              <span className="truncate" title={`Channel: ${result.channel}`}>{result.channel}</span>
              <span className="text-ink-faint">/</span>
              <span className="font-mono shrink-0">{result.start_timestamp}–{result.end_timestamp}</span>
              <span
                className="ml-auto flex items-center gap-2 shrink-0"
                title={result.match_reason ? `${confidenceLabel} — ${result.match_reason}` : confidenceLabel}
              >
                <span className="hidden sm:inline">{confidenceLabel}</span>
                <span className="confidence-rule" style={{ '--fill': confidenceFill } as React.CSSProperties} />
              </span>
            </div>

            {/* Video Title */}
            <h3 className="font-medium text-[15px] text-ink-body tracking-tight group-hover:text-ink transition-colors duration-100">
              {result.video_title}
              {result.section_topic && (
                <span className="text-ink-mute font-normal"> · {result.section_topic}</span>
              )}
            </h3>

            {/* Spoken Text Snippet — full-weight quote block in spoken mode (the text IS the
                match); a small, muted, clamped caption in visual mode, since the frame above
                is the match and this is just supporting context for it. */}
            {isVisualMode ? (
              <p className="text-xs text-ink-mute leading-relaxed line-clamp-2">
                {renderHighlightedSnippet(result.text, searchQuery, result.implicit_concepts)}
              </p>
            ) : (
              // No box. A left rule is enough to mark a quotation, and it lets the text
              // itself be the largest, brightest thing in the card.
              <blockquote className="border-l border-hairline-bright pl-3.5 text-[15px] text-ink leading-relaxed max-w-[68ch]">
                {renderHighlightedSnippet(displayText, searchQuery, result.implicit_concepts)}
                {hasFullPassage && (
                  // Plain inline text button, no capsule — same reasoning as the meta line
                  // above: this is a minor affordance and shouldn't compete with the quote.
                  <button
                    onClick={() => setShowFullPassage((v) => !v)}
                    className="ml-2 align-baseline text-[11px] text-ink-mute hover:text-ink underline underline-offset-2 decoration-hairline-bright transition-colors duration-100"
                  >
                    {showFullPassage ? 'Show less' : 'Show full passage'}
                  </button>
                )}
              </blockquote>
            )}

            {/* Questions Answered (if available) */}
            {result.questions_answered && result.questions_answered.length > 0 && (
              <p className="text-xs text-ink-mute leading-relaxed">
                Answers: <span className="text-ink-body">{result.questions_answered[0]}</span>
              </p>
            )}

            {/* Matched concepts — plain text, middot-separated. Five bordered capsules for
                five one-word tags was more chrome than the tags were worth. */}
            {result.matched_concepts && result.matched_concepts.length > 0 && (
              <p className="text-[11px] text-ink-faint truncate">
                {result.matched_concepts.slice(0, 5).join(' · ')}
              </p>
            )}
          </div>
        </div>

        {/* Actions. Icons kept only where they are the affordance (play, copy, bookmark);
            the decorative ones that duplicated adjacent text are gone. */}
        <div className="sm:self-center flex sm:flex-col items-center justify-end gap-1.5 shrink-0 pt-2 sm:pt-0">
          <button
            onClick={handleCopyCitation}
            className={`p-2 rounded-sm border transition-colors duration-100 ${
              copied
                ? 'border-hairline-bright text-ink'
                : 'border-transparent text-ink-faint hover:text-ink hover:border-hairline'
            }`}
            title={copied ? 'Copied' : 'Copy quote with citation'}
          >
            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
          </button>

          <button
            onClick={() => onJumpToMoment(result)}
            className="w-full sm:w-auto px-3 py-2 rounded-sm border border-hairline text-ink-body text-xs font-medium transition-colors duration-100 flex items-center justify-center gap-1.5 hover:bg-ink hover:text-canvas hover:border-ink active:translate-y-[0.5px]"
          >
            <Play className="w-3 h-3 fill-current" />
            <span>Jump</span>
          </button>
        </div>
      </div>
    </div>
  );
};
