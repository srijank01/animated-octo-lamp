'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Loader2, CheckCircle2, AlertTriangle, Clock, Film, Sparkles, Layers } from 'lucide-react';
import { getJobById, Job, JobStatus } from '@/lib/api';

interface JobProgressProps {
  jobId: string;
  onJobCompleted?: (job: Job) => void;
  onJobUpdated?: (job: Job) => void;
}

const STATUS_LABELS: Record<JobStatus, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
  queued: {
    label: 'Queued in Engine',
    color: 'border-zinc-700 bg-zinc-800 text-zinc-300',
    icon: Clock,
  },
  extracting_transcript: {
    label: 'Extracting Transcript',
    color: 'border-sky-500/30 bg-sky-500/10 text-sky-400',
    icon: Film,
  },
  selecting_hooks: {
    label: 'Gemini Viral Analysis',
    color: 'border-purple-500/30 bg-purple-500/10 text-purple-400',
    icon: Sparkles,
  },
  processing_clips: {
    label: 'Generating 9:16 Shorts',
    color: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
    icon: Layers,
  },
  completed: {
    label: 'Clips Ready',
    color: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
    icon: CheckCircle2,
  },
  failed: {
    label: 'Processing Failed',
    color: 'border-rose-500/30 bg-rose-500/10 text-rose-400',
    icon: AlertTriangle,
  },
};

export default function JobProgress({ jobId, onJobCompleted, onJobUpdated }: JobProgressProps) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onJobUpdatedRef = useRef(onJobUpdated);
  const onJobCompletedRef = useRef(onJobCompleted);

  useEffect(() => {
    onJobUpdatedRef.current = onJobUpdated;
    onJobCompletedRef.current = onJobCompleted;
  }, [onJobUpdated, onJobCompleted]);

  useEffect(() => {
    let isMounted = true;
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    async function fetchStatus() {
      try {
        const data = await getJobById(jobId);
        if (!isMounted) return;
        setJob(data);
        if (onJobUpdatedRef.current) onJobUpdatedRef.current(data);

        if (data.status === 'completed') {
          if (onJobCompletedRef.current) onJobCompletedRef.current(data);
          if (pollInterval) clearInterval(pollInterval);
        } else if (data.status === 'failed') {
          setError(data.error_message || 'Job failed during execution.');
          if (pollInterval) clearInterval(pollInterval);
        }
      } catch (err: unknown) {
        if (!isMounted) return;
        console.error('Polling error:', err);
      }
    }

    // Initial immediate fetch
    void fetchStatus();

    // Poll every 2 seconds
    pollInterval = setInterval(() => {
      void fetchStatus();
    }, 2000);

    return () => {
      isMounted = false;
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [jobId]);

  if (!job) {
    return (
      <div className="flex items-center justify-center p-6 rounded-2xl border border-zinc-800 bg-zinc-900/60 backdrop-blur-sm">
        <Loader2 className="h-5 w-5 animate-spin text-rose-500 mr-3" />
        <span className="text-xs font-medium text-zinc-400">Connecting to render engine for Job #{jobId.slice(0, 8)}...</span>
      </div>
    );
  }

  const statusMeta = STATUS_LABELS[job.status] || STATUS_LABELS.queued;
  const StatusIcon = statusMeta.icon;
  const isFinished = job.status === 'completed' || job.status === 'failed';

  return (
    <div className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/90 p-5 sm:p-6 shadow-xl backdrop-blur-md">
      {/* Top Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-[10px] font-mono text-zinc-400 font-semibold">
              PIPELINE JOB #{job.id.slice(0, 8)}
            </span>
            <span className="text-xs text-zinc-400 font-medium">
              Target: {job.num_clips} {job.num_clips === 1 ? 'Short' : 'Shorts'}
            </span>
          </div>
          <h3 className="text-sm sm:text-base font-bold text-white mt-1.5 flex items-center gap-2">
            {!isFinished && <span className="h-2 w-2 rounded-full bg-rose-500 animate-ping" />}
            <span>{job.current_step || 'Processing video stream...'}</span>
          </h3>
        </div>

        {/* Status Badge */}
        <div className={`inline-flex items-center gap-1.5 self-start sm:self-auto rounded-full border px-3 py-1 text-xs font-semibold ${statusMeta.color}`}>
          {!isFinished ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <StatusIcon className="h-3.5 w-3.5" />
          )}
          <span>{statusMeta.label}</span>
        </div>
      </div>

      {/* Progress Bar Container */}
      <div className="space-y-2">
        <div className="flex justify-between text-xs font-semibold">
          <span className="text-zinc-400">Rendering Pipeline Progress</span>
          <span className="text-white font-mono">{job.progress_pct}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800/90">
          <div
            className={`h-full transition-all duration-500 ease-out ${
              job.status === 'failed'
                ? 'bg-rose-500'
                : job.status === 'completed'
                ? 'bg-emerald-500'
                : 'bg-gradient-to-r from-rose-500 via-amber-400 to-violet-500 animate-pulse'
            }`}
            style={{ width: `${Math.max(5, Math.min(100, job.progress_pct))}%` }}
          />
        </div>
      </div>

      {/* Milestone Stages Indicator */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mt-5 pt-4 border-t border-zinc-800/80 text-xs">
        <div className={`flex items-center gap-2 rounded-lg border p-2 ${
          job.progress_pct >= 10
            ? 'border-emerald-500/20 bg-emerald-950/20 text-emerald-400'
            : 'border-zinc-800/60 bg-zinc-950/40 text-zinc-500'
        }`}>
          <div className={`h-1.5 w-1.5 rounded-full ${job.progress_pct >= 10 ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
          <span className="font-medium">1. Transcript</span>
        </div>

        <div className={`flex items-center gap-2 rounded-lg border p-2 ${
          job.progress_pct >= 25
            ? 'border-emerald-500/20 bg-emerald-950/20 text-emerald-400'
            : 'border-zinc-800/60 bg-zinc-950/40 text-zinc-500'
        }`}>
          <div className={`h-1.5 w-1.5 rounded-full ${job.progress_pct >= 25 ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
          <span className="font-medium">2. Gemini Hooks</span>
        </div>

        <div className={`flex items-center gap-2 rounded-lg border p-2 ${
          job.progress_pct >= 30
            ? 'border-emerald-500/20 bg-emerald-950/20 text-emerald-400'
            : 'border-zinc-800/60 bg-zinc-950/40 text-zinc-500'
        }`}>
          <div className={`h-1.5 w-1.5 rounded-full ${job.progress_pct >= 30 ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
          <span className="font-medium">3. Face Tracking</span>
        </div>

        <div className={`flex items-center gap-2 rounded-lg border p-2 ${
          job.progress_pct === 100
            ? 'border-emerald-500/20 bg-emerald-950/20 text-emerald-400'
            : 'border-zinc-800/60 bg-zinc-950/40 text-zinc-500'
        }`}>
          <div className={`h-1.5 w-1.5 rounded-full ${job.progress_pct === 100 ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
          <span className="font-medium">4. Subtitles & Finish</span>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-rose-500/30 bg-rose-950/30 p-3 text-xs text-rose-300">
          <AlertTriangle className="h-4 w-4 shrink-0 text-rose-400 mt-0.5" />
          <div>
            <p className="font-semibold text-rose-200">Pipeline Execution Error:</p>
            <p className="mt-0.5 font-mono text-[11px] break-all text-rose-300">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
