'use client';

import React, { useEffect, useState } from 'react';
import { Video, ExternalLink } from 'lucide-react';
import { getHealth } from '@/lib/api';

export default function Navbar() {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking');
  const [clipCount, setClipCount] = useState<number>(0);

  useEffect(() => {
    let mounted = true;
    async function checkStatus() {
      try {
        const health = await getHealth();
        if (mounted) {
          setBackendStatus(health.status === 'ok' ? 'connected' : 'disconnected');
          setClipCount(health.total_clips || 0);
        }
      } catch {
        if (mounted) {
          setBackendStatus('disconnected');
        }
      }
    }

    checkStatus();
    const interval = setInterval(checkStatus, 10000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-rose-500 via-rose-600 to-amber-500 shadow-md shadow-rose-500/20">
            <Video className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-base sm:text-lg font-bold tracking-tight text-white">
                AutoClip <span className="bg-gradient-to-r from-rose-400 via-amber-300 to-violet-400 bg-clip-text text-transparent">AI</span>
              </span>
              <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
                Studio
              </span>
            </div>
            <p className="hidden sm:block text-[11px] text-zinc-400">
              Zero-download viral hook extraction & 9:16 smart reframing
            </p>
          </div>
        </div>

        {/* Status Indicators & Links */}
        <div className="flex items-center gap-3">
          {/* Backend Status Pill */}
          <div className="flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900/80 px-3 py-1.5 text-xs text-zinc-300 shadow-sm">
            <span
              className={`h-2 w-2 rounded-full ${
                backendStatus === 'connected'
                  ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50 animate-pulse'
                  : backendStatus === 'checking'
                  ? 'bg-amber-500'
                  : 'bg-rose-500'
              }`}
            />
            <span className="font-medium">
              {backendStatus === 'connected'
                ? `Engine Live (${clipCount} clips)`
                : backendStatus === 'checking'
                ? 'Connecting...'
                : 'Engine Offline'}
            </span>
          </div>

          {/* API Docs Link */}
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition-colors hover:border-zinc-700 hover:bg-zinc-800 hover:text-white"
          >
            <span>FastAPI Docs</span>
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>
    </header>
  );
}
