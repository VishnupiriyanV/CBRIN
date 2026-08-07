import React, { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { VoiceProfile } from '../../types';
import { studioAutoseedVoiceProfile, studioGetVoiceProfile, studioUpdateVoiceProfile } from '../../services/api';
import { Button } from '../ui/Button';
import { Panel, PanelHeading } from '../ui/Panel';

const csv = (arr: string[]) => arr.join(', ');
const fromCsv = (s: string) => s.split(',').map((v) => v.trim()).filter(Boolean);

// The differentiator against raw ChatGPT (creator-tools-integration-spec.md §0.3) — injected
// into every STUDIO tool's system prompt via backend/voice_profile.py's to_prompt_block().
export const VoiceProfilePanel: React.FC = () => {
  const [profile, setProfile] = useState<VoiceProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [autoseeding, setAutoseeding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    studioGetVoiceProfile().then(setProfile).catch((e) => setError(e.message));
  }, []);

  if (!profile) {
    return <Panel><p className="text-xs text-ink-mute">Loading voice profile…</p></Panel>;
  }

  const save = async (patch: Partial<VoiceProfile>) => {
    setSaving(true);
    setError(null);
    try {
      const updated = await studioUpdateVoiceProfile(patch);
      setProfile(updated);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleAutoseed = async (force: boolean) => {
    setAutoseeding(true);
    setError(null);
    try {
      const updated = await studioAutoseedVoiceProfile(force);
      setProfile(updated);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAutoseeding(false);
    }
  };

  return (
    <Panel className="space-y-4 max-w-2xl">
      <div className="flex items-center justify-between">
        <PanelHeading className="mb-0">Voice Profile</PanelHeading>
        <Button
          variant="secondary" loading={autoseeding}
          onClick={() => handleAutoseed(!profile.auto_seeded)}
        >
          <Sparkles className="w-3.5 h-3.5" />
          {profile.auto_seeded ? 'Re-seed from library' : 'Re-seed (overwrites edits)'}
        </Button>
      </div>

      {error && <div className="bg-canvas-card/40 border border-danger/30 rounded-sm p-2.5 text-xs text-danger font-mono">{error}</div>}

      <div className="grid grid-cols-2 gap-3">
        <Field label="Niche" value={profile.niche} onBlurSave={(v) => save({ niche: v })} />
        <Field label="Audience" value={profile.audience} onBlurSave={(v) => save({ audience: v })} />
      </div>
      <Field label="Tone (comma-separated)" value={csv(profile.tone)} onBlurSave={(v) => save({ tone: fromCsv(v) })} />
      <Field label="Banned words (comma-separated)" value={csv(profile.banned_words)} onBlurSave={(v) => save({ banned_words: fromCsv(v) })} />
      <Field label="CTA style" value={profile.cta_style} onBlurSave={(v) => save({ cta_style: v })} />
      <Field label="Default platforms (comma-separated)" value={csv(profile.default_platforms)} onBlurSave={(v) => save({ default_platforms: fromCsv(v) })} />

      <div className="space-y-1.5">
        <label className="text-[11px] font-mono text-ink-mute">Sample writing (one per line, matched for tone)</label>
        <textarea
          rows={4}
          defaultValue={profile.sample_content.join('\n')}
          onBlur={(e) => save({ sample_content: e.target.value.split('\n').map((v) => v.trim()).filter(Boolean) })}
          className="w-full bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink resize-y focus:outline-none focus:border-hairline-bright"
        />
      </div>

      {saving && <p className="text-[11px] font-mono text-ink-mute">Saving…</p>}
    </Panel>
  );
};

const Field: React.FC<{ label: string; value: string; onBlurSave: (v: string) => void }> = ({ label, value, onBlurSave }) => (
  <div className="space-y-1.5">
    <label className="text-[11px] font-mono text-ink-mute">{label}</label>
    <input
      type="text"
      defaultValue={value}
      key={value}
      onBlur={(e) => { if (e.target.value !== value) onBlurSave(e.target.value); }}
      className="w-full bg-canvas-soft border border-hairline rounded-sm p-2.5 text-sm text-ink focus:outline-none focus:border-hairline-bright"
    />
  </div>
);
