import React, { useState } from 'react';
import { Download, Film, Megaphone, Type, FileText, Hash, AlertTriangle } from 'lucide-react';
import { ContentPack, CaptionResult } from '../../types';
import { OutputBlock } from '../ui/OutputBlock';
import { Pill, Tag } from '../ui/Pill';

interface ContentPackArtifactProps {
  pack: ContentPack;
}

type TabId = 'clips' | 'repurposed' | 'titles' | 'show_notes' | 'captions';

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'clips', label: 'Clips', icon: <Film className="w-3 h-3" /> },
  { id: 'repurposed', label: 'Posts', icon: <Megaphone className="w-3 h-3" /> },
  { id: 'titles', label: 'Titles', icon: <Type className="w-3 h-3" /> },
  { id: 'show_notes', label: 'Show Notes', icon: <FileText className="w-3 h-3" /> },
  { id: 'captions', label: 'Captions', icon: <Hash className="w-3 h-3" /> },
];

function isCaptionResult(v: unknown): v is CaptionResult {
  return !!v && typeof v === 'object' && 'caption' in (v as Record<string, unknown>);
}

function downloadContentPack(pack: ContentPack) {
  const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  const slug = (pack.video_title || pack.video_id).toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 40);
  link.download = `content_pack_${slug}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export const ContentPackArtifact: React.FC<ContentPackArtifactProps> = ({ pack }) => {
  const firstAvailable = TABS.find((t) => t.id === 'clips' ? pack.clips.length > 0 : !!(pack as any)[t.id]);
  const [tab, setTab] = useState<TabId>(firstAvailable?.id || 'repurposed');

  const errorCount = Object.keys(pack.errors || {}).length;

  return (
    <div className="bg-canvas-soft border border-hairline-bright rounded-sm overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-hairline bg-canvas-card gap-2">
        <div className="min-w-0">
          <span className="eyebrow-mono text-[9px] block text-ink-body">CONTENT PACK</span>
          <h4 className="text-sm font-medium text-ink truncate">{pack.video_title}</h4>
        </div>
        <button
          type="button"
          onClick={() => downloadContentPack(pack)}
          className="shrink-0 px-2.5 py-1.5 rounded-sm border border-hairline text-[11px] font-mono text-ink-mute hover:border-hairline-bright hover:text-ink transition-all inline-flex items-center gap-1.5"
        >
          <Download className="w-3 h-3" />
          Download pack
        </button>
      </div>

      {errorCount > 0 && (
        <div className="px-4 pt-3">
          <div className="bg-canvas-card/30 border border-hairline-bright/30 rounded-sm p-2.5 text-xs text-ink-body font-mono flex items-start gap-2">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{errorCount} section(s) failed to generate: {Object.keys(pack.errors).join(', ')}. The rest of the pack is still usable.</span>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5 px-4 pt-3">
        {TABS.map((t) => (
          <Pill key={t.id} selected={tab === t.id} onClick={() => setTab(t.id)} className="inline-flex items-center gap-1.5">
            {t.icon}
            {t.label}
          </Pill>
        ))}
      </div>

      <div className="p-4 space-y-3 text-xs text-ink-body">
        {tab === 'clips' && (
          pack.clips.length > 0 ? (
            <div className="space-y-2">
              {pack.clips.map((clip) => (
                <OutputBlock
                  key={clip.rank}
                  title={`#${clip.rank} — ${clip.start_time || '?'}–${clip.end_time || '?'}`}
                  copyText={`${clip.title}\n\n${clip.transcript || ''}`}
                >
                  <p className="font-medium text-ink mb-1">{clip.title}</p>
                  <p className="text-ink-mute italic">"{clip.hook}"</p>
                </OutputBlock>
              ))}
            </div>
          ) : <p className="text-ink-mute">No clip candidates were generated.</p>
        )}

        {tab === 'repurposed' && (
          pack.repurposed ? (
            <div className="space-y-3">
              <OutputBlock
                title="LinkedIn Post"
                copyText={`${pack.repurposed.linkedin?.hook || ''}\n\n${pack.repurposed.linkedin?.body || ''}\n\n${pack.repurposed.linkedin?.cta || ''}`}
              >
                <p className="font-medium text-ink mb-1">{pack.repurposed.linkedin?.hook}</p>
                <p>{pack.repurposed.linkedin?.body}</p>
                <p className="text-ink-mute mt-1">{pack.repurposed.linkedin?.cta}</p>
              </OutputBlock>
              <OutputBlock
                title="X / Twitter Thread"
                copyText={(pack.repurposed.thread || []).map((t: any) => `${t.n}. ${t.text}`).join('\n\n')}
              >
                <div className="space-y-1.5">
                  {(pack.repurposed.thread || []).map((t: any) => (
                    <p key={t.n}><span className="text-ink-mute">{t.n}.</span> {t.text}</p>
                  ))}
                </div>
              </OutputBlock>
              <OutputBlock
                title="Short-form Notes"
                copyText={(pack.repurposed.notes || []).join('\n\n')}
              >
                <div className="space-y-1.5">
                  {(pack.repurposed.notes || []).map((n: string, i: number) => <p key={i}>{n}</p>)}
                </div>
              </OutputBlock>
            </div>
          ) : <p className="text-ink-mute">Repurposed posts were not generated for this pack.</p>
        )}

        {tab === 'titles' && (
          pack.titles ? (
            <div className="space-y-2">
              {(pack.titles.titles || []).map((t: any, i: number) => (
                <OutputBlock key={i} title={t.formula || 'title'} copyText={t.text} badge={t.over_limit ? <Tag tone="warning">over 60 chars</Tag> : undefined}>
                  <p className="font-medium text-ink">{t.text}</p>
                  {t.why && <p className="text-ink-mute mt-1">{t.why}</p>}
                </OutputBlock>
              ))}
            </div>
          ) : <p className="text-ink-mute">Titles were not generated for this pack.</p>
        )}

        {tab === 'show_notes' && (
          pack.show_notes ? (
            <div className="space-y-3">
              <OutputBlock title="Summary" copyText={pack.show_notes.summary}>
                <p>{pack.show_notes.summary}</p>
              </OutputBlock>
              {(pack.show_notes.chapters || []).length > 0 && (
                <OutputBlock
                  title="Chapters"
                  copyText={(pack.show_notes.chapters || []).map((c: any) => `${c.time || '--:--'}  ${c.title}`).join('\n')}
                >
                  <div className="space-y-1">
                    {(pack.show_notes.chapters || []).map((c: any, i: number) => (
                      <p key={i}><span className="font-mono text-ink-body">{c.time || '--:--'}</span>{'  '}{c.title}{c.estimated && <Tag tone="warning" className="ml-1.5">estimated</Tag>}</p>
                    ))}
                  </div>
                </OutputBlock>
              )}
              <OutputBlock title="Key Takeaways" copyText={(pack.show_notes.show_notes || []).join('\n')}>
                <ul className="list-disc pl-4 space-y-1">
                  {(pack.show_notes.show_notes || []).map((n: string, i: number) => <li key={i}>{n}</li>)}
                </ul>
              </OutputBlock>
            </div>
          ) : <p className="text-ink-mute">Show notes were not generated for this pack.</p>
        )}

        {tab === 'captions' && (
          pack.captions && Object.entries(pack.captions).some(([, v]) => isCaptionResult(v)) ? (
            <div className="space-y-2">
              {Object.entries(pack.captions).filter(([, v]) => isCaptionResult(v)).map(([platform, result]) => {
                const r = result as CaptionResult;
                return (
                  <OutputBlock
                    key={platform}
                    title={platform}
                    copyText={`${r.caption}\n\n${(r.hashtags || []).join(' ')}`}
                    badge={r.over_limit ? <Tag tone="warning">over limit</Tag> : undefined}
                  >
                    <p>{r.caption}</p>
                    {r.hashtags?.length > 0 && <p className="text-ink-body mt-1">{r.hashtags.join(' ')}</p>}
                  </OutputBlock>
                );
              })}
            </div>
          ) : <p className="text-ink-mute">Captions were not generated for this pack.</p>
        )}
      </div>
    </div>
  );
};
