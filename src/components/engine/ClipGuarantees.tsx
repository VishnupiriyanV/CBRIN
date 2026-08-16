import React from 'react';
import { ClipCandidate } from '../../types';

interface ClipGuaranteesProps {
  clip: ClipCandidate;
}

type Line = { label: string; detail: string; tone: 'good' | 'warn' | 'unknown' };

// The solver computes these and nothing showed them. "This clip contains no reference to
// anything the viewer hasn't seen" is the one property here that is proven rather than
// scored, and it was invisible in the UI while being persisted on every clip.
//
// The three-state rule matters more than the styling: checked-and-clean, checked-and-not,
// and never-checked are different claims. An older clip with no `dangling_reference_indices`
// must read as unknown — reporting it as clean would be exactly the unverified assertion
// clip_scoring stopped making when it dropped the LLM's self_contained flag.
function buildLines(clip: ClipCandidate): Line[] {
  const lines: Line[] = [];

  const dangling = clip.dangling_reference_indices;
  if (dangling === undefined || dangling === null) {
    lines.push({
      label: 'References',
      detail: 'not checked for this clip',
      tone: 'unknown',
    });
  } else if (dangling.length === 0) {
    const expanded = clip.references_expanded_by ?? 0;
    lines.push({
      label: 'References',
      detail: expanded > 0
        ? `all resolve — opened ${expanded} sentence${expanded === 1 ? '' : 's'} earlier to keep them`
        : 'all resolve inside the clip',
      tone: 'good',
    });
  } else {
    lines.push({
      label: 'References',
      detail: `${dangling.length} sentence${dangling.length === 1 ? '' : 's'} still point outside the clip `
        + `(${dangling.join(', ')}) — couldn't reach the antecedent within the length limit`,
      tone: 'warn',
    });
  }

  const selection = clip.boundary_selection;
  if (selection?.pause_aligned) {
    lines.push({
      label: 'Boundaries',
      detail: `moved to a natural pause (+${selection.sentences_added} sentence`
        + `${selection.sentences_added === 1 ? '' : 's'})`,
      tone: 'good',
    });
  }

  // Only reported when there is a real number and it is high enough to matter.
  //
  // Deliberately silent otherwise, rather than explaining why. clip_scoring._select_diverse
  // sets `measured: false` for two unrelated reasons — the dense model was unavailable, and
  // there was only one candidate so nothing could be compared — and the payload does not
  // distinguish them. Naming either cause in the UI would be a guess presented as a fact, and
  // "nothing to compare this against" is not information the viewer needs anyway.
  const similarity = clip.diversity?.measured ? clip.diversity.max_similarity : null;
  if (similarity !== null && similarity !== undefined && similarity >= 0.5) {
    lines.push({
      label: 'Overlap',
      detail: `${Math.round(similarity * 100)}% similar to a higher-ranked clip`,
      tone: 'warn',
    });
  }

  return lines;
}

const TONE_CLASS: Record<Line['tone'], string> = {
  good: 'text-ink-body',
  warn: 'text-danger',
  unknown: 'text-ink-mute',
};

export const ClipGuarantees: React.FC<ClipGuaranteesProps> = ({ clip }) => {
  const lines = buildLines(clip);
  if (lines.length === 0) return null;

  return (
    <div className="space-y-1">
      {lines.map((line) => (
        <div key={line.label} className="flex items-start gap-2">
          <span className="text-[10px] font-mono text-ink-mute w-32 shrink-0">{line.label}</span>
          <span className={`text-[10px] font-mono leading-relaxed ${TONE_CLASS[line.tone]}`}>
            {line.detail}
          </span>
        </div>
      ))}
    </div>
  );
};
