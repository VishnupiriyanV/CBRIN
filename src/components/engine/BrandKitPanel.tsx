import React, { useEffect, useState } from 'react';
import { Palette, RefreshCw, Loader2 } from 'lucide-react';
import { BrandKit } from '../../types';
import { engineGetBrandKit, engineUpdateBrandKit, engineAutoseedBrandKit } from '../../services/api';

const CAPTION_FONTS = ['Inter', 'Anton', 'Archivo Black'];
const CAPTION_POSITIONS = ['bottom-center', 'top-center', 'center'];
const CAPTION_SIZES = ['small', 'medium', 'large'];

export const BrandKitPanel: React.FC = () => {
  const [kit, setKit] = useState<BrandKit | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const data = await engineGetBrandKit();
      setKit(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load brand kit');
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleAutoseed = async (force: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const updated = await engineAutoseedBrandKit(force);
      setKit(updated);
    } catch (err: any) {
      // Re-seeding an edited kit without force=true intentionally 409s (ENGINE-PLAN.md:
      // "auto_seeded flips to false on edit so re-seeding never silently overwrites the
      // creator's choices") — surface that as a confirm prompt rather than a dead end.
      if (err.message?.includes('manually edited')) {
        if (window.confirm('This brand kit has been manually edited. Re-seed from your video frames anyway? This will overwrite your color choices.')) {
          await handleAutoseed(true);
          return;
        }
      } else {
        setError(err.message || 'Autoseed failed');
      }
    } finally {
      setLoading(false);
    }
  };

  const applyPatch = async (patch: Partial<BrandKit>) => {
    if (!kit) return;
    const optimistic = { ...kit, ...patch } as BrandKit;
    setKit(optimistic);
    try {
      const updated = await engineUpdateBrandKit(patch);
      setKit(updated);
    } catch (err: any) {
      setError(err.message || 'Update failed');
      load();
    }
  };

  if (!kit) {
    return (
      <div className="text-xs font-mono text-ink-mute p-4">
        {error ? error : 'Loading brand kit...'}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Palette className="w-4 h-4 text-accent-sunset" />
          <span className="text-xs font-semibold text-ink">Brand Kit</span>
          {kit.auto_seeded && (
            <span className="px-2 py-0.5 rounded-full border border-hairline bg-canvas-soft text-[9px] font-mono text-ink-mute">
              AUTO-SEEDED
            </span>
          )}
        </div>
        <button
          onClick={() => handleAutoseed(false)}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-hairline hover:border-hairline-bright text-[10px] font-mono text-ink-mute hover:text-ink transition-all disabled:opacity-40"
        >
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          <span>Re-seed from frames</span>
        </button>
      </div>

      {error && <p className="text-[10px] font-mono text-red-400">{error}</p>}

      {/* Palette swatches */}
      <div className="grid grid-cols-4 gap-2">
        {(Object.keys(kit.colors) as (keyof BrandKit['colors'])[]).map((key) => (
          <label key={key} className="flex flex-col items-center gap-1 cursor-pointer">
            <input
              type="color"
              value={kit.colors[key]}
              onChange={(e) => applyPatch({ colors: { ...kit.colors, [key]: e.target.value } })}
              className="w-9 h-9 rounded-lg border border-hairline bg-transparent cursor-pointer"
            />
            <span className="text-[9px] font-mono text-ink-mute capitalize">{key}</span>
          </label>
        ))}
      </div>

      {/* Font picker */}
      <div className="space-y-1.5">
        <span className="text-[10px] font-mono text-ink-mute">Caption font</span>
        <div className="flex gap-1.5">
          {CAPTION_FONTS.map((font) => (
            <button
              key={font}
              onClick={() => applyPatch({ fonts: { ...kit.fonts, caption: font } })}
              className={`px-2.5 py-1 rounded-full border text-[10px] font-mono transition-all ${
                kit.fonts.caption === font
                  ? 'border-accent-sunset bg-accent-sunset/10 text-accent-sunset'
                  : 'border-hairline text-ink-mute hover:border-hairline-bright hover:text-ink'
              }`}
            >
              {font}
            </button>
          ))}
        </div>
      </div>

      {/* Caption position + size + case */}
      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1.5">
          <span className="text-[10px] font-mono text-ink-mute">Position</span>
          <select
            value={kit.caption.position}
            onChange={(e) => applyPatch({ caption: { ...kit.caption, position: e.target.value } })}
            className="w-full bg-canvas-soft border border-hairline rounded-lg px-2 py-1.5 text-[11px] text-ink outline-none"
          >
            {CAPTION_POSITIONS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <span className="text-[10px] font-mono text-ink-mute">Size</span>
          <select
            value={kit.caption.size || 'medium'}
            onChange={(e) => applyPatch({ caption: { ...kit.caption, size: e.target.value } })}
            className="w-full bg-canvas-soft border border-hairline rounded-lg px-2 py-1.5 text-[11px] text-ink outline-none"
          >
            {CAPTION_SIZES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <span className="text-[10px] font-mono text-ink-mute">Case</span>
          <select
            value={kit.caption.case}
            onChange={(e) => applyPatch({ caption: { ...kit.caption, case: e.target.value } })}
            className="w-full bg-canvas-soft border border-hairline rounded-lg px-2 py-1.5 text-[11px] text-ink outline-none"
          >
            <option value="upper">upper</option>
            <option value="sentence">sentence</option>
          </select>
        </div>
      </div>

      <p className="text-[9px] font-mono text-ink-mute leading-relaxed">
        Reframing is a static center crop in this version — an off-center speaker may be
        poorly framed. Face-tracking crop is planned but not yet implemented.
      </p>
    </div>
  );
};
