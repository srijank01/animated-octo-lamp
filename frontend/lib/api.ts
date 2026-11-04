/**
 * API Service Layer for AI Video Clipping Backend.
 */

export interface EditStats {
  jump_cuts_count: number;
  dead_air_removed_sec: number;
  layout_mode: 'single_tracked' | 'split_screen' | 'dynamic_zoom' | 'blurred_background' | string;
  segments_count: number;
  dynamic_zooms_count?: number;
}

export interface SocialMetadata {
  youtube_title: string;
  youtube_description: string;
  youtube_tags: string[];
  instagram_caption: string;
  tiktok_caption: string;
}

export interface Clip {
  id: string;
  job_id: string;
  clip_index: number;
  title: string;
  hook_text: string;
  start_time: number;
  end_time: number;
  duration: number;
  virality_score: number;
  reasoning?: string;
  video_url: string;
  preview_url: string;
  subtitles_url?: string;
  file_size_mb?: number;
  edit_stats?: EditStats;
  social_metadata?: SocialMetadata;
}

export interface SocialAccount {
  id: string;
  platform: 'youtube' | 'instagram' | 'tiktok' | string;
  account_name: string;
  channel_id?: string | null;
  mode: 'live_oauth' | 'sandbox';
  connected_at: string;
  credentials_json?: any;
}

export interface ScheduledPost {
  id: string;
  clip_id: string;
  job_id?: string | null;
  platform: 'youtube_shorts' | 'instagram_reels' | 'tiktok' | string;
  title: string;
  caption?: string | null;
  tags?: string[] | string | null;
  privacy_status: 'public' | 'unlisted' | 'private' | string;
  scheduled_for?: string | null;
  status: 'scheduled' | 'uploading' | 'published' | 'failed';
  platform_post_id?: string | null;
  platform_url?: string | null;
  error_message?: string | null;
  created_at: string;
  published_at?: string | null;
}

export interface PublishPayload {
  clip_id: string;
  platform: 'youtube_shorts' | 'instagram_reels' | 'tiktok';
  title: string;
  caption?: string;
  tags?: string[];
  privacy_status?: 'public' | 'unlisted' | 'private';
  scheduled_for?: string | null;
}

export type JobStatus =
  | 'queued'
  | 'extracting_transcript'
  | 'selecting_hooks'
  | 'processing_clips'
  | 'completed'
  | 'failed';

export interface Job {
  id: string;
  source_url: string;
  video_id?: string;
  num_clips: number;
  status: JobStatus;
  progress_pct: number;
  current_step: string;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
  clips: Clip[];
}

export interface HealthInfo {
  status: string;
  app: string;
  version: string;
  timestamp: string;
  database: string;
  total_jobs: number;
  total_clips: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/**
 * Resolves a relative media path (e.g. /media/final_clips/...) to the full backend URL.
 */
export function resolveMediaUrl(path?: string): string {
  if (!path) return '';
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  const cleanBase = API_BASE.replace(/\/+$/, '');
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${cleanBase}${cleanPath}`;
}

/**
 * Fetch health & database status from the backend.
 */
export async function getHealth(): Promise<HealthInfo> {
  const res = await fetch(`${API_BASE}/api/health`, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Health check failed with status: ${res.status}`);
  }
  return res.json();
}

/**
 * Create and enqueue a new clipping job.
 */
export async function createJob(sourceUrl: string, numClips: number = 3): Promise<Job> {
  const res = await fetch(`${API_BASE}/api/jobs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      source_url: sourceUrl.trim(),
      num_clips: numClips,
    }),
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(errorBody.detail || `Failed to create job (${res.status})`);
  }

  return res.json();
}

/**
 * List all clipping jobs sorted by creation date descending.
 */
export async function getJobs(): Promise<Job[]> {
  const res = await fetch(`${API_BASE}/api/jobs`, { credentials: 'omit', cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to list jobs (${res.status})`);
  }
  return res.json();
}

/**
 * Retrieve status, progress, and generated clips for a specific job.
 */
export async function getJobById(jobId: string): Promise<Job> {
  const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`, {
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch job ${jobId} (${res.status})`);
  }
  return res.json();
}

/**
 * Delete a job and its associated media from backend storage.
 */
export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(`Failed to delete job ${jobId} (${res.status})`);
  }
}

/**
 * List all connected social media accounts (or filter by platform).
 */
export async function getSocialAccounts(platform?: string): Promise<SocialAccount[]> {
  const url = platform ? `${API_BASE}/api/social/accounts?platform=${platform}` : `${API_BASE}/api/social/accounts`;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to fetch social accounts (${res.status})`);
  }
  return res.json();
}

/**
 * Connect a new social account.
 */
export async function connectSocialAccount(data: {
  platform: string;
  account_name: string;
  channel_id?: string;
  mode?: string;
  credentials_json?: any;
}): Promise<SocialAccount> {
  const res = await fetch(`${API_BASE}/api/social/accounts/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw new Error(`Failed to connect account (${res.status})`);
  }
  return res.json();
}

/**
 * Disconnect an existing social account.
 */
export async function disconnectSocialAccount(accountId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/social/accounts/${encodeURIComponent(accountId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(`Failed to disconnect account (${res.status})`);
  }
}

/**
 * Get YouTube OAuth authorization URL.
 */
export async function getOAuthUrl(redirectUri?: string): Promise<{ url: string; auth_url?: string; mode: string; message: string }> {
  const uri = redirectUri || 'http://localhost:8000/api/social/oauth/youtube/callback';
  const res = await fetch(`${API_BASE}/api/social/accounts/oauth-url?redirect_uri=${encodeURIComponent(uri)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch OAuth URL (${res.status})`);
  }
  return res.json();
}

/**
 * Trigger on-demand AI regeneration of social copy/metadata for a clip.
 */
export async function generateClipMetadata(
  clipId: string,
  customPrompt?: string
): Promise<{ status: string; clip_id: string; social_metadata: SocialMetadata; clip: Clip }> {
  const res = await fetch(`${API_BASE}/api/clips/${encodeURIComponent(clipId)}/generate-metadata`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ custom_prompt: customPrompt || null }),
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: 'Failed to generate metadata' }));
    throw new Error(errorBody.detail || `Failed to generate metadata (${res.status})`);
  }
  return res.json();
}

/**
 * Publish immediately or enqueue scheduled post.
 */
export async function publishClip(payload: PublishPayload): Promise<ScheduledPost> {
  const res = await fetch(`${API_BASE}/api/social/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: 'Failed to publish clip' }));
    throw new Error(errorBody.detail || `Publish error (${res.status})`);
  }
  return res.json();
}

/**
 * Fetch all posts in the publishing queue.
 */
export async function getScheduledPosts(params?: {
  clipId?: string;
  jobId?: string;
  status?: string;
}): Promise<ScheduledPost[]> {
  const searchParams = new URLSearchParams();
  if (params?.clipId) searchParams.set('clip_id', params.clipId);
  if (params?.jobId) searchParams.set('job_id', params.jobId);
  if (params?.status) searchParams.set('status', params.status);

  const queryStr = searchParams.toString();
  const url = queryStr ? `${API_BASE}/api/social/posts?${queryStr}` : `${API_BASE}/api/social/posts`;

  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to fetch scheduled posts (${res.status})`);
  }
  return res.json();
}

/**
 * Cancel or delete a post from the queue.
 */
export async function deleteScheduledPost(postId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/social/posts/${encodeURIComponent(postId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(`Failed to delete post (${res.status})`);
  }
}


