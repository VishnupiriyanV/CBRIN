import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bot, Send, Square, Loader2, ChevronDown, ChevronUp, Search, Video, FileText, Cpu,
  Sparkles, Package, Activity,
} from 'lucide-react';
import { VideoItem, AgentChatMessage, AgentToolStep, AgentUsage, ContentPack } from '../../types';
import { studioAgentChat, studioAgentChatStream } from '../../services/api';
import { ContentPackArtifact } from './ContentPackArtifact';
import { segmentContentWithCitations } from './citations';
import { CopyButton } from '../ui/CopyButton';
import { VideoPlayerModal } from '../VideoPlayerModal';
import { ChunkResult } from '../../types';

interface AgentWorkspaceProps {
  videos: VideoItem[];
  backendOnline: boolean;
}

const PROMPT_SUGGESTIONS = [
  'Turn my latest video into a week of LinkedIn and X content',
  'What have I said about pricing across my videos?',
  'Find quotes about scaling and draft 3 viral titles',
  'Extract the top 3 clip candidates from my latest video',
];

function getToolIcon(toolName: string) {
  switch (toolName) {
    case 'search_vault':
    case 'deep_research':
      return <Search className="w-3.5 h-3.5 text-ink-mute" />;
    case 'extract_video_clips':
      return <Video className="w-3.5 h-3.5 text-ink-mute" />;
    case 'run_studio_tool':
      return <FileText className="w-3.5 h-3.5 text-ink-mute" />;
    case 'generate_content_pack':
      return <Package className="w-3.5 h-3.5 text-ink-body" />;
    default:
      return <Cpu className="w-3.5 h-3.5 text-ink-mute" />;
  }
}

function nowLabel(): string {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function buildChunkResultFromCitation(title: string, seconds: number, video: VideoItem): ChunkResult {
  return {
    id: `citation-${video.id}-${seconds}`,
    video_id: video.id,
    video_title: video.title,
    channel: video.channel,
    youtube_id: video.youtube_id,
    is_local: video.is_local,
    start_sec: seconds,
    end_sec: seconds + 20,
    start_timestamp: `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`,
    end_timestamp: `${Math.floor((seconds + 20) / 60)}:${String(Math.floor((seconds + 20) % 60)).padStart(2, '0')}`,
    text: title,
    score: 1,
    matched_concepts: [],
    thumbnail_url: video.thumbnail_url,
  };
}

export const AgentWorkspace: React.FC<AgentWorkspaceProps> = ({ videos, backendOnline }) => {
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [liveSteps, setLiveSteps] = useState<AgentToolStep[]>([]);
  const [runningTool, setRunningTool] = useState<string | null>(null);
  const [selectedVideoId, setSelectedVideoId] = useState<string>('');
  const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({});
  const [usage, setUsage] = useState<AgentUsage | null>(null);
  const [selectedResult, setSelectedResult] = useState<ChunkResult | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!selectedVideoId && videos.length > 0) setSelectedVideoId(videos[0].id);
  }, [videos, selectedVideoId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent, liveSteps]);

  const videoByTitle = useMemo(() => {
    const map = new Map<string, VideoItem>();
    for (const v of videos) map.set(v.title.trim().toLowerCase(), v);
    return map;
  }, [videos]);

  const handleOpenCitation = (title: string, seconds: number) => {
    const video = videoByTitle.get(title.trim().toLowerCase());
    if (!video) return;
    setSelectedResult(buildChunkResultFromCitation(title, seconds, video));
  };

  const renderContent = (content: string) => {
    const segments = segmentContentWithCitations(content);
    return segments.map((seg, i) => {
      if (seg.kind === 'text') return <React.Fragment key={i}>{seg.content}</React.Fragment>;
      const known = videoByTitle.has(seg.citation.title.trim().toLowerCase());
      return (
        <button
          key={i}
          type="button"
          disabled={!known}
          onClick={() => handleOpenCitation(seg.citation.title, seg.citation.seconds)}
          className={`inline-flex items-center gap-1 mx-0.5 px-1.5 py-0.5 rounded text-[11px] font-mono border align-baseline ${
            known
              ? 'border-accent-sunset/40 text-ink-body bg-accent-sunset/10 hover:bg-accent-sunset hover:text-black transition-colors cursor-pointer'
              : 'border-hairline text-ink-mute cursor-default'
          }`}
          title={known ? `Jump to ${seg.citation.timestamp} in "${seg.citation.title}"` : 'Video not found in library'}
        >
          {seg.citation.title} @ {seg.citation.timestamp}
        </button>
      );
    });
  };

  const toggleStepExpansion = (key: string) => {
    setExpandedSteps((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleStop = () => {
    abortRef.current?.abort();
  };

  const handleSend = async (customPrompt?: string) => {
    const text = (customPrompt || input).trim();
    if (!text || isStreaming) return;

    const userMsg: AgentChatMessage = { id: `user-${Date.now()}`, role: 'user', content: text, timestamp: nowLabel() };
    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    if (!customPrompt) setInput('');

    setIsStreaming(true);
    setStreamingContent('');
    setLiveSteps([]);
    setRunningTool(null);

    const payload = nextMessages.map((m) => ({ role: m.role, content: m.content }));
    const controller = new AbortController();
    abortRef.current = controller;

    const finalizeAssistantMessage = (content: string, steps: AgentToolStep[]) => {
      setMessages((prev) => [...prev, {
        id: `assistant-${Date.now()}`, role: 'assistant', content, steps, timestamp: nowLabel(),
      }]);
    };

    try {
      let gatheredSteps: AgentToolStep[] = [];
      await studioAgentChatStream(payload, selectedVideoId || undefined, (event) => {
        switch (event.type) {
          case 'token':
            setStreamingContent((prev) => prev + event.content);
            break;
          case 'tool_start':
            setRunningTool(event.tool);
            break;
          case 'tool_result': {
            const step: AgentToolStep = { tool: event.tool, args: event.args, summary: event.summary, data: event.data };
            gatheredSteps = [...gatheredSteps, step];
            setLiveSteps(gatheredSteps);
            setRunningTool(null);
            break;
          }
          case 'usage':
            setUsage(event.usage);
            break;
          case 'done':
            finalizeAssistantMessage(event.reply, gatheredSteps);
            break;
          case 'error':
            finalizeAssistantMessage(`Agent execution failed: ${event.message}`, gatheredSteps);
            break;
        }
      }, controller.signal);
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        finalizeAssistantMessage('Stopped.', liveSteps);
      } else {
        // Streaming endpoint never started (e.g. transient network error) — fall back to
        // the blocking endpoint rather than leaving the user with nothing.
        try {
          const res = await studioAgentChat(payload, selectedVideoId || undefined);
          finalizeAssistantMessage(res.reply, res.steps);
          if (res.usage) setUsage(res.usage);
        } catch (fallbackErr: any) {
          finalizeAssistantMessage(`Agent execution failed: ${fallbackErr.message || err.message || 'Unable to complete request.'}`, []);
        }
      }
    } finally {
      setIsStreaming(false);
      setStreamingContent('');
      setLiveSteps([]);
      setRunningTool(null);
      abortRef.current = null;
    }
  };

  const renderSteps = (msgId: string, steps: AgentToolStep[]) => (
    <div className="mb-3 space-y-1.5">
      <div className="eyebrow-mono text-[10px] text-ink-mute mb-1">Tools Executed ({steps.length})</div>
      {steps.map((step, idx) => {
        const key = `${msgId}-step-${idx}`;
        const isExpanded = expandedSteps[key];
        return (
          <div key={key} className="bg-canvas-soft rounded-sm border border-hairline overflow-hidden">
            <button
              onClick={() => toggleStepExpansion(key)}
              className="w-full px-3 py-1.5 flex items-center justify-between text-left hover:bg-canvas-card transition-colors text-xs"
            >
              <div className="flex items-center space-x-2 truncate">
                {getToolIcon(step.tool)}
                <span className="font-mono text-[11px] text-ink truncate">{step.summary}</span>
              </div>
              {isExpanded ? <ChevronUp className="w-3 h-3 text-ink-mute" /> : <ChevronDown className="w-3 h-3 text-ink-mute" />}
            </button>
            {isExpanded && step.data && (
              <div className="p-2.5 border-t border-hairline bg-canvas-card font-mono text-[10px] text-ink-mute overflow-x-auto max-h-36">
                <pre>{JSON.stringify(step.data, null, 2)}</pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );

  const contentPackForMessage = (steps?: AgentToolStep[]): ContentPack | null => {
    const step = steps?.find((s) => s.tool === 'generate_content_pack');
    if (!step?.data || 'error' in step.data) return null;
    return step.data as unknown as ContentPack;
  };

  return (
    <div className="flex flex-col lg:flex-row gap-6 min-h-[72vh]">
      {/* Main conversation column */}
      <div className="flex-1 min-w-0 flex flex-col bg-canvas-card border border-hairline-bright rounded-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-hairline bg-canvas-soft gap-3">
          <div className="flex items-center space-x-3 min-w-0">
            <div className="w-8 h-8 rounded-sm bg-canvas-card border border-hairline-bright flex items-center justify-center text-ink-body shrink-0">
              <Bot className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center space-x-2">
                <h3 className="text-sm font-medium text-ink">CBRIN Agent</h3>
                <span className="px-2 py-0.5 text-[10px] font-mono text-ink-mute bg-canvas-card border border-hairline rounded inline-flex items-center gap-1">
                  {isStreaming ? (
                    <>
                      <Loader2 className="w-2.5 h-2.5 animate-spin text-ink-body" />
                      {runningTool ? `Running ${runningTool}…` : 'Thinking…'}
                    </>
                  ) : (
                    <>
                      <span className="w-1.5 h-1.5 rounded-sm bg-ink" />
                      Idle
                    </>
                  )}
                </span>
              </div>
              <p className="text-xs text-ink-mute truncate">Autonomous Vault, ENGINE & STUDIO orchestrator</p>
            </div>
          </div>

          {videos.length > 0 && (
            <select
              value={selectedVideoId}
              onChange={(e) => setSelectedVideoId(e.target.value)}
              className="bg-canvas-card text-ink text-xs border border-hairline rounded-sm px-2 py-1 max-w-[200px] truncate focus:outline-none focus:border-hairline-bright shrink-0"
            >
              <option value="">All Library Videos</option>
              {videos.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
            </select>
          )}
        </div>

        {/* Message thread */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 text-xs font-sans">
          {messages.length === 0 && !isStreaming && (
            <div className="h-full flex flex-col items-center justify-center text-center py-10 space-y-2">
              <div className="w-10 h-10 rounded-sm border border-hairline-bright bg-canvas-soft flex items-center justify-center text-ink-body">
                <Sparkles className="w-4 h-4" />
              </div>
              <p className="text-sm text-ink font-medium">Ask the agent to research, plan, or ship content.</p>
              <p className="text-xs text-ink-mute max-w-sm">
                It searches your Vault, extracts clips with ENGINE, and drafts multi-platform content packs with Studio — autonomously.
              </p>
            </div>
          )}

          {messages.map((msg) => {
            const pack = contentPackForMessage(msg.steps);
            return (
              <div key={msg.id} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div className="flex items-center space-x-2 mb-1 px-1">
                  <span className="text-[11px] font-medium text-ink-mute">{msg.role === 'user' ? 'You' : 'Agent'}</span>
                  <span className="text-[10px] text-ink-mute font-mono">{msg.timestamp}</span>
                </div>
                <div className={`max-w-[92%] rounded-sm p-4 border ${msg.role === 'user' ? 'bg-canvas-soft border-hairline-bright text-ink' : 'bg-canvas-card border-hairline text-ink-body'}`}>
                  {msg.steps && msg.steps.length > 0 && renderSteps(msg.id, msg.steps)}
                  <div className="whitespace-pre-wrap leading-relaxed">{renderContent(msg.content)}</div>
                  {pack && (
                    <div className="mt-3">
                      <ContentPackArtifact pack={pack} />
                    </div>
                  )}
                  {msg.role === 'assistant' && (
                    <div className="mt-3 pt-2.5 border-t border-hairline flex items-center justify-end gap-2 text-xs">
                      <CopyButton text={msg.content} />
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {isStreaming && (
            <div className="flex flex-col items-start space-y-1">
              <span className="text-[11px] font-medium text-ink-mute px-1">Agent</span>
              <div className="max-w-[92%] bg-canvas-card border border-hairline rounded-sm p-4 text-xs text-ink-body space-y-2">
                {liveSteps.length > 0 && renderSteps('live', liveSteps)}
                {runningTool && !streamingContent && (
                  <div className="flex items-center gap-2 text-ink-mute">
                    <Loader2 className="w-3.5 h-3.5 text-ink-body animate-spin" />
                    <span>Running {runningTool}…</span>
                  </div>
                )}
                {streamingContent && (
                  <div className="whitespace-pre-wrap leading-relaxed">{renderContent(streamingContent)}<span className="inline-block w-1.5 h-3 bg-accent-sunset/70 ml-0.5 animate-pulse align-middle" /></div>
                )}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Prompt suggestions */}
        {messages.length === 0 && !isStreaming && (
          <div className="px-5 py-2.5 border-t border-hairline bg-canvas-soft">
            <div className="eyebrow-mono text-[10px] text-ink-mute mb-2">Try asking</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {PROMPT_SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => handleSend(s)}
                  className="text-left text-xs bg-canvas-card hover:bg-canvas-soft text-ink-body hover:text-ink border border-hairline hover:border-hairline-bright rounded-sm px-2.5 py-1.5 transition-colors line-clamp-1"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Input */}
        <div className="p-4 border-t border-hairline bg-canvas-card">
          <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="flex items-center space-x-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask the agent to research, extract clips, or build a content pack…"
              disabled={isStreaming || !backendOnline}
              className="flex-1 bg-canvas-soft border border-hairline-bright rounded-sm px-3.5 py-2 text-xs text-ink placeholder:text-ink-mute focus:outline-none focus:border-hairline-bright disabled:opacity-50"
            />
            {isStreaming ? (
              <button
                type="button"
                onClick={handleStop}
                className="px-3.5 py-2 bg-canvas-soft hover:bg-canvas-card text-danger border border-danger/40 rounded-sm text-xs font-medium transition-colors flex items-center space-x-1.5"
              >
                <Square className="w-3.5 h-3.5" />
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() || !backendOnline}
                className="px-3.5 py-2 bg-canvas-soft hover:bg-canvas-card text-ink border border-hairline-bright rounded-sm text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center space-x-1.5"
              >
                <Send className="w-3.5 h-3.5 text-ink-body" />
                <span>Send</span>
              </button>
            )}
          </form>
        </div>
      </div>

      {/* Live tool timeline / usage side panel */}
      <div className="w-full lg:w-72 shrink-0 space-y-3">
        <div className="bg-canvas-card border border-hairline rounded-sm p-4 space-y-3">
          <div className="eyebrow-mono text-[10px] text-ink-mute flex items-center gap-1.5">
            <Activity className="w-3 h-3 text-ink-body" />
            Live Activity
          </div>
          {isStreaming ? (
            liveSteps.length > 0 || runningTool ? (
              <div className="space-y-1.5">
                {liveSteps.map((step, idx) => (
                  <div key={idx} className="flex items-start gap-2 text-[11px] text-ink-body">
                    {getToolIcon(step.tool)}
                    <span className="leading-snug">{step.summary}</span>
                  </div>
                ))}
                {runningTool && (
                  <div className="flex items-center gap-2 text-[11px] text-ink-mute">
                    <Loader2 className="w-3 h-3 text-ink-body animate-spin" />
                    <span>{runningTool}…</span>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-[11px] text-ink-mute">Reasoning…</p>
            )
          ) : (
            <p className="text-[11px] text-ink-mute">No agent turn in progress. Tool activity will stream here live.</p>
          )}
        </div>

        {usage && (
          <div className="bg-canvas-card border border-hairline rounded-sm p-4 space-y-1.5">
            <div className="eyebrow-mono text-[10px] text-ink-mute">Last Turn Usage</div>
            <p className="text-[11px] text-ink-body font-mono">{usage.prompt_tokens} in / {usage.completion_tokens} out tokens</p>
            <p className="text-[10px] text-ink-mute font-mono">{usage.model}</p>
          </div>
        )}
      </div>

      <VideoPlayerModal result={selectedResult} onClose={() => setSelectedResult(null)} />
    </div>
  );
};
