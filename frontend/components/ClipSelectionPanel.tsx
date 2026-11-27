'use client';

import React, { useEffect, useState } from 'react';
import {
  Sparkles,
  CheckCircle2,
  Circle,
  Loader2,
  RefreshCw,
  Wand2,
  Clock,
  Flame,
} from 'lucide-react';
import {
  Job,
  ClipOption,
  getJobOptions,
  renderSelectedOptions,
  regenerateJobOptions,
} from '@/lib/api';

interface ClipSelectionPanelProps {
  job: Job;
  onJobUpdated: (job: Job) => void;
  onRenderStarted: (job: Job) => void;
}

const VIBES = [
  'funny',
  'motivational',
  'emotional',
  'sad',
  'romantic',
  'educational',
  'controversial',
  'dramatic',
  'wholesome',
  'shocking',
  'informative',
];

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function ClipSelectionPanel({
  job,
  onJobUpdated,
  onRenderStarted,
}: ClipSelectionPanelProps) {
  const options = getJobOptions(job);
  const profile = job.content_profile;
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [vibe, setVibe] = useState(profile?.primary_vibe || '');
  const [rendering, setRendering] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep selection in sync when fresh options arrive.
  useEffect(() => {
    setSelected(new Set(options.map((_, idx) => idx)));
    if (profile?.primary_vibe) {
      setVibe(profile.primary_vibe);
    }
  }, [job.id, job.options_json]);

  if (job.status !== 'awaiting_selection' && job.status !== 'failed') {
    return null;
  }

  if (job.status === 'failed') {
    return null;
  }

  const toggle = (idx: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleRegenerate = async () => {
    try {
      setRegenerating(true);
      setError(null);
      const updated = await regenerateJobOptions(job.id, vibe || undefined);
      onJobUpdated(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to regenerate options');
    } finally {
      setRegenerating(false);
    }
  };

  const handleRender = async () => {
    if (selected.size === 0) {
      setError('Pick at least one clip option to render.');
      return;
    }
    try {
      setRendering(true);
      setError(null);
      const updated = await renderSelectedOptions(job.id, Array.from(selected).sort((a, b) => a - b));
      onRenderStarted(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to start render');
    } finally {
      setRendering(false);
    }
  };

  return (
    <div className="space-y-5 rounded-2xl border border-zinc-800 bg-zinc-900/70 p-5 sm:p-6 shadow-xl backdrop-blur-sm">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-500/30 bg-rose-500/10 px-3 py-1 text-[11px] font-bold uppercase tracking-wide text-rose-300">
              <Sparkles className="h-3 w-3" />
              Detected Vibe
            </span>
            <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-300 capitalize">
              {profile?.primary_vibe || 'unknown'}
            </span>
            {profile?.confidence != null && (
              <span className="text-[11px] text-zinc-400">{profile.confidence}% confidence</span>
            )}
            {profile?.energy && (
              <span className="flex items-center gap-1 text-[11px] text-zinc-400">
                <Flame className="h-3 w-3 text-orange-400" />
                {profile.energy} energy
              </span>
            )}
          </div>
          <p className="max-w-2xl text-xs text-zinc-400">
            {profile?.summary || 'Analysis complete. Pick the options you want rendered.'}
          </p>
          {profile?.secondary_vibes && profile.secondary_vibes.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {profile.secondary_vibes.map((v) => (
                <span key={v} className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-[10px] text-zinc-400 capitalize">
                  {v}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <select
            value={vibe}
            onChange={(e) => setVibe(e.target.value)}
            disabled={regenerating}
            className="h-9 rounded-xl border border-zinc-700 bg-zinc-950 px-2.5 text-xs text-zinc-200 focus:outline-none focus:ring-2 focus:ring-rose-500/40 disabled:opacity-50"
          >
            {VIBES.map((v) => (
              <option key={v} value={v} className="capitalize">
                {v}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleRegenerate}
            disabled={regenerating || rendering}
            className="flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-zinc-800/80 px-3 py-2 text-xs font-semibold text-zinc-300 hover:bg-zinc-700 hover:text-white transition-colors disabled:opacity-50"
          >
            {regenerating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            <span>Regenerate</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {options.map((option: ClipOption, idx: number) => {
          const isSelected = selected.has(idx);
          return (
            <button
              key={`${job.id}-option-${idx}`}
              type="button"
              onClick={() => toggle(idx)}
              className={`group relative flex flex-col gap-3 rounded-xl border p-4 text-left transition-all ${
                isSelected
                  ? 'border-rose-500/60 bg-rose-950/20 shadow-md shadow-rose-500/10'
                  : 'border-zinc-800 bg-zinc-950/60 hover:border-zinc-700 hover:bg-zinc-900/60'
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="rounded-md bg-zinc-800 px-2 py-0.5 text-[10px] font-mono text-zinc-400">
                  OPTION {idx + 1}
                </span>
                <span className="flex items-center gap-1 text-[11px] font-bold text-amber-400">
                  <Flame className="h-3 w-3" />
                  {option.virality_score}
                </span>
              </div>

              <div>
                <h4 className="text-sm font-bold leading-snug text-white line-clamp-2">{option.title}</h4>
                <p className="mt-1.5 text-[11px] leading-relaxed text-zinc-400 line-clamp-3">
                  {option.hook_text}
                </p>
              </div>

              <div className="mt-auto flex flex-wrap items-center gap-2 text-[10px] text-zinc-500">
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {formatTime(option.start_time)} – {formatTime(option.end_time)}
                </span>
                <span>•</span>
                <span>≤30s · {Math.round(option.duration)}s</span>
                {option.segments && option.segments.length > 1 ? (
                  <>
                    <span>•</span>
                    <span>{option.segments.length} segments</span>
                  </>
                ) : (
                  <>
                    <span>•</span>
                    <span>Continuous</span>
                  </>
                )}
              </div>

              <div className="absolute right-2.5 top-2.5 opacity-0 transition-opacity group-hover:opacity-100">
                {isSelected ? (
                  <CheckCircle2 className="h-5 w-5 text-rose-400" />
                ) : (
                  <Circle className="h-5 w-5 text-zinc-600" />
                )}
              </div>
            </button>
          );
        })}
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-950/30 p-3 text-xs text-rose-300">
          {error}
        </div>
      )}

      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-zinc-800/80 pt-4">
        <p className="text-xs text-zinc-400">
          <span className="font-semibold text-white">{selected.size}</span> of {options.length} options selected • only these will be rendered
        </p>
        <button
          type="button"
          onClick={handleRender}
          disabled={rendering || selected.size === 0}
          className="flex w-full sm:w-auto items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 via-rose-600 to-amber-500 px-6 py-3 text-xs sm:text-sm font-semibold text-white shadow-lg shadow-rose-500/25 hover:shadow-rose-500/40 hover:scale-[1.01] active:scale-[0.99] transition-all disabled:opacity-50 disabled:pointer-events-none"
        >
          {rendering ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Starting Render...</span>
            </>
          ) : (
            <>
              <Wand2 className="h-4 w-4" />
              <span>Render {selected.size} Clip{selected.size === 1 ? '' : 's'}</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
