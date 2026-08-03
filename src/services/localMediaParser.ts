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
