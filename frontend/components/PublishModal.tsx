'use client';

import React, { useState, useEffect } from 'react';
import {
  X,
  Sparkles,
  Calendar,
  Send,
  Loader2,
  CheckCircle2,
  ExternalLink,
  Tag,
  AlertCircle,
  Globe,
  Lock,
  EyeOff,
} from 'lucide-react';
import {
  Clip,
  SocialAccount,
  ScheduledPost,
  generateClipMetadata,
  publishClip,
  getSocialAccounts,
  getOAuthUrl,
} from '@/lib/api';

interface PublishModalProps {
  clip: Clip;
  isOpen: boolean;
  onClose: () => void;
  onPublished?: (post: ScheduledPost) => void;
}

type PlatformType = 'youtube_shorts' | 'instagram_reels' | 'tiktok';

export default function PublishModal({
  clip,
  isOpen,
  onClose,
  onPublished,
}: PublishModalProps) {
  const [platform, setPlatform] = useState<PlatformType>('youtube_shorts');
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(false);

  // Form states
  const [title, setTitle] = useState('');
  const [caption, setCaption] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [privacyStatus, setPrivacyStatus] = useState<'public' | 'unlisted' | 'private'>('public');

  // Scheduling states
  const [isScheduled, setIsScheduled] = useState(false);
  const [scheduleTime, setScheduleTime] = useState('');

  // AI prompt state
  const [customPrompt, setCustomPrompt] = useState('');
  const [isGeneratingAI, setIsGeneratingAI] = useState(false);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [publishedPost, setPublishedPost] = useState<ScheduledPost | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Fetch accounts on open
  useEffect(() => {
    if (!isOpen) return;

    setLoadingAccounts(true);
    getSocialAccounts()
      .then((data) => setAccounts(data))
      .catch((err) => console.error('Failed to load accounts:', err))
      .finally(() => setLoadingAccounts(false));
  }, [isOpen]);

  // Sync copy whenever platform or clip metadata changes
  useEffect(() => {
    if (!clip) return;
    const meta = clip.social_metadata;

    if (platform === 'youtube_shorts') {
      setTitle(meta?.youtube_title || `${clip.title.slice(0, 85)} #Shorts`);
      setCaption(meta?.youtube_description || clip.hook_text);
      setTags(meta?.youtube_tags || ['Shorts', 'Viral', 'Tech']);
    } else if (platform === 'instagram_reels') {
      setTitle(clip.title);
      setCaption(meta?.instagram_caption || `${clip.hook_text}\n\n#reels #viral #shorts`);
      setTags(['reels', 'trending', 'content']);
    } else if (platform === 'tiktok') {
      setTitle(clip.title);
      setCaption(meta?.tiktok_caption || `${clip.hook_text} #fyp #viral #trending`);
      setTags(['fyp', 'viral', 'trending']);
    }
    setPublishedPost(null);
    setErrorMessage(null);
  }, [platform, clip]);

  if (!isOpen) return null;

  const currentAccount = accounts.find((a) => {
    if (platform === 'youtube_shorts') return a.platform === 'youtube';
    if (platform === 'instagram_reels') return a.platform === 'instagram';
    return a.platform === 'tiktok';
  });

  const handleAddTag = () => {
    const trimmed = tagInput.trim().replace(/^#/, '');
    if (trimmed && !tags.includes(trimmed)) {
      setTags([...tags, trimmed]);
      setTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter((t) => t !== tagToRemove));
  };

  const handleRegenerateWithAI = async () => {
    setIsGeneratingAI(true);
    setErrorMessage(null);
    try {
      const res = await generateClipMetadata(clip.id, customPrompt || undefined);
      const meta = res.social_metadata;

      if (platform === 'youtube_shorts') {
        setTitle(meta.youtube_title);
        setCaption(meta.youtube_description);
        setTags(meta.youtube_tags);
      } else if (platform === 'instagram_reels') {
        setCaption(meta.instagram_caption);
      } else {
        setCaption(meta.tiktok_caption);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'AI generation failed';
      setErrorMessage(msg);
    } finally {
      setIsGeneratingAI(false);
    }
  };

  const handleConnectRealYouTube = async () => {
    try {
      const res = await getOAuthUrl('http://localhost:8000/api/social/oauth/youtube/callback');
      const targetUrl = res.auth_url || res.url;
      if (targetUrl) {
        window.location.href = targetUrl;
      } else {
        alert('Could not retrieve Google OAuth authorization link.');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to connect YouTube';
      setErrorMessage(msg);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      let targetSchedule: string | null = null;
      if (isScheduled && scheduleTime) {
        targetSchedule = new Date(scheduleTime).toISOString();
      }

      const result = await publishClip({
        clip_id: clip.id,
        platform,
        title: title.trim(),
        caption: caption.trim(),
        tags,
        privacy_status: privacyStatus,
        scheduled_for: targetSchedule,
      });

      setPublishedPost(result);
      if (onPublished) {
        onPublished(result);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Publishing failed';
      setErrorMessage(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-zinc-800 bg-zinc-950 p-6 sm:p-7 text-zinc-100 shadow-2xl space-y-6">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-zinc-800/80 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-rose-500 to-amber-500 text-white shadow-md shadow-rose-500/20">
              <Send className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Publish or Schedule Short</h3>
              <p className="text-xs text-zinc-400">
                Clip #{clip.clip_index + 1}: &ldquo;{clip.title}&rdquo;
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-white transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Success Banner if Published */}
        {publishedPost ? (
          <div className="my-6 space-y-4 rounded-xl border border-emerald-500/30 bg-emerald-950/20 p-6 text-center">
            <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-400" />
            <h4 className="text-base font-bold text-white">
              {publishedPost.status === 'published' ? '🎉 Short Published Successfully!' : '📅 Short Scheduled!'}
            </h4>
            <p className="text-xs text-zinc-300 max-w-md mx-auto">
              {publishedPost.status === 'published'
                ? 'Your vertical 9:16 short is live and processing on your creator channel.'
                : `Your upload is queued for ${new Date(publishedPost.scheduled_for!).toLocaleString()}.`}
            </p>

            {publishedPost.platform_url && (
              <div className="pt-2">
                <a
                  href={publishedPost.platform_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-4 py-2 text-xs font-semibold text-white shadow-lg hover:scale-[1.02] transition-transform"
                >
                  <span>View Post on Platform</span>
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            )}

            <button
              type="button"
              onClick={onClose}
              className="mt-4 block mx-auto text-xs text-zinc-400 hover:text-white underline"
            >
              Close Window
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Error Message */}
            {errorMessage && (
              <div className="flex items-center gap-2.5 rounded-xl border border-rose-500/30 bg-rose-950/30 px-4 py-3 text-xs text-rose-300 animate-in fade-in duration-200">
                <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
                <span>{errorMessage}</span>
              </div>
            )}

            {/* Platform Selection Tabs */}
            <div className="space-y-2.5">
              <label className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">
                1. Target Social Platform
              </label>
              <div className="grid grid-cols-3 gap-2.5">
                {/* YouTube Shorts */}
                <button
                  type="button"
                  onClick={() => setPlatform('youtube_shorts')}
                  className={`flex flex-col items-center justify-center gap-2 rounded-xl border p-3.5 text-xs font-semibold transition-all ${
                    platform === 'youtube_shorts'
                      ? 'border-rose-500 bg-rose-500/10 text-rose-400 shadow-md shadow-rose-500/15'
                      : 'border-zinc-800 bg-zinc-900/60 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200'
                  }`}
                >
                  <svg width="24" height="24" className="h-5 w-5 fill-current" viewBox="0 0 24 24">
                    <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
                  </svg>
                  <span>YouTube Shorts</span>
                </button>

                {/* Instagram Reels */}
                <button
                  type="button"
                  onClick={() => setPlatform('instagram_reels')}
                  className={`flex flex-col items-center justify-center gap-2 rounded-xl border p-3.5 text-xs font-semibold transition-all ${
                    platform === 'instagram_reels'
                      ? 'border-pink-500 bg-pink-500/10 text-pink-400 shadow-md shadow-pink-500/15'
                      : 'border-zinc-800 bg-zinc-900/60 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200'
                  }`}
                >
                  <svg width="24" height="24" className="h-5 w-5 fill-current" viewBox="0 0 24 24">
                    <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
                  </svg>
                  <span>Instagram Reels</span>
                </button>

                {/* TikTok */}
                <button
                  type="button"
                  onClick={() => setPlatform('tiktok')}
                  className={`flex flex-col items-center justify-center gap-2 rounded-xl border p-3.5 text-xs font-semibold transition-all ${
                    platform === 'tiktok'
                      ? 'border-cyan-500 bg-cyan-500/10 text-cyan-400 shadow-md shadow-cyan-500/15'
                      : 'border-zinc-800 bg-zinc-900/60 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200'
                  }`}
                >
                  <svg width="24" height="24" className="h-5 w-5 fill-current" viewBox="0 0 24 24">
                    <path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.24 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z" />
                  </svg>
                  <span>TikTok</span>
                </button>
              </div>

              {/* Connected Account Bar */}
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-3 text-xs text-zinc-400">
                <span className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${currentAccount?.mode === 'live_oauth' ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
                  <span>Account: <strong className="text-white">{currentAccount?.account_name || 'Sandbox Creator'}</strong></span>
                </span>
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold tracking-wide ${
                    currentAccount?.mode === 'live_oauth'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'bg-zinc-800 text-zinc-400 border border-zinc-700/60'
                  }`}>
                    {currentAccount?.mode === 'live_oauth' ? '● LIVE OAUTH' : 'SANDBOX MODE'}
                  </span>
                  {platform === 'youtube_shorts' && currentAccount?.mode !== 'live_oauth' && (
                    <button
                      type="button"
                      onClick={handleConnectRealYouTube}
                      className="flex items-center gap-1 rounded-lg bg-rose-500/10 border border-rose-500/30 px-2.5 py-1 text-[11px] font-semibold text-rose-300 hover:bg-rose-500/20 transition-colors"
                    >
                      <span>🔗 Connect Real YouTube</span>
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* AI Retention Copywriter Assistant */}
            <div className="rounded-xl border border-amber-500/20 bg-amber-950/15 p-3.5 space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-400">
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>AI Retention Copywriter</span>
                </span>
                <button
                  type="button"
                  onClick={handleRegenerateWithAI}
                  disabled={isGeneratingAI}
                  className="flex items-center gap-1 rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-200 hover:bg-zinc-700 hover:text-white transition-colors disabled:opacity-50"
                >
                  {isGeneratingAI ? (
                    <>
                      <Loader2 className="h-3 w-3 animate-spin text-amber-400" />
                      <span>Generating Copy...</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-3 w-3 text-amber-400" />
                      <span>✨ Regenerate with AI</span>
                    </>
                  )}
                </button>
              </div>
              <input
                type="text"
                value={customPrompt}
                onChange={(e) => setCustomPrompt(e.target.value)}
                placeholder="Custom prompt (e.g. 'Add suspense hook', 'Focus on career advice')"
                className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-amber-500/60"
              />
            </div>

            {/* Title / Hook Header */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-zinc-300">
                  {platform === 'youtube_shorts' ? 'Shorts Title (Under 95 chars)' : 'Post Title'}
                </label>
                <span className="text-[10px] text-zinc-500 font-mono">{title.length}/100</span>
              </div>
              <input
                type="text"
                required
                maxLength={100}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full rounded-xl border border-zinc-800 bg-zinc-900/90 px-3.5 py-2.5 text-xs font-medium text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-rose-500/40"
              />
            </div>

            {/* Description / Caption */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-zinc-300">
                {platform === 'youtube_shorts' ? 'YouTube Description' : 'Caption & Hashtags'}
              </label>
              <textarea
                rows={3}
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                placeholder="Write engaging caption with relevant hashtags..."
                className="w-full rounded-xl border border-zinc-800 bg-zinc-900/90 px-3.5 py-2.5 text-xs text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-rose-500/40"
              />
            </div>

            {/* Tags / Keywords */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-zinc-300">Tags / Keywords</label>
              <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/90 p-2.5 min-h-11">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 rounded-md bg-zinc-800 border border-zinc-700 px-2 py-0.5 text-xs text-zinc-200"
                  >
                    <span>#{tag}</span>
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(tag)}
                      className="text-zinc-400 hover:text-white"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                <input
                  type="text"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleAddTag();
                    }
                  }}
                  placeholder="+ add tag (Enter)"
                  className="bg-transparent px-2 py-0.5 text-xs text-zinc-200 placeholder:text-zinc-500 focus:outline-none"
                />
              </div>
            </div>

            {/* Privacy & Upload Timing Settings */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 pt-2 border-t border-zinc-800/80">
              {/* Privacy Setting */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-300">Privacy Status</label>
                <div className="flex items-center gap-1 rounded-xl border border-zinc-800 bg-zinc-900 p-1">
                  <button
                    type="button"
                    onClick={() => setPrivacyStatus('public')}
                    className={`flex-1 flex items-center justify-center gap-1 rounded-lg py-1.5 text-xs font-semibold transition-colors ${
                      privacyStatus === 'public' ? 'bg-zinc-800 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <Globe className="h-3 w-3" />
                    <span>Public</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setPrivacyStatus('unlisted')}
                    className={`flex-1 flex items-center justify-center gap-1 rounded-lg py-1.5 text-xs font-semibold transition-colors ${
                      privacyStatus === 'unlisted' ? 'bg-zinc-800 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <EyeOff className="h-3 w-3" />
                    <span>Unlisted</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setPrivacyStatus('private')}
                    className={`flex-1 flex items-center justify-center gap-1 rounded-lg py-1.5 text-xs font-semibold transition-colors ${
                      privacyStatus === 'private' ? 'bg-zinc-800 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <Lock className="h-3 w-3" />
                    <span>Private</span>
                  </button>
                </div>
              </div>

              {/* Timing Toggle */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-300">Upload Timing</label>
                <div className="flex items-center gap-1 rounded-xl border border-zinc-800 bg-zinc-900 p-1">
                  <button
                    type="button"
                    onClick={() => setIsScheduled(false)}
                    className={`flex-1 flex items-center justify-center gap-1 rounded-lg py-1.5 text-xs font-semibold transition-colors ${
                      !isScheduled ? 'bg-zinc-800 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <Send className="h-3 w-3" />
                    <span>Publish Now</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsScheduled(true)}
                    className={`flex-1 flex items-center justify-center gap-1 rounded-lg py-1.5 text-xs font-semibold transition-colors ${
                      isScheduled ? 'bg-zinc-800 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <Calendar className="h-3 w-3" />
                    <span>Schedule</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Datetime picker if scheduled */}
            {isScheduled && (
              <div className="space-y-1.5 rounded-xl border border-amber-500/30 bg-amber-950/20 p-3 animate-in fade-in duration-200">
                <label className="text-xs font-semibold text-amber-400 flex items-center gap-1.5">
                  <Calendar className="h-3.5 w-3.5" />
                  <span>Select Upload Date & Time (UTC/Local)</span>
                </label>
                <input
                  type="datetime-local"
                  required={isScheduled}
                  value={scheduleTime}
                  min={new Date().toISOString().slice(0, 16)}
                  onChange={(e) => setScheduleTime(e.target.value)}
                  className="w-full rounded-lg border border-amber-500/40 bg-zinc-950 px-3 py-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-amber-500"
                />
              </div>
            )}

            {/* Submit Action Buttons */}
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-zinc-800/80">
              <button
                type="button"
                onClick={onClose}
                disabled={isSubmitting}
                className="rounded-xl border border-zinc-800 px-4 py-2.5 text-xs font-semibold text-zinc-300 hover:bg-zinc-900 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting || !title.trim()}
                className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 via-rose-600 to-amber-500 px-6 py-2.5 text-xs font-semibold text-white shadow-lg shadow-rose-500/20 hover:shadow-rose-500/35 hover:scale-[1.01] active:scale-[0.99] transition-all disabled:opacity-50"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Uploading Short...</span>
                  </>
                ) : isScheduled ? (
                  <>
                    <Calendar className="h-3.5 w-3.5" />
                    <span>Enqueue Scheduled Upload</span>
                  </>
                ) : (
                  <>
                    <Send className="h-3.5 w-3.5" />
                    <span>Publish to {platform === 'youtube_shorts' ? 'YouTube' : platform === 'instagram_reels' ? 'Instagram' : 'TikTok'}</span>
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
