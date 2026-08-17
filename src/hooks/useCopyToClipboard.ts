import { useState, useCallback, useEffect, useRef } from 'react';

// Extracted from the only prior implementation (ResultCard.tsx's handleCopyCitation) —
// creator-tools-integration-spec.md §0.2 calls per-block copy "non-negotiable" across all
// six STUDIO tools, so this needed to stop being a one-off.
export function useCopyToClipboard(resetAfterMs: number = 1800) {
  const [copied, setCopied] = useState(false);
  // Held so a second copy supersedes the first's reset instead of racing it: two copies
  // 200ms apart used to leave two timers running, and the older one cleared the "Copied"
  // state while the newer copy was still fresh. Also cancelled on unmount.
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (resetTimer.current) clearTimeout(resetTimer.current);
  }, []);

  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        if (resetTimer.current) clearTimeout(resetTimer.current);
        resetTimer.current = setTimeout(() => setCopied(false), resetAfterMs);
      } catch (err) {
        console.error('Copy to clipboard failed:', err);
      }
    },
    [resetAfterMs]
  );

  return { copied, copy };
}
