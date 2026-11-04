'use client';

import React, { useState } from 'react';
import { Download, Flame, Clock, FileText, ChevronDown, ChevronUp, Share2, Sparkles, Check, Zap, Layers, Users, ZoomIn, Send } from 'lucide-react';
import { Clip, resolveMediaUrl } from '@/lib/api';
import PublishModal from '@/components/PublishModal';

interface ClipCardProps {
  clip: Clip;
  index?: number;
  onPostPublished?: () => void;
}

export default function ClipCard({ clip, onPostPublished }: ClipCardProps) {
  const [showReasoning, setShowReasoning] = useState(false);
  const [copied, setCopied] = useState(false);
  const [isPublishOpen, setIsPublishOpen] = useState(false);

  const videoUrl = resolveMediaUrl(clip.video_url);
  const previewUrl = resolveMediaUrl(clip.preview_url);
  const subtitlesUrl = clip.subtitles_url ? resolveMediaUrl(clip.subtitles_url) : null;

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(videoUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const getScoreBadge = (score: number) => {
    if (score >= 95) {
      return {
        bg: 'bg-gradient-to-r from-amber-400 via-rose-500 to-purple-600 text-white shadow-rose-500/30',
        text: 'Ultra Viral',
      };
    }
    if (score >= 90) {
      return {
        bg: 'bg-gradient-to-r from-emerald-400 to-teal-500 text-white shadow-emerald-500/30',
        text: 'High Viral',
      };
    }
    return {
      bg: 'bg-gradient-to-r from-blue-400 to-indigo-500 text-white shadow-blue-500/30',
      text: 'Good Reach',
    };
  };

  const scoreBadge = getScoreBadge(clip.virality_score);

  return (
    <div className="group flex flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/90 shadow-xl transition-all duration-300 hover:border-zinc-700/80 hover:shadow-2xl hover:shadow-rose-500/5">
      {/* 9:16 Video Player Preview Container */}
      <div className="relative aspect-9/16 w-full overflow-hidden bg-black">
        <video
          controls
          playsInline
          preload="metadata"
          poster={previewUrl}
          src={videoUrl}
          className="h-full w-full object-cover"
        />

        {/* Top Floating Glass Badges */}
        <div className="pointer-events-none absolute left-3 top-3 right-3 flex items-center justify-between z-10">
          {/* Virality Score Pill */}
          <div className={`flex items-center gap-1.5 rounded-full ${scoreBadge.bg} px-2.5 py-1 text-xs font-bold shadow-lg backdrop-blur-md`}>
            <Flame className="h-3.5 w-3.5 fill-current" />
            <span>{clip.virality_score}/100</span>
          </div>

          {/* Duration Pill */}
          <div className="flex items-center gap-1 rounded-full bg-black/75 backdrop-blur-md border border-white/10 px-2.5 py-1 text-xs font-medium text-white shadow">
            <Clock className="h-3 w-3 text-zinc-400" />
            <span>{clip.duration.toFixed(1)}s</span>
          </div>
        </div>
      </div>

      {/* Clip Content Details */}
      <div className="flex flex-1 flex-col p-4 sm:p-5 space-y-3.5">
        {/* Smart Edit Badges */}
        {clip.edit_stats && (
          <div className="flex flex-wrap items-center gap-1.5">
            {/* Jump Cuts Pill */}
            {clip.edit_stats.jump_cuts_count > 0 && (
              <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 text-[10px] font-semibold text-amber-400">
                <Zap className="h-3 w-3 fill-current text-amber-400" />
                <span>{clip.edit_stats.jump_cuts_count} Cuts (-{clip.edit_stats.dead_air_removed_sec}s)</span>
              </span>
            )}

            {/* Narrative Stitch Pill */}
            {clip.edit_stats.segments_count > 1 && (
              <span className="inline-flex items-center gap-1 rounded-md bg-purple-500/10 border border-purple-500/20 px-2 py-0.5 text-[10px] font-semibold text-purple-400">
                <Layers className="h-3 w-3 text-purple-400" />
                <span>{clip.edit_stats.segments_count}-Part Stitch</span>
              </span>
            )}

            {/* Layout Mode Pill */}
            {clip.edit_stats.layout_mode === 'split_screen' ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-cyan-500/10 border border-cyan-500/20 px-2 py-0.5 text-[10px] font-semibold text-cyan-400">
                <Users className="h-3 w-3 text-cyan-400" />
                <span>2-Speaker Split</span>
              </span>
            ) : clip.edit_stats.dynamic_zooms_count && clip.edit_stats.dynamic_zooms_count > 0 ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-rose-500/10 border border-rose-500/20 px-2 py-0.5 text-[10px] font-semibold text-rose-400">
                <ZoomIn className="h-3 w-3 text-rose-400" />
                <span>Dynamic Zooms</span>
              </span>
            ) : null}
          </div>
        )}

        {/* Clip Title & Index */}
        <div>
          <div className="flex items-center justify-between text-[10px] font-semibold tracking-wider text-rose-400 uppercase">
            <span>Clip #{clip.clip_index + 1}</span>
            <span className="text-zinc-500 font-mono">{clip.file_size_mb ? `${clip.file_size_mb} MB` : '1080x1920'}</span>
          </div>
          <h4 className="mt-1 text-sm font-bold text-white line-clamp-2 leading-snug">
            {clip.title}
          </h4>
        </div>

        {/* Opening Hook Snippet */}
        <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/70 p-3">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-400 mb-1">
            <Sparkles className="h-3 w-3" />
            <span>Opening Hook</span>
          </div>
          <p className="text-xs italic text-zinc-300 line-clamp-3 leading-relaxed">
            &ldquo;{clip.hook_text}&rdquo;
          </p>
        </div>

        {/* Virality Analysis Accordion */}
        {clip.reasoning && (
          <div>
            <button
              type="button"
              onClick={() => setShowReasoning(!showReasoning)}
              className="flex w-full items-center justify-between rounded-lg border border-zinc-800/70 bg-zinc-950/40 px-3 py-2 text-xs font-semibold text-zinc-300 hover:bg-zinc-800/60 hover:text-white transition-colors"
            >
              <span>Why this will go viral</span>
              {showReasoning ? <ChevronUp className="h-3.5 w-3.5 text-zinc-400" /> : <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />}
            </button>
            {showReasoning && (
              <p className="mt-2 rounded-lg bg-zinc-950/50 p-2.5 text-xs leading-relaxed text-zinc-400 border border-zinc-800/50 animate-in fade-in duration-200">
                {clip.reasoning}
              </p>
            )}
          </div>
        )}

        {/* Action Buttons Footer */}
        <div className="mt-auto pt-3 border-t border-zinc-800/80 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            {/* Primary Action: Publish / Schedule */}
            <button
              type="button"
              onClick={() => setIsPublishOpen(true)}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-gradient-to-r from-rose-500 via-rose-600 to-amber-500 px-3.5 py-2 text-xs font-semibold text-white shadow-md shadow-rose-500/20 hover:shadow-rose-500/35 hover:scale-[1.01] active:scale-[0.99] transition-all"
            >
              <Send className="h-3.5 w-3.5" />
              <span>Publish / Schedule</span>
            </button>

            {/* Download Video Button */}
            <a
              href={videoUrl}
              download={`viral_clip_${clip.clip_index + 1}.mp4`}
              target="_blank"
              rel="noopener noreferrer"
              title="Download 9:16 Video"
              className="flex items-center justify-center gap-1 rounded-xl border border-zinc-800 bg-zinc-800/80 px-3 py-2 text-xs font-semibold text-zinc-200 hover:bg-zinc-700 hover:text-white transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              <span>MP4</span>
            </a>

            {/* Subtitles Link if available */}
            {subtitlesUrl && (
              <a
                href={subtitlesUrl}
                download={`clip_${clip.clip_index + 1}.ass`}
                target="_blank"
                rel="noopener noreferrer"
                title="Download .ass Subtitles"
                className="flex items-center justify-center rounded-xl border border-zinc-800 bg-zinc-800/80 p-2 text-zinc-300 hover:bg-zinc-700 hover:text-white transition-colors"
              >
                <FileText className="h-3.5 w-3.5" />
              </a>
            )}

            {/* Copy Video Link Button */}
            <button
              type="button"
              onClick={handleCopyLink}
              title="Copy Video URL"
              className="flex items-center justify-center rounded-xl border border-zinc-800 bg-zinc-800/80 p-2 text-zinc-300 hover:bg-zinc-700 hover:text-white transition-colors"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Share2 className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>
      </div>

      {/* Publish / Schedule Modal */}
      <PublishModal
        clip={clip}
        isOpen={isPublishOpen}
        onClose={() => setIsPublishOpen(false)}
        onPublished={() => {
          if (onPostPublished) onPostPublished();
        }}
      />
    </div>
  );
}
