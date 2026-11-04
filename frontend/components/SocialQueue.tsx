'use client';

import React, { useState, useEffect } from 'react';
import {
  Send,
  Calendar,
  CheckCircle2,
  Trash2,
  RefreshCw,
  ExternalLink,
  Plus,
  Radio,
  Clock,
  AlertCircle,
  Share2,
} from 'lucide-react';
import {
  ScheduledPost,
  SocialAccount,
  getScheduledPosts,
  deleteScheduledPost,
  getSocialAccounts,
  connectSocialAccount,
  disconnectSocialAccount,
  getOAuthUrl,
} from '@/lib/api';

interface SocialQueueProps {
  onPostUpdated?: () => void;
}

export default function SocialQueue({ onPostUpdated }: SocialQueueProps) {
  const [activeTab, setActiveTab] = useState<'queue' | 'history' | 'accounts'>('queue');
  const [posts, setPosts] = useState<ScheduledPost[]>([]);
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // New account form state
  const [showConnectForm, setShowConnectForm] = useState(false);
  const [newPlatform, setNewPlatform] = useState('youtube');
  const [newAccountName, setNewAccountName] = useState('');
  const [newChannelId, setNewChannelId] = useState('');
  const [isSubmittingAccount, setIsSubmittingAccount] = useState(false);
  const [connectingOAuth, setConnectingOAuth] = useState(false);

  const fetchData = async () => {
    try {
      const [fetchedPosts, fetchedAccounts] = await Promise.all([
        getScheduledPosts(),
        getSocialAccounts(),
      ]);
      setPosts(fetchedPosts);
      setAccounts(fetchedAccounts);
    } catch (err) {
      console.error('Failed to load social queue data:', err);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchData().finally(() => setLoading(false));
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  };

  const handleDeletePost = async (postId: string) => {
    if (!confirm('Are you sure you want to cancel or remove this post record?')) return;
    try {
      await deleteScheduledPost(postId);
      setPosts((prev) => prev.filter((p) => p.id !== postId));
      if (onPostUpdated) onPostUpdated();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to delete post';
      alert(msg);
    }
  };

  const handleConnectAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAccountName.trim()) return;

    setIsSubmittingAccount(true);
    try {
      const created = await connectSocialAccount({
        platform: newPlatform,
        account_name: newAccountName.trim(),
        channel_id: newChannelId.trim() || undefined,
        mode: 'sandbox',
      });
      setAccounts((prev) => [created, ...prev.filter((a) => a.id !== created.id)]);
      setShowConnectForm(false);
      setNewAccountName('');
      setNewChannelId('');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to connect account';
      alert(msg);
    } finally {
      setIsSubmittingAccount(false);
    }
  };

  const handleDisconnectAccount = async (accountId: string) => {
    if (!confirm('Disconnect this creator account?')) return;
    try {
      await disconnectSocialAccount(accountId);
      setAccounts((prev) => prev.filter((a) => a.id !== accountId));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to disconnect account';
      alert(msg);
    }
  };

  const handleOAuthConnect = async () => {
    setConnectingOAuth(true);
    try {
      const res = await getOAuthUrl('http://localhost:8000/api/social/oauth/youtube/callback');
      const targetUrl = res.auth_url || res.url;
      if (targetUrl) {
        window.location.href = targetUrl;
      } else {
        alert('Could not retrieve Google OAuth authorization link.');
        setConnectingOAuth(false);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'OAuth request failed';
      alert(msg);
      setConnectingOAuth(false);
    }
  };

  const scheduledPosts = posts.filter((p) => p.status === 'scheduled' || p.status === 'uploading');
  const publishedPosts = posts.filter((p) => p.status === 'published' || p.status === 'failed');

  const getPlatformIcon = (platform: string) => {
    if (platform.includes('youtube')) {
      return (
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-500/10 text-rose-500 border border-rose-500/20">
          <svg width="24" height="24" className="h-4 w-4 fill-current" viewBox="0 0 24 24">
            <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
          </svg>
        </span>
      );
    }
    if (platform.includes('instagram')) {
      return (
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-pink-500/10 text-pink-400 border border-pink-500/20">
          <svg width="24" height="24" className="h-4 w-4 fill-current" viewBox="0 0 24 24">
            <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
          </svg>
        </span>
      );
    }
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
        <svg width="24" height="24" className="h-4 w-4 fill-current" viewBox="0 0 24 24">
          <path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.24 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z" />
        </svg>
      </span>
    );
  };

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/90 p-5 sm:p-6 text-zinc-100 shadow-xl backdrop-blur-md space-y-6">
      {/* Top Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-zinc-800/80 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-rose-500 to-amber-500 text-white shadow-md shadow-rose-500/20">
            <Share2 className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm sm:text-base font-bold text-white">
              Social Auto-Publisher & Schedule Queue
            </h3>
            <p className="text-xs text-zinc-400">
              Publish directly or queue automated uploads to YouTube Shorts, Instagram Reels & TikTok.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* Connect Real YouTube Channel Button */}
          <button
            type="button"
            onClick={handleOAuthConnect}
            disabled={connectingOAuth}
            className="flex items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 px-3.5 py-2 text-xs font-bold text-rose-300 hover:bg-rose-500/20 hover:border-rose-500 transition-all shadow-sm shadow-rose-500/10 disabled:opacity-50"
          >
            <span>🔗</span>
            <span>{connectingOAuth ? 'Redirecting to Google...' : 'Connect Real YouTube Channel'}</span>
          </button>

          {/* Refresh Button */}
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin text-rose-500' : ''}`} />
            <span>Sync</span>
          </button>
        </div>
      </div>

      {/* Segmented Tabs Switcher */}
      <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveTab('queue')}
            className={`flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold transition-all ${
              activeTab === 'queue'
                ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
            }`}
          >
            <Clock className="h-3.5 w-3.5" />
            <span>Scheduled Queue ({scheduledPosts.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold transition-all ${
              activeTab === 'history'
                ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
            }`}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span>Published Feed ({publishedPosts.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('accounts')}
            className={`flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold transition-all ${
              activeTab === 'accounts'
                ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
            }`}
          >
            <Radio className="h-3.5 w-3.5" />
            <span>Connected Channels ({accounts.length})</span>
          </button>
        </div>
      </div>

      {/* TAB CONTENT: Scheduled Queue */}
      {activeTab === 'queue' && (
        <div className="space-y-3">
          {scheduledPosts.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40 p-8 text-center text-xs text-zinc-400">
              <Calendar className="mx-auto h-7 w-7 text-zinc-500 mb-2" />
              <p className="font-medium text-zinc-300">No uploads currently queued.</p>
              <p className="mt-1 text-zinc-500">Click &ldquo;Publish / Schedule&rdquo; on any generated short to enqueue an automatic upload.</p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/60">
              {scheduledPosts.map((post) => (
                <div key={post.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 text-xs border-b border-zinc-800/80 last:border-b-0">
                  <div className="flex items-center gap-3">
                    {getPlatformIcon(post.platform)}
                    <div>
                      <h4 className="font-semibold text-white">{post.title}</h4>
                      <div className="flex items-center gap-2 text-[11px] text-zinc-400 mt-0.5">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3 text-amber-400" />
                          <span>
                            {post.scheduled_for
                              ? `Due: ${new Date(post.scheduled_for).toLocaleString()}`
                              : 'Immediate Queue'}
                          </span>
                        </span>
                        <span>•</span>
                        <span className="capitalize">{post.privacy_status}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <span className="rounded-full bg-amber-500/10 border border-amber-500/20 px-2.5 py-0.5 text-[10px] font-bold text-amber-400">
                      {post.status.toUpperCase()}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleDeletePost(post.id)}
                      title="Cancel post"
                      className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-rose-400 transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT: Published History */}
      {activeTab === 'history' && (
        <div className="space-y-3">
          {publishedPosts.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40 p-8 text-center text-xs text-zinc-400">
              <CheckCircle2 className="mx-auto h-7 w-7 text-zinc-500 mb-2" />
              <p className="font-medium text-zinc-300">No published shorts recorded yet.</p>
              <p className="mt-1 text-zinc-500">Completed uploads will appear here with direct platform links.</p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/60">
              {publishedPosts.map((post) => (
                <div key={post.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 text-xs border-b border-zinc-800/80 last:border-b-0">
                  <div className="flex items-center gap-3">
                    {getPlatformIcon(post.platform)}
                    <div>
                      <h4 className="font-semibold text-white">{post.title}</h4>
                      <p className="text-[11px] text-zinc-400 mt-0.5">
                        {post.published_at ? `Published on ${new Date(post.published_at).toLocaleString()}` : 'Date unknown'}
                      </p>
                      {post.error_message && (
                        <p className="text-[11px] text-rose-400 flex items-center gap-1 mt-1">
                          <AlertCircle className="h-3 w-3" />
                          <span>{post.error_message}</span>
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {post.status === 'published' ? (
                      <span className="rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 text-[10px] font-bold text-emerald-400">
                        PUBLISHED
                      </span>
                    ) : (
                      <span className="rounded-full bg-rose-500/10 border border-rose-500/20 px-2.5 py-0.5 text-[10px] font-bold text-rose-400">
                        FAILED
                      </span>
                    )}

                    {post.platform_url && (
                      <a
                        href={post.platform_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-200 hover:bg-zinc-700 hover:text-white transition-colors"
                      >
                        <span>View</span>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}

                    <button
                      type="button"
                      onClick={() => handleDeletePost(post.id)}
                      title="Delete record"
                      className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-rose-400 transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT: Connected Accounts */}
      {activeTab === 'accounts' && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-zinc-400">Authorized Channels & Social Profiles</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleOAuthConnect}
                disabled={connectingOAuth}
                className="flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-1.5 text-xs font-bold text-rose-200 hover:bg-rose-500/25 transition-all shadow-sm disabled:opacity-50"
              >
                <span>🔗</span>
                <span>{connectingOAuth ? 'Redirecting...' : 'Connect Real YouTube Channel'}</span>
              </button>
              <button
                type="button"
                onClick={() => setShowConnectForm(!showConnectForm)}
                className="flex items-center gap-1 rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1.5 text-xs font-semibold text-zinc-200 hover:bg-zinc-700 hover:text-white transition-colors"
              >
                <Plus className="h-3 w-3" />
                <span>Add Channel</span>
              </button>
            </div>
          </div>

          {/* Connect Account Form */}
          {showConnectForm && (
            <form onSubmit={handleConnectAccount} className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4 space-y-3 animate-in fade-in duration-200">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-zinc-400">Platform</label>
                  <select
                    value={newPlatform}
                    onChange={(e) => setNewPlatform(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-rose-500"
                  >
                    <option value="youtube">YouTube</option>
                    <option value="instagram">Instagram</option>
                    <option value="tiktok">TikTok</option>
                  </select>
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-zinc-400">Account / Handle</label>
                  <input
                    type="text"
                    required
                    placeholder="@CreatorName"
                    value={newAccountName}
                    onChange={(e) => setNewAccountName(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-xs text-white placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-rose-500"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-zinc-400">Channel ID (Optional)</label>
                  <input
                    type="text"
                    placeholder="UC_xxx or username"
                    value={newChannelId}
                    onChange={(e) => setNewChannelId(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-xs text-white placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-rose-500"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowConnectForm(false)}
                  className="rounded-lg border border-zinc-800 px-3 py-1.5 text-xs text-zinc-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingAccount}
                  className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500 transition-colors"
                >
                  {isSubmittingAccount ? 'Connecting...' : 'Save Account'}
                </button>
              </div>
            </form>
          )}

          {/* Accounts List */}
          <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/60">
            {accounts.map((acc) => (
              <div key={acc.id} className="flex items-center justify-between p-4 text-xs border-b border-zinc-800/80 last:border-b-0">
                <div className="flex items-center gap-3">
                  {getPlatformIcon(acc.platform)}
                  <div>
                    <h4 className="font-semibold text-white">{acc.account_name}</h4>
                    <p className="text-[11px] text-zinc-400 mt-0.5">
                      Channel ID: {acc.channel_id || 'N/A'} • Connected {new Date(acc.connected_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold tracking-wide ${
                    acc.mode === 'live_oauth'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm shadow-emerald-500/20'
                      : 'bg-zinc-800 text-zinc-400 border border-zinc-700/60'
                  }`}>
                    {acc.mode === 'live_oauth' ? '● LIVE OAUTH' : 'SANDBOX MODE'}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleDisconnectAccount(acc.id)}
                    title="Disconnect account"
                    className="rounded-lg p-1.5 text-zinc-500 hover:text-rose-400 transition-colors"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
