import React from 'react';
import { VideoItem, LibraryStats } from '../types';
import { X, CheckCircle2, AlertTriangle, Loader2, Sparkles, Eye, FileText, Activity, Server, Cpu, Database, RotateCcw } from 'lucide-react';

interface IndexingProgressModalProps {
  isOpen: boolean;
  onClose: () => void;
  videos: VideoItem[];
  stats: LibraryStats | null;
  backendOnline: boolean;
  onRefresh: () => void;
}

export const IndexingProgressModal: React.FC<IndexingProgressModalProps> = ({
  isOpen,
  onClose,
  videos,
  stats,
  backendOnline,
  onRefresh,
}) => {
  if (!isOpen) return null;

  const totalVideos = stats?.total_videos || videos.length;
  const indexedCount = stats?.indexed_count || videos.filter(v => v.status === 'fully_indexed').length;
  const failedCount = stats?.failed_count || videos.filter(v => v.status === 'failed').length;
  const indexingCount = stats?.indexing_count || videos.filter(v => v.status === 'indexing').length;
  const totalChunks = stats?.total_chunks || videos.reduce((acc, v) => acc + v.chunk_count, 0);
  const visualIndexedCount = stats?.visual_indexed_count || 0;

  // Calculate overall percentage
  const progressPercent = totalVideos > 0 ? Math.round((indexedCount / totalVideos) * 100) : 0;
  const visualPercent = totalChunks > 0 ? Math.round((visualIndexedCount / totalChunks) * 100) : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/85 animate-fade-in">
      <div
        className="bg-canvas-card border border-hairline-bright rounded-sm w-full max-w-4xl overflow-hidden flex flex-col max-h-[88vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-hairline bg-canvas">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-sm border border-accent-sunset/40 bg-accent-sunset/10 flex items-center justify-center text-ink-body">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Indexing Pipeline & Telemetry</h2>
              <p className="eyebrow-mono text-[9px] text-ink-mute">
                MULTIMODAL INGESTION ENGINE // REAL-TIME STATUS
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onRefresh}
              className="p-2 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-sm transition-colors"
              title="Refresh telemetry"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-2 text-ink-mute hover:text-ink hover:bg-canvas-soft rounded-sm transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="p-6 overflow-y-auto space-y-6">

          {/* Overall Health Overview Banner */}
          <div className="bg-[#121215] border border-hairline rounded-sm p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-sm ${backendOnline ? (indexingCount > 0 ? 'bg-ink-body' : 'bg-ink') : 'bg-danger'}`} />
                <div>
                  <h3 className="text-sm font-semibold text-ink tracking-tight">
                    {backendOnline ? (indexingCount > 0 ? 'Indexing In Progress' : 'Library Fully Synced') : 'Backend Offline'}
                  </h3>
                  <span className="text-xs font-mono text-ink-mute">
                    {indexedCount} OF {totalVideos} MEDIA ITEMS FULLY EMBEDDED ({progressPercent}%)
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2 font-mono text-xs text-ink-mute">
                <Server className="w-3.5 h-3.5 text-ink-body" />
                <span>MODEL: {stats?.embedding_model || 'MiniLM-L6-v2 + CLIP'}</span>
              </div>
            </div>

            {/* Main Progress Bar */}
            <div className="space-y-1.5">
              <div className="h-2.5 w-full bg-canvas-soft rounded-sm overflow-hidden border border-hairline flex">
                <div
                  className="h-full bg-accent-sunset transition-all duration-500"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[10px] font-mono text-ink-mute">
                <span>{indexedCount} READY</span>
                <span>{indexingCount} IN QUEUE</span>
                <span>{failedCount} FAILED</span>
              </div>
            </div>
          </div>

          {/* Detailed Pipeline Stage Breakdown Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            
            {/* Stage 1: Whisper Transcription */}
            <div className="bg-canvas-soft/60 border border-hairline rounded-sm p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="eyebrow-mono text-[9px]">1. TRANSCRIPTION</span>
                <Cpu className="w-3.5 h-3.5 text-ink-body" />
              </div>
              <p className="text-xs font-semibold text-ink">Whisper Speech-to-Text</p>
              <div className="text-[11px] font-mono text-ink-mute flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-ink" />
                <span>Word Timestamps Preserved</span>
              </div>
            </div>

            {/* Stage 2: Chunking & Enrichment */}
            <div className="bg-canvas-soft/60 border border-hairline rounded-sm p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="eyebrow-mono text-[9px]">2. CHUNKING & NLP</span>
                <Sparkles className="w-3.5 h-3.5 text-ink-body" />
              </div>
              <p className="text-xs font-semibold text-ink">{totalChunks} Chunks Generated</p>
              <div className="text-[11px] font-mono text-ink-mute">
                <span>Sentence-Level Segmentation</span>
              </div>
            </div>

            {/* Stage 3: CLIP Visual Scene Embedding */}
            <div className="bg-canvas-soft/60 border border-hairline rounded-sm p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="eyebrow-mono text-[9px]">3. VISUAL EMBEDDINGS</span>
                <Eye className="w-3.5 h-3.5 text-ink" />
              </div>
              <p className="text-xs font-semibold text-ink">{visualIndexedCount}/{totalChunks} Keyframes ({visualPercent}%)</p>
              <div className="h-1.5 w-full bg-canvas rounded-sm overflow-hidden border border-hairline">
                <div className="h-full bg-ink transition-all" style={{ width: `${visualPercent}%` }} />
              </div>
            </div>

            {/* Stage 4: Dense Vector Index */}
            <div className="bg-canvas-soft/60 border border-hairline rounded-sm p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="eyebrow-mono text-[9px]">4. VECTOR INDEX</span>
                <Database className="w-3.5 h-3.5 text-ink-body" />
              </div>
              <p className="text-xs font-semibold text-ink">{stats?.is_fitted ? 'Vector Store Fitted' : 'Ready'}</p>
              <div className="text-[11px] font-mono text-ink-mute flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-ink" />
                <span>384-dim Dense Index</span>
              </div>
            </div>
          </div>

          {/* Media Items Processing Queue */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="eyebrow-mono">MEDIA INDEXING QUEUE ({videos.length})</span>
              <span className="text-[11px] font-mono text-ink-mute">{stats?.total_hours || '0h 0m'} Total Spoken Content</span>
            </div>

            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              {videos.length === 0 ? (
                <div className="text-center py-6 text-xs text-ink-mute font-mono border border-dashed border-hairline rounded-sm">
                  No items in queue. Use 'Index New' to add media files.
                </div>
              ) : (
                videos.map((vid) => {
                  const isFailed = vid.status === 'failed';
                  const isIndexing = vid.status === 'indexing';
                  const hasVisual = (vid.visual_chunk_count ?? 0) > 0;

                  return (
                    <div
                      key={vid.id}
                      className="bg-canvas-soft border border-hairline rounded-sm p-3.5 flex items-center justify-between gap-4"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        {vid.thumbnail_url ? (
                          <img
                            src={vid.thumbnail_url}
                            alt={vid.title}
                            className="w-14 h-9 object-cover rounded border border-hairline shrink-0"
                          />
                        ) : (
                          <div className="w-14 h-9 rounded bg-canvas border border-hairline flex items-center justify-center text-ink-mute shrink-0">
                            <FileText className="w-4 h-4" />
                          </div>
                        )}

                        <div className="min-w-0 space-y-0.5">
                          <h4 className="text-xs font-medium text-ink truncate">{vid.title}</h4>
                          <div className="flex items-center gap-2 text-[10px] font-mono text-ink-mute">
                            <span>{vid.duration_formatted}</span>
                            <span>•</span>
                            <span>{vid.chunk_count} chunks</span>
                            {hasVisual && (
                              <>
                                <span>•</span>
                                <span className="text-ink flex items-center gap-0.5">
                                  <Eye className="w-2.5 h-2.5" /> VISUAL INDEXED
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Status Badge */}
                      <div className="shrink-0">
                        {isFailed ? (
                          <span className="px-2.5 py-1 rounded-sm border border-danger/60 bg-canvas-card/60 text-[10px] font-mono text-danger flex items-center gap-1">
                            <AlertTriangle className="w-3 h-3 text-danger" />
                            <span>FAILED</span>
                          </span>
                        ) : isIndexing ? (
                          <span className="px-2.5 py-1 rounded-sm border border-hairline-bright/60 bg-canvas-card/60 text-[10px] font-mono text-ink-body flex items-center gap-1">
                            <Loader2 className="w-3 h-3 text-ink-body animate-spin" />
                            <span>PROCESSING</span>
                          </span>
                        ) : (
                          <span className="px-2.5 py-1 rounded-sm border border-canvas-card/60 bg-canvas-card/60 text-[10px] font-mono text-ink flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3 text-ink" />
                            <span>100% DONE</span>
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
