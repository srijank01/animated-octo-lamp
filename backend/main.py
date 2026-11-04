"""FastAPI Application for AI Video Clipping System.

Provides RESTful endpoints for:
- Job creation and asynchronous execution
- Real-time job progress polling & status tracking
- Clip catalog retrieval & media streaming
- SQLite database initialization & Phase 3 data seeding
"""

import logging
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure Google OAuth allows http://localhost in local development
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from backend.database import (
    DEFAULT_DB_PATH,
    create_job,
    create_scheduled_post,
    delete_job,
    delete_scheduled_post,
    delete_social_account,
    get_all_jobs,
    get_clip,
    get_db_connection,
    get_job,
    get_scheduled_post,
    get_scheduled_posts,
    get_social_account,
    get_social_accounts,
    init_db,
    seed_from_phase3_if_empty,
    update_clip_metadata,
    upsert_social_account,
)
from backend.pipeline.llm_hooks import generate_social_metadata_for_clip
from backend.pipeline.publisher import (
    exchange_youtube_oauth_code,
    get_youtube_oauth_url,
    publish_post,
    start_scheduler_loop,
    stop_scheduler_loop,
)
from backend.pipeline.transcript import extract_video_id

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("VideoClippingAPI")

BACKEND_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BACKEND_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SQLite database, seed initial verified clips, and start scheduler."""
    logger.info("Initializing database...")
    init_db(DEFAULT_DB_PATH)
    seeded = seed_from_phase3_if_empty(DEFAULT_DB_PATH)
    if seeded:
        logger.info("Database successfully seeded with Phase 3 verified clips.")
    else:
        logger.info("Database already initialized or has active jobs.")

    logger.info("Starting background social upload scheduler loop...")
    start_scheduler_loop(DEFAULT_DB_PATH, interval_seconds=15)

    yield

    logger.info("Stopping background social upload scheduler...")
    stop_scheduler_loop()
    logger.info("Application shutdown.")


app = FastAPI(
    title="AI Video Clipping System API",
    description="Automated short-form viral video clipping, smart face reframing, and dynamic karaoke subtitles.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for open development access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static media mount for generated clips, previews, and subtitles
app.mount("/media", StaticFiles(directory=str(OUTPUT_DIR)), name="media")


# -----------------------------------------------------------------------------
# Request & Response Schemas
# -----------------------------------------------------------------------------
class CreateJobRequest(BaseModel):
    source_url: str = Field(
        ...,
        description="YouTube video URL (e.g., https://www.youtube.com/watch?v=UF8uR6Z6KLc)",
        examples=["https://www.youtube.com/watch?v=UF8uR6Z6KLc"],
    )
    num_clips: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of viral clips to identify and process (1-10)",
    )


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/", tags=["General"])
def root() -> dict[str, str]:
    """Root welcome endpoint with pointers to docs and health status."""
    return {
        "app": "AI Video Clipping System API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "jobs": "/api/jobs",
    }


@app.get("/api/health", tags=["System"])
def health_check() -> dict[str, Any]:
    """Health check endpoint reporting API, database, and system status."""
    try:
        with get_db_connection(DEFAULT_DB_PATH) as conn:
            job_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            clip_count = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = f"unhealthy: {e}"
        job_count = -1
        clip_count = -1

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "app": "AI Video Clipping API",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_status,
        "total_jobs": job_count,
        "total_clips": clip_count,
    }


@app.post("/api/jobs", status_code=status.HTTP_201_CREATED, tags=["Jobs"])
def create_clipping_job(
    request: CreateJobRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Create a new video clipping job and dispatch background processing."""
    # Validate YouTube URL by checking video ID extraction
    try:
        video_id = extract_video_id(request.source_url)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid YouTube URL: {e}",
        )

    # Insert job into SQLite
    job = create_job(
        source_url=request.source_url,
        video_id=video_id,
        num_clips=request.num_clips,
        db_path=DEFAULT_DB_PATH,
    )

    # Dispatch asynchronous pipeline orchestrator
    from backend.orchestrator import run_clipping_job

    background_tasks.add_task(
        run_clipping_job,
        job_id=job["id"],
        source_url=request.source_url,
        num_clips=request.num_clips,
        db_path=DEFAULT_DB_PATH,
    )

    logger.info(f"Dispatched background clipping job {job['id']} for {request.source_url}")
    return job


@app.get("/api/jobs", tags=["Jobs"])
def list_jobs(include_clips: bool = True) -> list[dict[str, Any]]:
    """Retrieve all jobs ordered by creation date descending."""
    return get_all_jobs(include_clips=include_clips, db_path=DEFAULT_DB_PATH)


@app.get("/api/jobs/{job_id}", tags=["Jobs"])
def get_job_by_id(job_id: str) -> dict[str, Any]:
    """Retrieve full status, progress, and generated clips for a specific job."""
    job = get_job(job_id, db_path=DEFAULT_DB_PATH)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found.",
        )
    return job


@app.delete("/api/jobs/{job_id}", tags=["Jobs"])
def delete_job_by_id(job_id: str) -> dict[str, Any]:
    """Delete a job and its associated clips from database and local storage."""
    job = get_job(job_id, db_path=DEFAULT_DB_PATH)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found.",
        )

    deleted = delete_job(job_id, db_path=DEFAULT_DB_PATH)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete job '{job_id}'.",
        )

    # Clean up isolated job directory if present
    job_dir = OUTPUT_DIR / "jobs" / job_id
    if job_dir.exists() and job_dir.is_dir():
        try:
            shutil.rmtree(job_dir)
            logger.info(f"Removed job directory: {job_dir}")
        except Exception as e:
            logger.warning(f"Could not remove directory {job_dir}: {e}")

    return {
        "status": "deleted",
        "job_id": job_id,
        "message": f"Job '{job_id}' and all associated clips were deleted successfully.",
    }


# -----------------------------------------------------------------------------
# Phase 7 Social Publishing Schemas & Endpoints
# -----------------------------------------------------------------------------
class ConnectAccountRequest(BaseModel):
    platform: str = Field(..., description="Platform identifier: 'youtube', 'instagram', or 'tiktok'")
    account_name: str = Field(..., description="Display name / handle of the creator account")
    channel_id: str | None = Field(default=None, description="External platform channel or user ID")
    mode: str = Field(default="sandbox", description="'live_oauth' or 'sandbox'")
    credentials_json: dict[str, Any] | None = Field(default=None, description="Optional OAuth tokens")


class PublishClipRequest(BaseModel):
    clip_id: str = Field(..., description="ID of clip to publish")
    platform: str = Field(default="youtube_shorts", description="'youtube_shorts', 'instagram_reels', or 'tiktok'")
    title: str = Field(..., description="Video title or primary hook header")
    caption: str | None = Field(default="", description="Description or caption with hashtags")
    tags: list[str] = Field(default_factory=list, description="Array of SEO tags")
    privacy_status: str = Field(default="public", description="'public', 'unlisted', or 'private'")
    scheduled_for: str | None = Field(default=None, description="Optional ISO-8601 target upload timestamp")


class GenerateMetadataRequest(BaseModel):
    custom_prompt: str | None = Field(default=None, description="Optional style or focus instructions for Gemini")


class OAuthCallbackRequest(BaseModel):
    code: str = Field(..., description="OAuth authorization code")
    redirect_uri: str = Field(default="http://localhost:3000", description="Redirect URI registered with OAuth client")
    state: str | None = Field(default=None, description="OAuth state parameter containing PKCE session key")
    code_verifier: str | None = Field(default=None, description="PKCE code verifier")


@app.get("/api/social/accounts", tags=["Social Media"])
def list_social_accounts(platform: str | None = None) -> list[dict[str, Any]]:
    """Retrieve all connected social accounts."""
    return get_social_accounts(platform=platform, db_path=DEFAULT_DB_PATH)


@app.post("/api/social/accounts/connect", status_code=status.HTTP_201_CREATED, tags=["Social Media"])
def connect_social_account(request: ConnectAccountRequest) -> dict[str, Any]:
    """Connect a new social account (either sandbox demo or live OAuth)."""
    clean_platform = request.platform.lower().replace(" ", "_")
    account = upsert_social_account(
        {
            "platform": clean_platform,
            "account_name": request.account_name,
            "channel_id": request.channel_id,
            "mode": request.mode,
            "credentials_json": request.credentials_json,
        },
        db_path=DEFAULT_DB_PATH,
    )
    return account


@app.get("/api/social/accounts/oauth-url", tags=["Social Media"])
def get_oauth_url(redirect_uri: str = "http://localhost:8000/api/social/oauth/youtube/callback") -> dict[str, Any]:
    """Get YouTube OAuth 2.0 authorization URL or sandbox fallback."""
    res = get_youtube_oauth_url(redirect_uri=redirect_uri)
    # Ensure both url and auth_url keys are present for frontend flexibility
    if "auth_url" not in res and "url" in res:
        res["auth_url"] = res["url"]
    return res


@app.get("/api/social/oauth/youtube/callback", tags=["Social Media"])
def handle_youtube_oauth_redirect(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    """Handle Google OAuth 2.0 browser redirect callback on FastAPI.
    Exchanges authorization code for tokens, extracts user's real YouTube channel name,
    saves the channel in SQLite with mode='live_oauth' (superseding sandbox),
    and redirects user back to http://localhost:3000/?oauth=youtube_connected.
    """
    if error:
        logger.error(f"Google OAuth authorization error: {error}")
        return RedirectResponse(url=f"http://localhost:3000/?oauth=error&msg={error}")

    if not code:
        logger.error("OAuth callback received without authorization code.")
        return RedirectResponse(url="http://localhost:3000/?oauth=error&msg=missing_code")

    try:
        redirect_uri = "http://localhost:8000/api/social/oauth/youtube/callback"
        token_info = exchange_youtube_oauth_code(
            code=code,
            redirect_uri=redirect_uri,
            state=state,
        )

        # Remove or supersede any existing sandbox YouTube account
        with get_db_connection(DEFAULT_DB_PATH) as conn:
            conn.execute("DELETE FROM social_accounts WHERE platform = 'youtube' AND mode = 'sandbox'")

        # Upsert real Live YouTube Channel
        channel_id = token_info.get("channel_id") or f"UC_{uuid.uuid4().hex[:12]}"
        account_id = f"youtube-{channel_id}"
        account = upsert_social_account(
            {
                "id": account_id,
                "platform": "youtube",
                "account_name": token_info["account_name"],
                "channel_id": channel_id,
                "mode": "live_oauth",
                "credentials_json": token_info.get("credentials_json"),
            },
            db_path=DEFAULT_DB_PATH,
        )
        logger.info(f"Connected live YouTube channel: '{account['account_name']}' ({account['channel_id']})")
        return RedirectResponse(url="http://localhost:3000/?oauth=youtube_connected")
    except Exception as exc:
        logger.error(f"Failed to complete YouTube OAuth callback: {exc}")
        return RedirectResponse(url=f"http://localhost:3000/?oauth=error&msg={type(exc).__name__}")


@app.post("/api/social/accounts/oauth-callback", tags=["Social Media"])
def handle_oauth_callback(request: OAuthCallbackRequest) -> dict[str, Any]:
    """Exchange authorization code and link YouTube account programmatically."""
    token_info = exchange_youtube_oauth_code(
        code=request.code,
        redirect_uri=request.redirect_uri,
        state=request.state,
        code_verifier=request.code_verifier,
    )
    # Remove sandbox account
    with get_db_connection(DEFAULT_DB_PATH) as conn:
        conn.execute("DELETE FROM social_accounts WHERE platform = 'youtube' AND mode = 'sandbox'")

    channel_id = token_info.get("channel_id") or f"UC_{uuid.uuid4().hex[:12]}"
    account = upsert_social_account(
        {
            "id": f"youtube-{channel_id}",
            "platform": "youtube",
            "account_name": token_info["account_name"],
            "channel_id": channel_id,
            "mode": token_info.get("mode", "live_oauth"),
            "credentials_json": token_info.get("credentials_json"),
        },
        db_path=DEFAULT_DB_PATH,
    )
    return account


@app.delete("/api/social/accounts/{account_id}", tags=["Social Media"])
def disconnect_social_account(account_id: str) -> dict[str, Any]:
    """Disconnect and remove a social account."""
    acct = get_social_account(account_id, db_path=DEFAULT_DB_PATH)
    if not acct:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Account '{account_id}' not found.")
    delete_social_account(account_id, db_path=DEFAULT_DB_PATH)
    return {"status": "deleted", "account_id": account_id}


@app.post("/api/clips/{clip_id}/generate-metadata", tags=["Social Media"])
def generate_metadata_endpoint(clip_id: str, request: GenerateMetadataRequest) -> dict[str, Any]:
    """Generate or refresh multi-platform social metadata for a clip using Gemini."""
    clip = get_clip(clip_id, db_path=DEFAULT_DB_PATH)
    if not clip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Clip '{clip_id}' not found.")

    new_meta = generate_social_metadata_for_clip(clip, custom_prompt=request.custom_prompt)
    updated_clip = update_clip_metadata(clip_id, new_meta, db_path=DEFAULT_DB_PATH)
    return {
        "status": "success",
        "clip_id": clip_id,
        "social_metadata": new_meta,
        "clip": updated_clip,
    }


@app.post("/api/social/publish", status_code=status.HTTP_201_CREATED, tags=["Social Media"])
def publish_or_schedule_clip(request: PublishClipRequest) -> dict[str, Any]:
    """Publish a clip immediately or enqueue it in the scheduled queue."""
    clip = get_clip(request.clip_id, db_path=DEFAULT_DB_PATH)
    if not clip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Clip '{request.clip_id}' not found.")

    # Determine if scheduled or immediate
    is_immediate = True
    if request.scheduled_for:
        try:
            target_dt = datetime.fromisoformat(request.scheduled_for.replace("Z", "+00:00"))
            if target_dt > datetime.now(timezone.utc):
                is_immediate = False
        except Exception:
            is_immediate = True

    post_record = create_scheduled_post(
        {
            "clip_id": request.clip_id,
            "job_id": clip.get("job_id"),
            "platform": request.platform,
            "title": request.title,
            "caption": request.caption or "",
            "tags": request.tags,
            "privacy_status": request.privacy_status,
            "scheduled_for": request.scheduled_for if not is_immediate else None,
            "status": "scheduled",
        },
        db_path=DEFAULT_DB_PATH,
    )

    if is_immediate:
        try:
            published = publish_post(post_record["id"], db_path=DEFAULT_DB_PATH)
            return published
        except Exception as exc:
            logger.error(f"Immediate publish error: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to publish clip to {request.platform}: {exc}",
            )

    return post_record


@app.get("/api/social/posts", tags=["Social Media"])
def list_scheduled_posts(
    clip_id: str | None = None,
    job_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve all posts from the social upload queue."""
    return get_scheduled_posts(clip_id=clip_id, job_id=job_id, status=status, db_path=DEFAULT_DB_PATH)


@app.get("/api/social/posts/{post_id}", tags=["Social Media"])
def get_post_by_id(post_id: str) -> dict[str, Any]:
    """Retrieve a single post status."""
    post = get_scheduled_post(post_id, db_path=DEFAULT_DB_PATH)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Post '{post_id}' not found.")
    return post


@app.delete("/api/social/posts/{post_id}", tags=["Social Media"])
def cancel_or_delete_post(post_id: str) -> dict[str, Any]:
    """Cancel or delete a post record."""
    deleted = delete_scheduled_post(post_id, db_path=DEFAULT_DB_PATH)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Post '{post_id}' not found.")
    return {"status": "deleted", "post_id": post_id}


