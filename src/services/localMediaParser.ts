/**
 * Helper to format seconds to MM:SS
 */
export function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

/**
 * Determines duration of a local video or audio File using HTML5 media element
 */
export function getMediaDuration(file: File): Promise<number> {
  return new Promise((resolve) => {
    const isAudio = file.type.startsWith('audio');
    const media = document.createElement(isAudio ? 'audio' : 'video');
    const objectUrl = URL.createObjectURL(file);
    media.src = objectUrl;

    media.onloadedmetadata = () => {
      const duration = media.duration || 0;
      URL.revokeObjectURL(objectUrl);
      resolve(duration);
    };

    media.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(0);
    };
  });
}

/**
 * Filter a FileList to only include supported media formats.
 */
export function filterMediaFiles(files: FileList | null): File[] {
  if (!files || files.length === 0) return [];

  return Array.from(files).filter(f =>
    f.type.startsWith('video/') ||
    f.type.startsWith('audio/') ||
    /\.(mp4|mov|webm|mkv|avi|mp3|wav|m4a|aac|flac|ogg|wma)$/i.test(f.name)
  );
}
