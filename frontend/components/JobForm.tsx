'use client';

import React, { useState } from 'react';
import { Sparkles, Loader2, ArrowRight, AlertCircle } from 'lucide-react';
import { createJob, Job } from '@/lib/api';

function YoutubeIcon({ className }: { className?: string }) {
  return (
    <svg width="24" height="24" className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
    </svg>
  );
}

interface JobFormProps {
  onJobCreated: (job: Job) => void;
  isProcessing?: boolean;
}

const DEMO_URL = 'https://www.youtube.com/watch?v=UF8uR6Z6KLc';

export default function JobForm({ onJobCreated, isProcessing }: JobFormProps) {
  const [url, setUrl] = useState('');
  const [numClips, setNumClips] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) {
      setError('Please enter a valid YouTube video URL');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const newJob = await createJob(url, numClips);
      onJobCreated(newJob);
      setUrl('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to submit clipping job. Please check backend connection.';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const handleUseDemo = () => {
    setUrl(DEMO_URL);
    setNumClips(3);
    setError(null);
  };

  return (
    <div className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/80 p-6 sm:p-7 shadow-xl backdrop-blur-md">
      {/* Decorative ambient background glows */}
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-rose-500/10 blur-3xl" />
      <div className="pointer-events-none absolute -left-16 -bottom-16 h-48 w-48 rounded-full bg-amber-500/10 blur-3xl" />

      <div className="relative z-10 max-w-3xl mx-auto space-y-6">
        {/* Header Block */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-rose-500/20 bg-rose-500/10 px-3 py-1 text-xs font-medium text-rose-300">
            <Sparkles className="h-3.5 w-3.5 text-rose-400" />
            <span>AI Viral Engine • Smart 9:16 Reframing & Subtitles</span>
          </div>
          <h2 className="text-xl sm:text-3xl font-extrabold tracking-tight text-white">
            Create High-Retention{' '}
            <span className="bg-gradient-to-r from-rose-400 via-amber-300 to-violet-400 bg-clip-text text-transparent">
              Shorts from Any Video
            </span>
          </h2>
          <p className="text-xs sm:text-sm text-zinc-400 max-w-lg mx-auto">
            Zero full video downloads. AI finds retention hooks, face-tracks speakers into 9:16 vertical, and generates dynamic karaoke subtitles.
          </p>
        </div>

        {/* Input Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* URL Input Bar */}
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-zinc-400">
              <YoutubeIcon className="h-5 w-5 text-rose-500" />
            </div>
            <input
              type="text"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (error) setError(null);
              }}
              placeholder="Paste YouTube link (e.g. https://www.youtube.com/watch?v=UF8uR6Z6KLc)..."
              disabled={loading || isProcessing}
              className="w-full rounded-xl border border-zinc-700/80 bg-zinc-950/90 py-3.5 pl-12 pr-28 text-sm text-zinc-100 placeholder:text-zinc-500 shadow-inner focus:outline-none focus:ring-2 focus:ring-rose-500/40 disabled:opacity-60 transition-all"
            />
            <button
              type="button"
              onClick={handleUseDemo}
              disabled={loading || isProcessing}
              className="absolute right-2.5 top-2.5 rounded-lg border border-zinc-700 bg-zinc-800/90 px-3 py-1.5 text-xs font-semibold text-zinc-300 hover:bg-zinc-700 hover:text-white transition-colors"
            >
              Demo URL
            </button>
          </div>

          {/* Options & Action Row */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-1">
            {/* Target Clips Selector */}
            <div className="flex items-center gap-2.5 w-full sm:w-auto">
              <span className="text-xs font-semibold text-zinc-400">Output Clips:</span>
              <div className="flex items-center gap-1 rounded-xl border border-zinc-800 bg-zinc-950/80 p-1">
                {[1, 2, 3, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setNumClips(n)}
                    disabled={loading || isProcessing}
                    className={`h-7 px-3 rounded-lg text-xs font-semibold transition-all ${
                      numClips === n
                        ? 'bg-gradient-to-r from-rose-500 to-amber-500 text-white shadow-sm shadow-rose-500/20'
                        : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
                    }`}
                  >
                    {n} {n === 1 ? 'clip' : 'clips'}
                  </button>
                ))}
              </div>
            </div>

            {/* Submit Action */}
            <button
              type="submit"
              disabled={loading || isProcessing || !url.trim()}
              className="w-full sm:w-auto flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 via-rose-600 to-amber-500 px-6 py-3 text-xs sm:text-sm font-semibold text-white shadow-lg shadow-rose-500/25 hover:shadow-rose-500/40 hover:scale-[1.01] active:scale-[0.99] transition-all disabled:opacity-50 disabled:pointer-events-none"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Submitting Project...</span>
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  <span>Generate Viral Clips</span>
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </div>

          {/* Error Message */}
          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-950/30 p-3 text-xs text-rose-300 animate-in fade-in duration-200">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
              <span>{error}</span>
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
