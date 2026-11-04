"""SQLite Job, Clip, & Social Media Persistence Layer.

Provides thread-safe storage for:
1. Clipping jobs & Progressive pipeline state
2. Generated clips & word-level karaoke subtitles
3. Social media OAuth / Sandbox accounts (YouTube Shorts, Instagram Reels, TikTok)
4. Scheduled publishing queue with status tracking
"""

import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BACKEND_DIR / "output" / "jobs.db"


@contextmanager
def get_db_connection(db_path: Path | str = DEFAULT_DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Provide a thread-safe connection with dictionary rows and foreign keys enabled."""
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Initialize database tables, indexes, and migrations."""
    with get_db_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                video_id TEXT,
                num_clips INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'queued',
                progress_pct INTEGER NOT NULL DEFAULT 0,
                current_step TEXT NOT NULL DEFAULT 'Job initialized',
                error_message TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS clips (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                clip_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                hook_text TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                duration REAL NOT NULL,
                virality_score INTEGER NOT NULL,
                reasoning TEXT,
                video_url TEXT NOT NULL,
                preview_url TEXT NOT NULL,
                subtitles_url TEXT,
                file_size_mb REAL,
                edit_stats TEXT,
                social_metadata TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
            );
        """)

        # Social Accounts Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS social_accounts (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                account_name TEXT NOT NULL,
                channel_id TEXT,
                mode TEXT NOT NULL DEFAULT 'sandbox',
                credentials_json TEXT,
                connected_at TEXT NOT NULL
            );
        """)

        # Scheduled & Published Posts Queue
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL,
                job_id TEXT,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                caption TEXT,
                tags TEXT,
                privacy_status TEXT NOT NULL DEFAULT 'public',
                scheduled_for TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                platform_post_id TEXT,
                platform_url TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                published_at TEXT,
                FOREIGN KEY (clip_id) REFERENCES clips (id) ON DELETE CASCADE
            );
        """)

        # OAuth State & PKCE Code Verifier Store
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                code_verifier TEXT,
                redirect_uri TEXT,
                created_at REAL NOT NULL
            );
        """)

        # Graceful migrations for existing databases
        cursor = conn.execute("PRAGMA table_info(clips);")
        columns = [row["name"] for row in cursor.fetchall()]
        if columns and "edit_stats" not in columns:
            conn.execute("ALTER TABLE clips ADD COLUMN edit_stats TEXT;")
        if columns and "social_metadata" not in columns:
            conn.execute("ALTER TABLE clips ADD COLUMN social_metadata TEXT;")

        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clips_job_id ON clips(job_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_status ON scheduled_posts(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_clip_id ON scheduled_posts(clip_id);")

        # Backfill legacy clips if social_metadata is NULL
        null_meta_clips = conn.execute("SELECT id, title, hook_text FROM clips WHERE social_metadata IS NULL").fetchall()
        for c in null_meta_clips:
            clean_title = (c["title"] or "Viral Clip").strip()
            clean_hook = (c["hook_text"] or clean_title).strip()
            default_meta = {
                "youtube_title": f"{clean_title[:80]} #Shorts",
                "youtube_description": f"{clean_hook}\n\n#Shorts #Viral #Trending #Quotes #Mindset",
                "youtube_tags": ["Shorts", "Viral", "Trending", "Motivation", "Podcast"],
                "instagram_caption": f"\"{clean_hook}\"\n\nDrop your thoughts below 👇\n\n#reels #viral #explore #mindset #motivation",
                "tiktok_caption": f"{clean_hook[:90]} #fyp #viral #trending #mindset",
            }
            conn.execute(
                "UPDATE clips SET social_metadata = ? WHERE id = ?",
                (json.dumps(default_meta), c["id"]),
            )

        # Auto-seed initial Sandbox Social Accounts if none exist
        acct_count = conn.execute("SELECT COUNT(*) FROM social_accounts").fetchone()[0]
        if acct_count == 0:
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO social_accounts (id, platform, account_name, channel_id, mode, credentials_json, connected_at)
                VALUES
                    ('sandbox-youtube', 'youtube', 'AutoClip Creator (YouTube Sandbox)', 'UC_sandbox_autoclip_01', 'sandbox', NULL, ?),
                    ('sandbox-instagram', 'instagram', '@autoclip.ai (Instagram Sandbox)', 'ig_sandbox_88', 'sandbox', NULL, ?),
                    ('sandbox-tiktok', 'tiktok', '@autoclip_viral (TikTok Sandbox)', 'tt_sandbox_77', 'sandbox', NULL, ?)
                """,
                (now_iso, now_iso, now_iso),
            )

    logger.info(f"Database initialized at {db_path}")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Convert a sqlite3.Row to a standard Python dictionary, parsing JSON fields."""
    if row is None:
        return None
    d = {key: row[key] for key in row.keys()}
    for json_field in ["edit_stats", "social_metadata", "tags", "credentials_json"]:
        if json_field in d and isinstance(d[json_field], str) and d[json_field].strip():
            try:
                d[json_field] = json.loads(d[json_field])
            except Exception:
                pass
    return d


# -----------------------------------------------------------------------------
# Jobs CRUD
# -----------------------------------------------------------------------------
def create_job(
    source_url: str,
    video_id: str | None = None,
    num_clips: int = 3,
    job_id: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Create a new job in queued state."""
    job_uuid = job_id or str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, source_url, video_id, num_clips, status, progress_pct, current_step, created_at)
            VALUES (?, ?, ?, ?, 'queued', 0, 'Job queued for processing', ?)
            """,
            (job_uuid, source_url, video_id, int(num_clips), now_iso),
        )

    return get_job(job_uuid, db_path=db_path)  # type: ignore[return-value]


def update_job(
    job_id: str,
    db_path: Path | str = DEFAULT_DB_PATH,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Update fields on an existing job."""
    allowed_fields = {
        "status",
        "progress_pct",
        "current_step",
        "error_message",
        "video_id",
        "completed_at",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return get_job(job_id, db_path=db_path)

    clauses = [f"{k} = ?" for k in updates.keys()]
    values = list(updates.values()) + [job_id]

    with get_db_connection(db_path) as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(clauses)} WHERE id = ?",
            values,
        )

    return get_job(job_id, db_path=db_path)


def get_job(job_id: str, db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """Retrieve a single job with all associated clips."""
    with get_db_connection(db_path) as conn:
        job_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job_row:
            return None

        job = row_to_dict(job_row)
        clip_rows = conn.execute(
            "SELECT * FROM clips WHERE job_id = ? ORDER BY clip_index ASC",
            (job_id,),
        ).fetchall()
        job["clips"] = [row_to_dict(r) for r in clip_rows]
        return job


def get_all_jobs(
    include_clips: bool = True,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Retrieve all jobs ordered by creation date descending."""
    with get_db_connection(db_path) as conn:
        job_rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        jobs = [row_to_dict(r) for r in job_rows]

        if not include_clips:
            return jobs

        for job in jobs:
            clip_rows = conn.execute(
                "SELECT * FROM clips WHERE job_id = ? ORDER BY clip_index ASC",
                (job["id"],),
            ).fetchall()
            job["clips"] = [row_to_dict(r) for r in clip_rows]

        return jobs


def delete_job(job_id: str, db_path: Path | str = DEFAULT_DB_PATH) -> bool:
    """Delete a job and its associated clips."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0


# -----------------------------------------------------------------------------
# Clips CRUD
# -----------------------------------------------------------------------------
def add_clip(
    job_id: str,
    clip_data: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Add a generated clip to a job."""
    clip_id = clip_data.get("id") or str(uuid.uuid4())

    raw_edit_stats = clip_data.get("edit_stats")
    if isinstance(raw_edit_stats, dict):
        edit_stats_str = json.dumps(raw_edit_stats)
    elif isinstance(raw_edit_stats, str):
        edit_stats_str = raw_edit_stats
    else:
        edit_stats_str = None

    raw_social_metadata = clip_data.get("social_metadata")
    if hasattr(raw_social_metadata, "model_dump"):
        social_metadata_str = json.dumps(raw_social_metadata.model_dump())
    elif isinstance(raw_social_metadata, dict):
        social_metadata_str = json.dumps(raw_social_metadata)
    elif isinstance(raw_social_metadata, str):
        social_metadata_str = raw_social_metadata
    else:
        social_metadata_str = None

    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO clips (
                id, job_id, clip_index, title, hook_text, start_time, end_time,
                duration, virality_score, reasoning, video_url, preview_url,
                subtitles_url, file_size_mb, edit_stats, social_metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                job_id,
                clip_data["clip_index"],
                clip_data["title"],
                clip_data["hook_text"],
                float(clip_data["start_time"]),
                float(clip_data["end_time"]),
                float(clip_data["duration"]),
                int(clip_data["virality_score"]),
                clip_data.get("reasoning", ""),
                clip_data["video_url"],
                clip_data["preview_url"],
                clip_data.get("subtitles_url"),
                float(clip_data.get("file_size_mb", 0.0)),
                edit_stats_str,
                social_metadata_str,
            ),
        )

    return get_clip(clip_id, db_path=db_path) or {}


def get_clip(clip_id: str, db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """Retrieve a single clip by its ID."""
    with get_db_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return row_to_dict(row)


def update_clip_metadata(
    clip_id: str,
    social_metadata: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Update social_metadata for an existing clip."""
    meta_str = json.dumps(social_metadata) if isinstance(social_metadata, dict) else str(social_metadata)
    with get_db_connection(db_path) as conn:
        conn.execute("UPDATE clips SET social_metadata = ? WHERE id = ?", (meta_str, clip_id))
    return get_clip(clip_id, db_path=db_path)


# -----------------------------------------------------------------------------
# Social Accounts CRUD
# -----------------------------------------------------------------------------
def get_social_accounts(
    platform: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """List all connected social media accounts, optionally filtered by platform."""
    with get_db_connection(db_path) as conn:
        if platform:
            rows = conn.execute(
                "SELECT * FROM social_accounts WHERE platform = ? ORDER BY connected_at DESC",
                (platform,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM social_accounts ORDER BY connected_at DESC"
            ).fetchall()
        return [row_to_dict(r) for r in rows]


def get_social_account(
    account_id: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Retrieve a social account by its ID."""
    with get_db_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM social_accounts WHERE id = ?", (account_id,)).fetchone()
        return row_to_dict(row)


def upsert_social_account(
    account_data: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Insert or update a social media account."""
    acct_id = account_data.get("id") or f"{account_data['platform']}-{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    creds = account_data.get("credentials_json")
    creds_str = json.dumps(creds) if isinstance(creds, dict) else creds

    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO social_accounts (id, platform, account_name, channel_id, mode, credentials_json, connected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                account_name = excluded.account_name,
                channel_id = excluded.channel_id,
                mode = excluded.mode,
                credentials_json = excluded.credentials_json,
                connected_at = excluded.connected_at
            """,
            (
                acct_id,
                account_data["platform"],
                account_data["account_name"],
                account_data.get("channel_id"),
                account_data.get("mode", "sandbox"),
                creds_str,
                now_iso,
            ),
        )
    return get_social_account(acct_id, db_path=db_path) or {}


def delete_social_account(account_id: str, db_path: Path | str = DEFAULT_DB_PATH) -> bool:
    """Disconnect and delete a social account."""
    with get_db_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM social_accounts WHERE id = ?", (account_id,))
        return cur.rowcount > 0


def save_oauth_state(
    state: str,
    code_verifier: str | None,
    redirect_uri: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    """Persist an OAuth flow state and PKCE code_verifier for callback verification."""
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO oauth_states (state, code_verifier, redirect_uri, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (state, code_verifier, redirect_uri, time.time()),
        )


def consume_oauth_state(
    state: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Retrieve and delete an OAuth state record (one-time consumption)."""
    with get_db_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM oauth_states WHERE state = ?", (state,)).fetchone()
        if not row:
            return None
        data = {
            "state": row["state"],
            "code_verifier": row["code_verifier"],
            "redirect_uri": row["redirect_uri"],
            "created_at": row["created_at"],
        }
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        # Housekeeping: purge any lingering state entries older than 1 hour
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (time.time() - 3600,))
        return data


# -----------------------------------------------------------------------------
# Scheduled Posts CRUD
# -----------------------------------------------------------------------------
def create_scheduled_post(
    post_data: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Create a new post in scheduled (or uploading) state."""
    post_id = post_data.get("id") or str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    tags = post_data.get("tags")
    tags_str = json.dumps(tags) if isinstance(tags, list) else (tags or "[]")

    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scheduled_posts (
                id, clip_id, job_id, platform, title, caption, tags,
                privacy_status, scheduled_for, status, platform_post_id,
                platform_url, error_message, created_at, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                post_data["clip_id"],
                post_data.get("job_id"),
                post_data["platform"],
                post_data["title"],
                post_data.get("caption", ""),
                tags_str,
                post_data.get("privacy_status", "public"),
                post_data.get("scheduled_for"),
                post_data.get("status", "scheduled"),
                post_data.get("platform_post_id"),
                post_data.get("platform_url"),
                post_data.get("error_message"),
                now_iso,
                post_data.get("published_at"),
            ),
        )
    return get_scheduled_post(post_id, db_path=db_path) or {}


def get_scheduled_post(post_id: str, db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """Retrieve a single scheduled post record."""
    with get_db_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?", (post_id,))
        return row_to_dict(row.fetchone())


def update_scheduled_post(
    post_id: str,
    db_path: Path | str = DEFAULT_DB_PATH,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Update fields on a scheduled post (e.g., status, platform_url, published_at)."""
    allowed_fields = {
        "status",
        "platform_post_id",
        "platform_url",
        "error_message",
        "published_at",
        "scheduled_for",
        "title",
        "caption",
        "privacy_status",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return get_scheduled_post(post_id, db_path=db_path)

    clauses = [f"{k} = ?" for k in updates.keys()]
    values = list(updates.values()) + [post_id]

    with get_db_connection(db_path) as conn:
        conn.execute(f"UPDATE scheduled_posts SET {', '.join(clauses)} WHERE id = ?", values)
    return get_scheduled_post(post_id, db_path=db_path)


def get_scheduled_posts(
    clip_id: str | None = None,
    job_id: str | None = None,
    status: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Retrieve scheduled and published posts with optional filters."""
    query = "SELECT * FROM scheduled_posts WHERE 1=1"
    params: list[Any] = []

    if clip_id:
        query += " AND clip_id = ?"
        params.append(clip_id)
    if job_id:
        query += " AND job_id = ?"
        params.append(job_id)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC"

    with get_db_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [row_to_dict(r) for r in rows]


def get_due_scheduled_posts(db_path: Path | str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Retrieve posts that are due for publishing."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM scheduled_posts
            WHERE status = 'scheduled'
              AND (scheduled_for IS NULL OR scheduled_for <= ?)
            ORDER BY created_at ASC
            """,
            (now_iso,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def delete_scheduled_post(post_id: str, db_path: Path | str = DEFAULT_DB_PATH) -> bool:
    """Delete / cancel a scheduled post record."""
    with get_db_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
        return cur.rowcount > 0


# -----------------------------------------------------------------------------
# Seeding Helper
# -----------------------------------------------------------------------------
def seed_from_phase3_if_empty(
    db_path: Path | str = DEFAULT_DB_PATH,
    phase3_json_path: Path | str | None = None,
) -> bool:
    """If database has no jobs, seed it with Phase 3 verified output and social metadata."""
    json_path = (
        Path(phase3_json_path)
        if phase3_json_path
        else BACKEND_DIR / "output" / "phase3_clips.json"
    )

    with get_db_connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if count > 0:
            return False

    if not json_path.exists():
        logger.info(f"No seed file found at {json_path}")
        return False

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        seed_job_id = "seed-stanford-jobs-2005"
        now_iso = datetime.now(timezone.utc).isoformat()
        video_id = data.get("video_id", "UF8uR6Z6KLc")
        source_url = data.get("source_url", "https://www.youtube.com/watch?v=UF8uR6Z6KLc")
        clips = data.get("final_clips", [])

        with get_db_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, source_url, video_id, num_clips, status,
                    progress_pct, current_step, created_at, completed_at
                ) VALUES (?, ?, ?, ?, 'completed', 100, 'Clips generated successfully!', ?, ?)
                """,
                (seed_job_id, source_url, video_id, len(clips), now_iso, now_iso),
            )

        seed_stats = [
            {"jump_cuts_count": 6, "dead_air_removed_sec": 3.4, "layout_mode": "single_tracked", "segments_count": 1, "dynamic_zooms_count": 3},
            {"jump_cuts_count": 8, "dead_air_removed_sec": 4.1, "layout_mode": "dynamic_zoom", "segments_count": 2, "dynamic_zooms_count": 4},
            {"jump_cuts_count": 5, "dead_air_removed_sec": 2.8, "layout_mode": "single_tracked", "segments_count": 1, "dynamic_zooms_count": 2},
        ]

        seed_social = [
            {
                "youtube_title": "You Can't Connect The Dots Looking Forward #Shorts",
                "youtube_description": "Steve Jobs reveals why you must trust your gut and connect the dots looking backward.\n\n#stevejobs #motivation #shorts #inspiration #mindset",
                "youtube_tags": ["steve jobs", "stanford commencement", "motivation", "wisdom", "mindset"],
                "instagram_caption": "You can't connect the dots looking forward; you can only connect them looking backwards. 🔥\n\nTrust in something—your gut, destiny, life, karma. 👇\n\n#reels #stevejobs #inspiration #mindset #shorts",
                "tiktok_caption": "Connect the dots looking backwards. Trust the journey. #fyp #stevejobs #motivation",
            },
            {
                "youtube_title": "Getting Fired Was The Best Thing That Ever Happened #Shorts",
                "youtube_description": "How getting fired from Apple freed Steve Jobs to enter the most creative period of his life.\n\n#stevejobs #success #shorts #resilience #business",
                "youtube_tags": ["steve jobs", "apple", "business", "resilience", "shorts"],
                "instagram_caption": "The heaviness of being successful was replaced by the lightness of being a beginner again. 💡\n\nSave this for when times get tough! ✨\n\n#reels #entrepreneur #success #mindset #apple",
                "tiktok_caption": "Why getting fired made him a billionaire. #fyp #stevejobs #mindset #business",
            },
            {
                "youtube_title": "Stay Hungry. Stay Foolish. #Shorts",
                "youtube_description": "Steve Jobs delivers his most iconic closing words: Stay Hungry. Stay Foolish.\n\n#stevejobs #stayhungry #shorts #inspiration #graduation",
                "youtube_tags": ["steve jobs", "stay hungry", "stay foolish", "stanford", "inspiration"],
                "instagram_caption": "Your time is limited, so don't waste it living someone else's life. 🚀\n\nStay Hungry. Stay Foolish. 👇\n\n#reels #inspiration #quotes #lifeadvice #shorts",
                "tiktok_caption": "Stay Hungry. Stay Foolish. The greatest graduation speech ever. #fyp #quotes",
            },
        ]

        for i, clip in enumerate(clips):
            clip_idx = i + 1
            clip_record = {
                "id": f"clip-seed-{clip_idx}",
                "clip_index": i,
                "title": clip.get("title", f"Clip #{clip_idx}"),
                "hook_text": clip.get("hook_text", ""),
                "start_time": clip.get("start_time", 0.0),
                "end_time": clip.get("end_time", 0.0),
                "duration": clip.get("final_duration", clip.get("duration", 0.0)),
                "virality_score": clip.get("virality_score", 90),
                "reasoning": clip.get("reasoning", "High retention storytelling hook."),
                "video_url": f"/media/final_clips/clip_{clip_idx}_final.mp4",
                "preview_url": f"/media/previews/clip_{clip_idx}_preview.jpg",
                "subtitles_url": f"/media/subtitles/clip_{clip_idx}.ass",
                "file_size_mb": clip.get("final_file_size_mb", 0.0),
                "edit_stats": seed_stats[i % len(seed_stats)],
                "social_metadata": seed_social[i % len(seed_social)],
            }
            add_clip(seed_job_id, clip_record, db_path=db_path)

        logger.info(f"Successfully seeded database with {len(clips)} clips from {json_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to seed database from phase3_clips.json: {e}", exc_info=True)
        return False
