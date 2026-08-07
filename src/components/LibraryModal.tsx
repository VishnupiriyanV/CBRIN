import React, { useState, useRef } from 'react';
import { VideoItem } from '../types';
import { X, Video, Plus, Check, ExternalLink, Upload, FolderUp, AlertCircle, Loader2, Trash2, RotateCcw, AlertTriangle, CheckCircle2, FileUp, Eye, FileText } from 'lucide-react';
import { ingestVideoUrl, uploadLocalFile, deleteLibraryVideo, importLibrary, isIngestJobStart, pollJob } from '../services/api';
import { filterMediaFiles } from '../services/localMediaParser';
import { relativeTime } from '../utils';

const WHISPER_MODEL_TIERS = ['base', 'small', 'medium'] as const;
type WhisperModelTier = typeof WHISPER_MODEL_TIERS[number];

const MODEL_TIER_HINTS: Record<WhisperModelTier, string> = {
  base: 'Fastest, weakest on proper nouns & technical terms',
  small: 'Balanced — recommended default',
  medium: 'Most accurate, slowest to transcribe',
};

/** Whisper accuracy/speed tier picker shared by the file and folder upload modes
 * (PRD §7.2 — 'base' mangles proper nouns and technical vocabulary). */
const ModelTierSelector: React.FC<{
  value: WhisperModelTier;
  onChange: (tier: WhisperModelTier) => void;
  disabled?: boolean;
}> = ({ value, onChange, disabled }) => (
  <div className="flex items-center gap-3">
    <span className="text-[10px] font-mono text-ink-mute shrink-0">Transcription quality:</span>
    <div className="flex items-center gap-1 bg-canvas border border-hairline p-0.5 rounded-sm">
      {WHISPER_MODEL_TIERS.map((tier) => (
        <button
          key={tier}
          type="button"
          onClick={() => onChange(tier)}
          disabled={disabled}
          title={MODEL_TIER_HINTS[tier]}
          className={`px-3 py-1 rounded-sm text-[10px] font-mono transition-all disabled:opacity-40 ${
            value === tier ? 'bg-canvas-card text-ink border border-hairline-bright' : 'text-ink-mute hover:text-ink'
          }`}
        >
          {tier}
        </button>
      ))}
    </div>
    <span className="text-[10px] font-mono text-ink-mute truncate hidden sm:inline">{MODEL_TIER_HINTS[value]}</span>
  </div>
);

interface QueueItem {
  file: File;
  status: 'pending' | 'uploading' | 'queued' | 'processing' | 'done' | 'failed' | 'skipped';
  message: string;
}

interface LibraryModalProps {
  isOpen: boolean;
  onClose: () => void;
  videos: VideoItem[];
  onVideoIngested: () => void;
  backendOnline: boolean;
}



export const LibraryModal: React.FC<LibraryModalProps> = ({
  isOpen,
  onClose,
  videos,
  onVideoIngested,
  backendOnline,
}) => {
  const [ingestMode, setIngestMode] = useState<'url' | 'file' | 'folder' | 'import'>('url');
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestStatusMsg, setIngestStatusMsg] = useState<string | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);
  // Per-file status for a multi-file/folder upload — each file's upload request is submitted
  // immediately (fast: just the HTTP POST + dedup check), so they queue on the backend's
  // single-worker job executor in submission order instead of the frontend blocking on one
  // file's full transcribe/chunk/embed cycle before even starting the next upload.
  const [uploadQueue, setUploadQueue] = useState<QueueItem[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [importMode, setImportMode] = useState<'merge' | 'replace'>('merge');
  // Whisper accuracy/speed tier for local uploads (PRD §7.2) — 'base' mangles proper nouns
  // and technical vocabulary, so 'small' is the default rather than the old hardcoded 'base'.
  const [modelTier, setModelTier] = useState<WhisperModelTier>('small');

  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const totalChunks = videos.reduce((sum, v) => sum + v.chunk_count, 0);

  const handleUrlIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!youtubeUrl.trim() || !backendOnline) return;

    setIsIngesting(true);
    setIngestStatusMsg(null);
    setIngestError(null);

    try {
      const started = await ingestVideoUrl(youtubeUrl);

      if (isIngestJobStart(started)) {
        const job = await pollJob(started.job_id, (j) => {
          setUploadProgress(j.message || `${j.stage || 'working'}...`);
        });
        setUploadProgress(null);
        if (job.status === 'failed') {
          setIngestError(job.error || 'YouTube ingestion failed.');
        } else if (job.result?.success) {
          setYoutubeUrl('');
          setIngestStatusMsg(job.result.message);
        } else {
          setIngestError(job.result?.message || 'YouTube ingestion did not complete successfully.');
        }
      } else if (started.success) {
        setYoutubeUrl('');
        setIngestStatusMsg(started.message || 'Indexed.');
      } else {
        setIngestError(started.message || 'Ingestion failed.');
      }
      onVideoIngested();
      setTimeout(() => {
        setIngestStatusMsg(null);
        setIngestError(null);
      }, 6000);
    } catch (err: any) {
      setIngestError(err.message || 'Failed to ingest YouTube video.');
      onVideoIngested();
    } finally {
      setIsIngesting(false);
    }
  };

  const handleFileUpload = async (files: FileList | null) => {
    if (!backendOnline) return;

    const mediaFiles = filterMediaFiles(files);

    if (mediaFiles.length === 0) {
      setIngestError('No supported video or audio files found in selection.');
      setTimeout(() => setIngestError(null), 5000);
      return;
    }

    setIsIngesting(true);
    setIngestStatusMsg(null);
    setIngestError(null);
    setUploadQueue(mediaFiles.map((file) => ({ file, status: 'pending', message: 'Waiting to upload...' })));

    const updateItem = (idx: number, patch: Partial<QueueItem>) => {
      setUploadQueue((prev) => prev.map((item, i) => (i === idx ? { ...item, ...patch } : item)));
    };

    let processedCount = 0;
    let failedCount = 0;
    const jobPromises: Promise<void>[] = [];

    // Submit every file's upload request in sequence (each is just an HTTP POST + a cheap
    // content-hash dedup check, not the slow part) without waiting for its job to finish —
    // that's what actually queues them on the backend's single-worker executor in submission
    // order. Processing (transcribe/chunk/embed) then happens for real one at a time on the
    // backend regardless, so this doesn't overload anything; it just stops the frontend from
    // blocking file 2's upload behind file 1's entire multi-minute transcription.
    for (let i = 0; i < mediaFiles.length; i++) {
      const file = mediaFiles[i];
      updateItem(i, { status: 'uploading', message: 'Uploading...' });

      try {
        const started = await uploadLocalFile(file, modelTier);

        if (isIngestJobStart(started)) {
          updateItem(i, { status: 'queued', message: 'Queued — waiting for the backend worker...' });
          const jobPromise = pollJob(started.job_id, (j) => {
            updateItem(i, { status: 'processing', message: j.message || `${j.stage || 'processing'}...` });
          })
            .then((job) => {
              if (job.status === 'failed') {
                failedCount++;
                updateItem(i, { status: 'failed', message: job.error || 'Processing failed.' });
              } else if (job.result?.success) {
                processedCount++;
                updateItem(i, { status: 'done', message: job.result.message || 'Indexed.' });
              } else {
                failedCount++;
                updateItem(i, { status: 'failed', message: job.result?.message || 'Did not complete successfully.' });
              }
              onVideoIngested(); // reflect each file in the library as soon as it finishes, not just at the very end
            })
            .catch((err: any) => {
              failedCount++;
              updateItem(i, { status: 'failed', message: err.message || 'Processing failed.' });
            });
          jobPromises.push(jobPromise);
        } else if (started.success) {
          processedCount++;
          updateItem(i, { status: 'done', message: started.message || 'Indexed.' });
          onVideoIngested();
        } else {
          updateItem(i, { status: 'skipped', message: started.message || 'Already indexed.' });
        }
      } catch (err: any) {
        failedCount++;
        updateItem(i, { status: 'failed', message: err.message || 'Upload failed.' });
      }
    }

    await Promise.all(jobPromises);

    setIsIngesting(false);
    onVideoIngested();

    if (processedCount > 0) {
      setIngestStatusMsg(`Indexed ${processedCount} media file(s).${failedCount > 0 ? ` ${failedCount} failed.` : ''}`);
    } else if (failedCount > 0) {
      setIngestError(`All ${failedCount} file(s) failed to process. Ensure OPENAI_API_KEY is set or local Whisper is installed.`);
    }

    setTimeout(() => {
      setIngestStatusMsg(null);
      setIngestError(null);
      setUploadQueue([]);
    }, 8000);
  };

  const handleImportFile = async (files: FileList | null) => {
    if (!backendOnline || !files || files.length === 0) return;

    const file = files[0];
    if (!file.name.endsWith('.json') && !file.name.endsWith('.zip')) {
      setIngestError('Please select a CBRIN export file (.json or .zip).');
      setTimeout(() => setIngestError(null), 5000);
      return;
    }

    setIsIngesting(true);
    setIngestStatusMsg(null);
    setIngestError(null);
    setUploadProgress(`Importing ${file.name} (${importMode} mode)...`);

    try {
      const result = await importLibrary(file, importMode);
      if (result.success) {
        setIngestStatusMsg(result.message);
        onVideoIngested();
      } else {
        setIngestError(result.message || 'Import failed.');
      }
    } catch (err: any) {
      setIngestError(err.message || 'Failed to import library backup.');
    } finally {
      setUploadProgress(null);
      setIsIngesting(false);
      setTimeout(() => {
        setIngestStatusMsg(null);
        setIngestError(null);
      }, 8000);
    }
  };

  const handleDelete = async (videoId: string, title: string) => {
    if (!confirm(`Delete '${title}' and its indexed transcript chunks from your library?`)) return;

    setDeletingId(videoId);
    try {
      await deleteLibraryVideo(videoId);
      onVideoIngested();
    } catch (err: any) {
      alert(`Deletion failed: ${err.message}`);
    } finally {
      setDeletingId(null);
    }
  };

  const handleRetry = (vid: VideoItem) => {
    if (vid.youtube_id) {
      setIngestMode('url');
      setYoutubeUrl(`https://youtube.com/watch?v=${vid.youtube_id}`);
    } else {
      setIngestMode('file');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 animate-fade-in">
      <div
        className="bg-canvas-card border border-hairline-bright rounded-sm w-full max-w-3xl overflow-hidden flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-hairline bg-canvas">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-sm border border-hairline bg-canvas-soft flex items-center justify-center text-ink-body">
              <Video className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Indexed Creator Library</h2>
              <p className="eyebrow-mono text-[9px] text-ink-mute">
                {videos.length} MEDIA ITEMS // {totalChunks} CHUNKS
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-sm transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Backend Offline Warning */}
        {!backendOnline && (
          <div className="mx-6 mt-4 p-3 bg-canvas-card/40 border border-danger/30 rounded-sm text-xs text-danger font-mono flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>Backend is offline. Start the Python server to ingest content.</span>
          </div>
        )}

        {/* Ingest Mode Tabs */}
        <div className="p-6 border-b border-hairline bg-canvas-soft/40 space-y-4">
          <div className="flex items-center justify-between">
            <span className="eyebrow-mono">Index new content</span>
            <div className="flex items-center gap-1 bg-canvas border border-hairline p-1 rounded-sm text-xs font-mono">
              <button
                onClick={() => setIngestMode('url')}
                className={`px-3 py-1 rounded-sm transition-all ${ingestMode === 'url' ? 'bg-canvas-card text-ink border border-hairline-bright' : 'text-ink-mute hover:text-ink'}`}
              >
                YOUTUBE URL
              </button>
              <button
                onClick={() => setIngestMode('file')}
                className={`px-3 py-1 rounded-sm transition-all ${ingestMode === 'file' ? 'bg-canvas-card text-ink border border-hairline-bright' : 'text-ink-mute hover:text-ink'}`}
              >
                UPLOAD FILES
              </button>
              <button
                onClick={() => setIngestMode('folder')}
                className={`px-3 py-1 rounded-sm transition-all ${ingestMode === 'folder' ? 'bg-canvas-card text-ink border border-hairline-bright' : 'text-ink-mute hover:text-ink'}`}
              >
                UPLOAD FOLDER
              </button>
              <button
                onClick={() => setIngestMode('import')}
                className={`px-3 py-1 rounded-sm transition-all ${ingestMode === 'import' ? 'bg-canvas-card text-ink border border-hairline-bright' : 'text-ink-mute hover:text-ink'}`}
              >
                IMPORT BACKUP
              </button>
            </div>
          </div>

          {/* Mode 1: YouTube URL */}
          {ingestMode === 'url' && (
            <form onSubmit={handleUrlIngest} className="flex gap-2">
              <input
                type="text"
                value={youtubeUrl}
                onChange={(e) => setYoutubeUrl(e.target.value)}
                placeholder="Paste YouTube Video URL (e.g. https://youtube.com/watch?v=...)"
                disabled={!backendOnline || isIngesting}
                className="flex-1 px-4 py-2.5 bg-canvas border border-hairline rounded-sm text-xs sm:text-sm text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright disabled:opacity-40"
              />
              <button
                type="submit"
                disabled={isIngesting || !youtubeUrl.trim() || !backendOnline}
                className="px-4 py-2.5 bg-canvas-card border border-hairline-bright hover:border-accent-sunset hover:bg-accent-sunset hover:text-black rounded-sm text-xs font-medium text-ink disabled:opacity-40 transition-all flex items-center gap-1.5 shrink-0"
              >
                {isIngesting ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4" />
                )}
                <span>{isIngesting ? 'Ingesting...' : 'Ingest URL'}</span>
              </button>
            </form>
          )}

          {/* Mode 2: Local Files Upload */}
          {ingestMode === 'file' && (
            <div className="space-y-2">
              <ModelTierSelector value={modelTier} onChange={setModelTier} disabled={isIngesting || !backendOnline} />
              <input
                type="file"
                ref={fileInputRef}
                multiple
                accept="video/*,audio/*,.mp4,.mov,.webm,.mkv,.avi,.mp3,.wav,.m4a"
                onChange={(e) => handleFileUpload(e.target.files)}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isIngesting || !backendOnline}
                className="w-full py-6 border border-dashed border-hairline-bright hover:border-accent-sunset bg-canvas/60 rounded-sm flex flex-col items-center justify-center gap-2 group transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Upload className="w-5 h-5 text-ink-mute group-hover:text-ink-body transition-colors" />
                <span className="text-xs font-medium text-ink">
                  Click to select one or more local video/audio files (.mp4, .mov, .mp3, .wav)
                </span>
                <span className="text-[10px] font-mono text-ink-mute">SELECT MULTIPLE FILES TO QUEUE THEM — PROCESSED ONE AT A TIME AUTOMATICALLY</span>
              </button>
            </div>
          )}

          {/* Mode 3: Local Folder Upload */}
          {ingestMode === 'folder' && (
            <div className="space-y-2">
              <ModelTierSelector value={modelTier} onChange={setModelTier} disabled={isIngesting || !backendOnline} />
              <input
                type="file"
                ref={folderInputRef}
                // @ts-ignore
                webkitdirectory="true"
                directory="true"
                onChange={(e) => handleFileUpload(e.target.files)}
                className="hidden"
              />
              <button
                onClick={() => folderInputRef.current?.click()}
                disabled={isIngesting || !backendOnline}
                className="w-full py-6 border border-dashed border-hairline-bright hover:border-accent-sunset bg-canvas/60 rounded-sm flex flex-col items-center justify-center gap-2 group transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <FolderUp className="w-5 h-5 text-ink-mute group-hover:text-ink-body transition-colors" />
                <span className="text-xs font-medium text-ink">
                  Select an entire folder of videos/podcasts from your computer
                </span>
                <span className="text-[10px] font-mono text-ink-mute font-sans">All media transcribed and embedded automatically</span>
              </button>
            </div>
          )}

          {/* Mode 4: Import Backup */}
          {ingestMode === 'import' && (
            <div className="space-y-3">
              {/* Merge / Replace toggle */}
              <div className="flex items-center gap-3">
                <span className="text-[10px] font-mono text-ink-mute">Import mode:</span>
                <div className="flex items-center gap-1 bg-canvas border border-hairline p-0.5 rounded-sm">
                  <button
                    onClick={() => setImportMode('merge')}
                    className={`px-3 py-1 rounded-sm text-[10px] font-mono transition-all ${importMode === 'merge' ? 'bg-canvas-card text-ink border border-hairline-bright' : 'text-ink-mute hover:text-ink'}`}
                  >
                    MERGE (SKIP DUPLICATES)
                  </button>
                  <button
                    onClick={() => setImportMode('replace')}
                    className={`px-3 py-1 rounded-sm text-[10px] font-mono transition-all ${importMode === 'replace' ? 'bg-canvas-card/60 text-danger border border-danger/40' : 'text-ink-mute hover:text-ink'}`}
                  >
                    REPLACE (WIPE & RESTORE)
                  </button>
                </div>
              </div>

              <input
                type="file"
                ref={importInputRef}
                accept=".json,.zip"
                onChange={(e) => handleImportFile(e.target.files)}
                className="hidden"
              />
              <button
                onClick={() => importInputRef.current?.click()}
                disabled={isIngesting || !backendOnline}
                className="w-full py-6 border border-dashed border-hairline-bright hover:border-accent-sunset bg-canvas/60 rounded-sm flex flex-col items-center justify-center gap-2 group transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <FileUp className="w-5 h-5 text-ink-mute group-hover:text-ink-body transition-colors" />
                <span className="text-xs font-medium text-ink">
                  Select a CBRIN library export (.json or .zip) to restore
                </span>
                <span className="text-[10px] font-mono text-ink-mute">
                  {importMode === 'merge' ? 'NEW ITEMS ADDED, DUPLICATES SKIPPED' : 'WARNING: CURRENT LIBRARY WILL BE REPLACED'}
                </span>
              </button>
            </div>
          )}

          {/* Multi-file Upload Queue (file / folder modes) */}
          {uploadQueue.length > 0 && (
            <div className="border border-hairline-bright rounded-sm overflow-hidden animate-fade-in">
              <div className="px-3 py-2 bg-canvas-soft border-b border-hairline flex items-center justify-between">
                <span className="text-[10px] font-mono text-ink-mute">
                  Upload queue ({uploadQueue.filter((q) => q.status === 'done').length}/{uploadQueue.length} done)
                </span>
              </div>
              <div className="max-h-48 overflow-y-auto divide-y divide-hairline/40">
                {uploadQueue.map((item, idx) => (
                  <div key={idx} className="px-3 py-2 flex items-center gap-2 bg-canvas">
                    <div className="shrink-0">
                      {item.status === 'done' ? (
                        <Check className="w-3.5 h-3.5 text-ink" />
                      ) : item.status === 'failed' ? (
                        <AlertCircle className="w-3.5 h-3.5 text-danger" />
                      ) : item.status === 'skipped' ? (
                        <AlertTriangle className="w-3.5 h-3.5 text-ink-body" />
                      ) : item.status === 'pending' ? (
                        <div className="w-3.5 h-3.5 rounded-sm border border-hairline-bright" />
                      ) : (
                        <Loader2 className="w-3.5 h-3.5 text-ink-body animate-spin" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-ink truncate">{item.file.name}</p>
                      <p className="text-[10px] font-mono text-ink-mute truncate">{item.message}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Upload Progress (single-item flows: YouTube URL, import backup) */}
          {uploadProgress && (
            <div className="p-3 bg-canvas border border-hairline-bright rounded-sm text-xs text-ink flex items-center gap-2 animate-fade-in font-mono">
              <Loader2 className="w-4 h-4 text-ink-body animate-spin shrink-0" />
              <span>{uploadProgress}</span>
            </div>
          )}

          {/* Success Message */}
          {ingestStatusMsg && (
            <div className="p-3 bg-canvas border border-hairline-bright rounded-sm text-xs text-ink flex items-center gap-2 animate-fade-in">
              <Check className="w-4 h-4 text-ink shrink-0" />
              <span>{ingestStatusMsg}</span>
            </div>
          )}

          {/* Error Message */}
          {ingestError && (
            <div className="p-3 bg-canvas-card/40 border border-danger/30 rounded-sm text-xs text-danger flex items-center gap-2 animate-fade-in">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{ingestError}</span>
            </div>
          )}
        </div>

        {/* Video List with Status Badges */}
        <div className="p-6 overflow-y-auto space-y-3 divide-y divide-hairline/40">
          {videos.length === 0 ? (
            <div className="text-center py-8 text-xs text-ink-mute font-mono">
              No media files indexed yet. Choose YouTube URL, Upload Files, Upload Folder, or Import Backup above.
            </div>
          ) : (
            videos.map((vid) => {
              const isFailed = vid.status === 'failed';
              const isIndexing = vid.status === 'indexing';
              const hasVisual = (vid.visual_chunk_count ?? 0) > 0;

              return (
                <div key={vid.id} className="pt-3 first:pt-0 flex items-start gap-4 group">
                  <img
                    src={vid.thumbnail_url || 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><rect fill="%23191919" width="160" height="90"/><text x="80" y="50" fill="%237d8187" font-size="12" text-anchor="middle">No Thumbnail</text></svg>'}
                    alt={vid.title}
                    className="w-24 h-14 object-cover rounded border border-hairline bg-canvas-soft shrink-0"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] font-mono text-ink-body">
                        {vid.category || (vid.is_local ? 'Local Upload' : 'YouTube')}
                      </span>
                      <span className="text-ink-mute text-xs">•</span>
                      <span className="text-xs font-mono text-ink-mute">{vid.duration_formatted}</span>

                      {/* Status Badge */}
                      {isFailed ? (
                        <span className="px-2 py-0.5 rounded-sm border border-danger/60 bg-canvas-card/60 text-[9px] font-mono text-danger flex items-center gap-1">
                          <AlertTriangle className="w-3 h-3 text-danger" />
                          <span>Indexing failed</span>
                        </span>
                      ) : isIndexing ? (
                        <span className="px-2 py-0.5 rounded-sm border border-hairline-bright/60 bg-canvas-card/60 text-[9px] font-mono text-ink-body flex items-center gap-1">
                          <Loader2 className="w-3 h-3 text-ink-body animate-spin" />
                          <span>Indexing…</span>
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-sm border border-canvas-card/60 bg-canvas-card/60 text-[9px] font-mono text-ink flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3 text-ink" />
                          <span>Fully indexed</span>
                        </span>
                      )}

                      {/* Visual / Text index indicator */}
                      {!isFailed && !isIndexing && (
                        <span className={`px-1.5 py-0.5 rounded-sm border text-[9px] font-mono flex items-center gap-0.5 ${hasVisual ? 'border-canvas-card/40 bg-canvas-card/30 text-ink' : 'border-hairline bg-canvas-soft text-ink-mute'}`}
                          title={hasVisual ? `${vid.visual_chunk_count} chunks with CLIP visual embeddings` : 'Text-only (no visual embeddings)'}
                        >
                          {hasVisual ? <Eye className="w-2.5 h-2.5" /> : <FileText className="w-2.5 h-2.5" />}
                          <span>{hasVisual ? 'VISUAL' : 'TEXT'}</span>
                        </span>
                      )}
                    </div>

                    <h4 className="text-xs sm:text-sm font-medium text-ink truncate group-hover:text-ink-body transition-colors mt-0.5">
                      {vid.title}
                    </h4>

                    {isFailed ? (
                      <p className="text-[11px] text-danger font-mono mt-0.5">
                        Error: {vid.error_message || 'Transcription/ingestion failed.'}
                      </p>
                    ) : (
                      <p className="text-[11px] text-ink-mute font-mono mt-0.5">
                        {vid.chunk_count} chunks indexed • {relativeTime(vid.uploaded_at)}
                      </p>
                    )}
                  </div>

                  {/* Item Action Controls */}
                  <div className="flex items-center gap-1 shrink-0">
                    {isFailed && (
                      <button
                        onClick={() => handleRetry(vid)}
                        className="p-1.5 text-ink-body hover:text-ink-body hover:bg-canvas-soft rounded transition-colors"
                        title="Retry Ingestion"
                      >
                        <RotateCcw className="w-4 h-4" />
                      </button>
                    )}

                    {vid.youtube_id && (
                      <a
                        href={`https://youtube.com/watch?v=${vid.youtube_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 text-ink-mute hover:text-ink transition-colors"
                        title="Watch on YouTube"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </a>
                    )}

                    <button
                      onClick={() => handleDelete(vid.id, vid.title)}
                      disabled={deletingId === vid.id}
                      className="p-1.5 text-ink-mute hover:text-danger hover:bg-canvas-soft rounded transition-colors disabled:opacity-40"
                      title="Delete Video"
                    >
                      {deletingId === vid.id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Trash2 className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
