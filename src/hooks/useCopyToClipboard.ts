import { useState, useCallback } from 'react';

// Extracted from the only prior implementation (ResultCard.tsx's handleCopyCitation) —
// creator-tools-integration-spec.md §0.2 calls per-block copy "non-negotiable" across all
// six STUDIO tools, so this needed to stop being a one-off.
export function useCopyToClipboard(resetAfterMs: number = 1800) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), resetAfterMs);
      } catch (err) {
        console.error('Copy to clipboard failed:', err);
      }
    },
    [resetAfterMs]
  );

  return { copied, copy };
}
