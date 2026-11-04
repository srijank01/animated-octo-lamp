'use client';

import React, { useEffect, useState } from 'react';
import { 
  Film, 
  Trash2, 
  RefreshCw, 
  ExternalLink, 
  Share2
} from 'lucide-react';
import Navbar from '@/components/Navbar';
import JobForm from '@/components/JobForm';
import JobProgress from '@/components/JobProgress';
import ClipCard from '@/components/ClipCard';
import SocialQueue from '@/components/SocialQueue';
import { getJobs, deleteJob, Job, getJobById } from '@/lib/api';

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeDashboardTab, setActiveDashboardTab] = useState<'studio' | 'social'>('studio');
  const [oauthBanner, setOauthBanner] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  useEffect(() => {
    let isMounted = true;

    // Detect OAuth redirect status
    if (typeof window !== 'undefined') {
      const urlParams = new URLSearchParams(window.location.search);
      const oauthParam = urlParams.get('oauth');
      if (oauthParam === 'youtube_connected') {
        setOauthBanner({
          type: 'success',
          message: '🎉 Real YouTube Channel successfully connected via OAuth 2.0! Ready for live publishing.',
        });
        setActiveDashboardTab('social');
        window.history.replaceState({}, '', window.location.pathname);
      } else if (oauthParam === 'error') {
        const msg = urlParams.get('msg') || 'Authentication failed';
        setOauthBanner({
          type: 'error',
          message: `YouTube connection error: ${msg}`,
        });
        window.history.replaceState({}, '', window.location.pathname);
      }
    }

    getJobs()
      .then((data) => {
        if (!isMounted) return;
        setJobs(data);

        // Check if any job is currently in progress
        const ongoing = data.find(
          (j) => j.status !== 'completed' && j.status !== 'failed'
        );
        if (ongoing) {
          setActiveJobId(ongoing.id);
        }

        if (data.length > 0) {
          setSelectedJobId(data[0].id);
        } else {
          setSelectedJobId(null);
        }
      })
      .catch((err) => {
        console.error('Failed to load jobs list:', err);
      })
      .finally(() => {
        if (isMounted) {
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const data = await getJobs();
      setJobs(data);
      if (data.length > 0) {
        setSelectedJobId((prev) => (prev && data.some((j) => j.id === prev) ? prev : data[0].id));
      } else {
        setSelectedJobId(null);
      }
    } catch (err) {
      console.error('Failed to refresh jobs:', err);
    } finally {
      setRefreshing(false);
    }
  };

  const handleJobCreated = (newJob: Job) => {
    setJobs((prev) => [newJob, ...prev.filter((j) => j.id !== newJob.id)]);
    setActiveJobId(newJob.id);
    setSelectedJobId(newJob.id);
    setActiveDashboardTab('studio');
  };

  const handleJobUpdated = (updatedJob: Job) => {
    setJobs((prev) =>
      prev.map((j) => (j.id === updatedJob.id ? { ...j, ...updatedJob } : j))
    );
  };

  const handleJobCompleted = async (completedJob: Job) => {
    setActiveJobId(null);
    try {
      const refreshed = await getJobById(completedJob.id);
      setJobs((prev) =>
        prev.map((j) => (j.id === refreshed.id ? refreshed : j))
      );
      setSelectedJobId(refreshed.id);
    } catch (err) {
      console.error('Failed to refresh completed job:', err);
    }
  };

  const handleDeleteJob = async (jobId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this clipping job and all its generated files?')) {
      return;
    }

    try {
      await deleteJob(jobId);
      const remaining = jobs.filter((j) => j.id !== jobId);
      setJobs(remaining);

      if (activeJobId === jobId) {
        setActiveJobId(null);
      }
      if (selectedJobId === jobId) {
        setSelectedJobId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      alert(`Could not delete job: ${message}`);
    }
  };

  const selectedJob = jobs.find((j) => j.id === selectedJobId) || null;
  const isSelectedJobActive = activeJobId && activeJobId === selectedJobId;
  const totalClipsCount = jobs.reduce((acc, j) => acc + (j.clips?.length || 0), 0);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col font-sans selection:bg-rose-500 selection:text-white">
      <Navbar />

      <main className="flex-1 mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* OAuth Notification Banner */}
        {oauthBanner && (
          <div
            className={`flex items-center justify-between rounded-2xl border p-4 text-xs font-semibold shadow-lg animate-in fade-in slide-in-from-top-2 duration-300 ${
              oauthBanner.type === 'success'
                ? 'border-emerald-500/40 bg-emerald-950/40 text-emerald-300 shadow-emerald-500/5'
                : 'border-rose-500/40 bg-rose-950/40 text-rose-300 shadow-rose-500/5'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <span className="text-sm">{oauthBanner.type === 'success' ? '🎉' : '⚠️'}</span>
              <span>{oauthBanner.message}</span>
            </div>
            <button
              type="button"
              onClick={() => setOauthBanner(null)}
              className="text-zinc-400 hover:text-white ml-3 font-bold px-2 py-1 rounded-lg hover:bg-zinc-800/60 transition-colors"
            >
              ✕
            </button>
          </div>
        )}

        {/* Dashboard Navigation & Studio Metrics Ribbon */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-zinc-800/80 pb-5">
          {/* Segmented View Switcher Tabs */}
          <div className="flex items-center gap-1.5 rounded-2xl border border-zinc-800 bg-zinc-900/80 p-1 backdrop-blur-sm">
            <button
              type="button"
              onClick={() => setActiveDashboardTab('studio')}
              className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition-all ${
                activeDashboardTab === 'studio'
                  ? 'bg-gradient-to-r from-rose-500 via-rose-600 to-amber-500 text-white shadow-md shadow-rose-500/20'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <Film className="h-4 w-4" />
              <span>Clips Studio</span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-mono ${
                activeDashboardTab === 'studio' ? 'bg-black/30 text-white' : 'bg-zinc-800 text-zinc-400'
              }`}>
                {totalClipsCount}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveDashboardTab('social')}
              className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition-all ${
                activeDashboardTab === 'social'
                  ? 'bg-gradient-to-r from-rose-500 via-rose-600 to-amber-500 text-white shadow-md shadow-rose-500/20'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <Share2 className="h-4 w-4" />
              <span>Social Publishing</span>
            </button>
          </div>

          {/* Quick Metrics & Refresh Button */}
          <div className="flex items-center gap-3">
            <div className="hidden md:flex items-center gap-4 text-xs text-zinc-400 pr-2">
              <span className="flex items-center gap-1.5">
                <span className="text-zinc-500">Projects:</span>
                <strong className="text-white font-mono">{jobs.length}</strong>
              </span>
              <span>•</span>
              <span className="flex items-center gap-1.5">
                <span className="text-zinc-500">Shorts:</span>
                <strong className="text-rose-400 font-mono">{totalClipsCount}</strong>
              </span>
              <span>•</span>
              <span className="flex items-center gap-1.5">
                <span className="text-zinc-500">Engine:</span>
                <strong className={`font-medium ${activeJobId ? 'text-amber-400' : 'text-emerald-400'}`}>
                  {activeJobId ? 'Rendering...' : 'Idle'}
                </strong>
              </span>
            </div>

            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshing}
              className="flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/90 px-3.5 py-2 text-xs font-semibold text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors disabled:opacity-50 shadow-sm"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin text-rose-500' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* VIEW 1: CLIPS STUDIO */}
        {activeDashboardTab === 'studio' && (
          <div className="space-y-8 animate-in fade-in duration-200">
            {/* Top Video Submission Dock */}
            <section>
              <JobForm 
                onJobCreated={handleJobCreated} 
                isProcessing={!!activeJobId} 
              />
            </section>

            {/* Active Job Real-Time Progress Tracker */}
            {activeJobId && (
              <section className="animate-in fade-in slide-in-from-top-4 duration-300">
                <JobProgress
                  jobId={activeJobId}
                  onJobUpdated={handleJobUpdated}
                  onJobCompleted={handleJobCompleted}
                />
              </section>
            )}

            {/* Projects & Clips Section */}
            <section className="space-y-6">
              {/* Project Selection Tabs */}
              {jobs.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-semibold text-zinc-400">
                    <span>Recent Video Projects</span>
                    <span>{jobs.length} loaded</span>
                  </div>
                  <div className="flex items-center gap-2.5 overflow-x-auto pb-2 scrollbar-none">
                    {jobs.map((job) => {
                      const isSelected = job.id === selectedJobId;
                      const isRunning = job.status !== 'completed' && job.status !== 'failed';
                      return (
                        <div
                          key={job.id}
                          onClick={() => setSelectedJobId(job.id)}
                          className={`group relative flex cursor-pointer items-center gap-3 rounded-xl border px-4 py-2.5 text-xs transition-all whitespace-nowrap shadow-sm ${
                            isSelected
                              ? 'border-rose-500/50 bg-zinc-900 text-white shadow-md shadow-rose-500/10'
                              : 'border-zinc-800/80 bg-zinc-950/60 text-zinc-400 hover:border-zinc-700 hover:bg-zinc-900/60 hover:text-zinc-200'
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-zinc-200">
                              {job.id === 'seed-stanford-jobs-2005'
                                ? 'Steve Jobs 2005 (Demo)'
                                : `Video ${job.video_id || job.id.slice(0, 6)}`}
                            </span>
                            <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400 font-mono">
                              {job.clips?.length || 0} clips
                            </span>
                            {isRunning && (
                              <span className="h-2 w-2 rounded-full bg-amber-400 animate-ping" />
                            )}
                          </div>

                          {/* Delete button on hover */}
                          <button
                            type="button"
                            onClick={(e) => handleDeleteJob(job.id, e)}
                            title="Delete Project"
                            className="opacity-0 group-hover:opacity-100 p-1 text-zinc-500 hover:text-rose-400 transition-opacity"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Clips Grid Area */}
              {loading ? (
                <div className="flex h-64 items-center justify-center rounded-2xl border border-zinc-800/60 bg-zinc-900/30">
                  <RefreshCw className="h-6 w-6 animate-spin text-rose-500" />
                </div>
              ) : selectedJob && selectedJob.clips && selectedJob.clips.length > 0 ? (
                <div className="space-y-5">
                  {/* Selected Job Info Ribbon */}
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-zinc-800/80 bg-zinc-900/60 px-5 py-3 text-xs text-zinc-400 backdrop-blur-sm">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-zinc-300">Source Video:</span>
                      <a
                        href={selectedJob.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-rose-400 hover:text-rose-300 hover:underline font-mono"
                      >
                        <span className="truncate max-w-xs sm:max-w-md">{selectedJob.source_url}</span>
                        <ExternalLink className="h-3 w-3 shrink-0" />
                      </a>
                    </div>
                    <div className="flex items-center gap-3">
                      <span>Status: <strong className="text-emerald-400 uppercase font-semibold">{selectedJob.status}</strong></span>
                      <span>•</span>
                      <span className="font-semibold text-white">{selectedJob.clips.length} Short(s) Ready</span>
                    </div>
                  </div>

                  {/* 3-Column 9:16 Video Clips Grid */}
                  <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {selectedJob.clips.map((clip, idx) => (
                      <ClipCard key={clip.id || idx} clip={clip} index={idx} onPostPublished={handleRefresh} />
                    ))}
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-12 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-900 text-zinc-500 mb-3 border border-zinc-800">
                    <Film className="h-6 w-6" />
                  </div>
                  <h3 className="text-base font-bold text-white">No clips generated yet</h3>
                  <p className="mt-1 max-w-sm text-xs text-zinc-400">
                    {isSelectedJobActive
                      ? 'Your clips are actively processing. They will appear here one by one as they finish rendering!'
                      : 'Paste a YouTube video URL above to extract high-retention 9:16 shorts.'}
                  </p>
                </div>
              )}
            </section>
          </div>
        )}

        {/* VIEW 2: SOCIAL PUBLISHING HUB */}
        {activeDashboardTab === 'social' && (
          <div className="animate-in fade-in duration-200">
            <SocialQueue onPostUpdated={handleRefresh} />
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="mt-auto border-t border-zinc-900 bg-zinc-950 py-6 text-center text-xs text-zinc-500">
        <p>AutoClip AI Studio • Powered by Gemini 2.5, yt-dlp, OpenCV, Faster-Whisper, and FFmpeg</p>
      </footer>
    </div>
  );
}
