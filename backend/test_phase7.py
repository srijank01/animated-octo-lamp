"""Comprehensive Test Suite for Phase 7:
Social Media Auto-Publishing, OAuth Account Management,
Multi-Platform Metadata Generation, and Scheduled Upload Queue.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from backend.database import (
    DEFAULT_DB_PATH,
    create_scheduled_post,
    delete_scheduled_post,
    delete_social_account,
    get_all_jobs,
    get_clip,
    get_due_scheduled_posts,
    get_scheduled_post,
    get_scheduled_posts,
    get_social_account,
    get_social_accounts,
    init_db,
    seed_from_phase3_if_empty,
    update_clip_metadata,
    upsert_social_account,
)
from backend.main import app
from backend.pipeline.llm_hooks import SocialMetadata, generate_social_metadata_for_clip
from backend.pipeline.publisher import (
    get_youtube_oauth_url,
    process_due_posts,
    publish_post,
    resolve_video_path,
    upload_to_instagram_reels,
    upload_to_tiktok,
    upload_to_youtube_shorts,
)


def run_tests():
    print("=" * 70)
    print("🚀 STARTING PHASE 7 VERIFICATION TEST SUITE")
    print("=" * 70)

    # 1. Initialize Database and Seed Data
    print("\n[Step 1/7] Initializing SQLite DB and verifying schema...")
    init_db(DEFAULT_DB_PATH)
    seed_from_phase3_if_empty(DEFAULT_DB_PATH)
    print("✓ Database initialized.")

    # 2. Verify Social Accounts CRUD
    print("\n[Step 2/7] Verifying Social Accounts CRUD & seeded accounts...")
    accounts = get_social_accounts(db_path=DEFAULT_DB_PATH)
    print(f"✓ Found {len(accounts)} default/seeded social accounts:")
    for a in accounts:
        print(f"   • [{a['platform'].upper()}] {a['account_name']} (mode: {a['mode']})")

    assert len(accounts) >= 3, "Expected at least 3 seeded accounts (YouTube, Instagram, TikTok)"

    # Test creating custom account
    test_acct = upsert_social_account(
        {
            "platform": "youtube",
            "account_name": "Test Creator Pro",
            "channel_id": "UC_TEST12345",
            "mode": "sandbox",
        },
        db_path=DEFAULT_DB_PATH,
    )
    assert test_acct["account_name"] == "Test Creator Pro"
    assert test_acct["channel_id"] == "UC_TEST12345"
    print("✓ Created custom social account:", test_acct["id"])

    # Test fetching single account
    fetched = get_social_account(test_acct["id"], db_path=DEFAULT_DB_PATH)
    assert fetched is not None
    assert fetched["id"] == test_acct["id"]

    # Test deleting custom account
    deleted_ok = delete_social_account(test_acct["id"], db_path=DEFAULT_DB_PATH)
    assert deleted_ok is True
    assert get_social_account(test_acct["id"], db_path=DEFAULT_DB_PATH) is None
    print("✓ Account deletion verified.")

    # 3. Verify Multi-Platform Social Metadata Schema & Generation
    print("\n[Step 3/7] Verifying Multi-Platform Social Metadata...")
    jobs = get_all_jobs(db_path=DEFAULT_DB_PATH)
    assert len(jobs) > 0, "Expected at least one job"
    first_job = jobs[0]
    assert len(first_job["clips"]) > 0, "Expected at least one clip in first job"
    sample_clip = first_job["clips"][0]

    # Verify existing metadata structure
    meta = sample_clip.get("social_metadata")
    assert meta is not None, "Clip should have social_metadata populated"
    print(f"✓ Clip ID: {sample_clip['id']}")
    print(f"   • YouTube Title: {meta.get('youtube_title')}")
    print(f"   • YouTube Tags: {meta.get('youtube_tags')}")
    print(f"   • Instagram Caption Preview: {meta.get('instagram_caption')[:50]}...")
    print(f"   • TikTok Caption Preview: {meta.get('tiktok_caption')[:50]}...")

    # Test on-demand generation
    print("Testing on-demand metadata regeneration...")
    regen_meta = generate_social_metadata_for_clip(
        sample_clip,
        custom_prompt="Highlight extreme life lessons and courage.",
    )
    assert "youtube_title" in regen_meta
    assert "instagram_caption" in regen_meta
    assert "tiktok_caption" in regen_meta
    print("✓ On-demand metadata generation succeeded:")
    print(f"   • Regenerated Title: {regen_meta['youtube_title']}")

    # Update in DB
    updated_clip = update_clip_metadata(sample_clip["id"], regen_meta, db_path=DEFAULT_DB_PATH)
    assert updated_clip["social_metadata"]["youtube_title"] == regen_meta["youtube_title"]
    print("✓ Updated clip metadata saved to SQLite.")

    # 4. Verify Publishing Engine & Sandbox Dispatchers
    print("\n[Step 4/7] Verifying Direct Platform Uploaders...")
    resolved_video = resolve_video_path(sample_clip["video_url"])
    print(f"✓ Video resolved at: {resolved_video} (exists: {resolved_video.exists()})")
    assert resolved_video.exists(), f"Video file must exist at {resolved_video}"

    # YouTube Shorts Upload
    yt_res = upload_to_youtube_shorts(
        video_path=resolved_video,
        title=regen_meta["youtube_title"],
        description=regen_meta["youtube_description"],
        tags=regen_meta.get("youtube_tags", []),
        privacy_status="public",
    )
    assert yt_res["platform_url"].startswith("https://youtube.com/shorts/")
    print(f"✓ YouTube Shorts simulation succeeded: {yt_res['platform_url']}")

    # Instagram Reels Upload
    ig_res = upload_to_instagram_reels(
        video_path=resolved_video,
        caption=regen_meta["instagram_caption"],
    )
    assert ig_res["platform_url"].startswith("https://instagram.com/reel/")
    print(f"✓ Instagram Reels simulation succeeded: {ig_res['platform_url']}")

    # TikTok Upload
    tt_res = upload_to_tiktok(
        video_path=resolved_video,
        caption=regen_meta["tiktok_caption"],
    )
    assert "tiktok.com" in tt_res["platform_url"]
    print(f"✓ TikTok simulation succeeded: {tt_res['platform_url']}")

    # 5. Verify Scheduled Post Flow & Polling Loop
    print("\n[Step 5/7] Verifying Scheduled Queue Execution...")
    # Create immediate post via publish_post
    post_imm = create_scheduled_post(
        {
            "clip_id": sample_clip["id"],
            "job_id": sample_clip.get("job_id"),
            "platform": "youtube_shorts",
            "title": "Immediate Test Short #Shorts",
            "caption": "Testing immediate post execution",
            "tags": ["Test", "Viral"],
            "privacy_status": "public",
            "status": "scheduled",
        },
        db_path=DEFAULT_DB_PATH,
    )
    published_imm = publish_post(post_imm["id"], db_path=DEFAULT_DB_PATH)
    assert published_imm["status"] == "published"
    assert published_imm["platform_url"] is not None
    assert published_imm["published_at"] is not None
    print(f"✓ Immediate publish_post verified: {published_imm['platform_url']}")

    # Create scheduled post due in 1 second
    due_time = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    post_sched = create_scheduled_post(
        {
            "clip_id": sample_clip["id"],
            "job_id": sample_clip.get("job_id"),
            "platform": "instagram_reels",
            "title": "Scheduled Reels Test",
            "caption": "Wait 1 second for scheduler",
            "scheduled_for": due_time,
            "status": "scheduled",
        },
        db_path=DEFAULT_DB_PATH,
    )
    print(f"✓ Enqueued post {post_sched['id']} scheduled for {due_time}")

    # Immediately check due posts (should be 0 because scheduled_for is in future)
    due_now = get_due_scheduled_posts(db_path=DEFAULT_DB_PATH)
    sched_in_due = [p for p in due_now if p["id"] == post_sched["id"]]
    assert len(sched_in_due) == 0, "Post should not be due yet"

    # Wait 2 seconds so it becomes due
    print("Waiting 2.0s for scheduler tick threshold...")
    time.sleep(2.0)

    # Process due posts
    processed = process_due_posts(db_path=DEFAULT_DB_PATH)
    assert any(p["id"] == post_sched["id"] for p in processed), "Scheduled post was not picked up by process_due_posts"
    post_after = get_scheduled_post(post_sched["id"], db_path=DEFAULT_DB_PATH)
    assert post_after["status"] == "published"
    assert post_after["platform_url"] is not None
    print(f"✓ Auto-publishing queue processed due post: {post_after['platform_url']}")

    # Clean up test scheduled posts
    delete_scheduled_post(post_imm["id"], db_path=DEFAULT_DB_PATH)
    delete_scheduled_post(post_sched["id"], db_path=DEFAULT_DB_PATH)
    print("✓ Scheduled posts cleanup verified.")

    # 6. Verify FastAPI REST Endpoints via TestClient
    print("\n[Step 6/7] Verifying FastAPI Social REST Endpoints...")
    with TestClient(app) as client:
        # GET /api/social/accounts
        r = client.get("/api/social/accounts")
        assert r.status_code == 200
        accts = r.json()
        assert len(accts) >= 3
        print(f"✓ GET /api/social/accounts returned {len(accts)} accounts")

        # POST /api/social/accounts/connect
        r = client.get("/api/social/accounts/oauth-url")
        assert r.status_code == 200
        oauth_data = r.json()
        assert "url" in oauth_data
        print(f"✓ GET /api/social/accounts/oauth-url returned mode: {oauth_data.get('mode')}")

        # POST /api/clips/{id}/generate-metadata
        r = client.post(
            f"/api/clips/{sample_clip['id']}/generate-metadata",
            json={"custom_prompt": "Fast paced energetic style"},
        )
        assert r.status_code == 200
        meta_res = r.json()
        assert meta_res["status"] == "success"
        assert "youtube_title" in meta_res["social_metadata"]
        print(f"✓ POST /api/clips/{sample_clip['id']}/generate-metadata returned valid metadata")

        # POST /api/social/publish (immediate)
        r = client.post(
            "/api/social/publish",
            json={
                "clip_id": sample_clip["id"],
                "platform": "tiktok",
                "title": "REST API Test TikTok Short",
                "caption": "Testing REST upload endpoint #viral",
                "tags": ["test", "api"],
                "privacy_status": "public",
            },
        )
        assert r.status_code == 201
        published_post_data = r.json()
        assert published_post_data["status"] == "published"
        assert "tiktok.com" in published_post_data["platform_url"]
        print(f"✓ POST /api/social/publish (immediate) succeeded: {published_post_data['platform_url']}")

        # POST /api/social/publish (scheduled future)
        future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = client.post(
            "/api/social/publish",
            json={
                "clip_id": sample_clip["id"],
                "platform": "youtube_shorts",
                "title": "REST Scheduled YouTube Short #Shorts",
                "caption": "Scheduled for 2 hours later",
                "scheduled_for": future_iso,
                "privacy_status": "unlisted",
            },
        )
        assert r.status_code == 201
        sched_data = r.json()
        assert sched_data["status"] == "scheduled"
        print(f"✓ POST /api/social/publish (scheduled) enqueued: {sched_data['id']}")

        # GET /api/social/posts
        r = client.get("/api/social/posts")
        assert r.status_code == 200
        all_posts = r.json()
        assert len(all_posts) >= 2
        print(f"✓ GET /api/social/posts returned {len(all_posts)} post records")

        # DELETE /api/social/posts/{id}
        r = client.delete(f"/api/social/posts/{sched_data['id']}")
        assert r.status_code == 200
        print(f"✓ DELETE /api/social/posts/{sched_data['id']} deleted scheduled post")

        # Clean up immediate test post
        client.delete(f"/api/social/posts/{published_post_data['id']}")

    # 7. Backward Compatibility Verification
    print("\n[Step 7/7] Verifying Backward Compatibility (Phases 1-6)...")
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        health = r.json()
        assert health["status"] == "ok"
        assert health["database"] == "connected"
        assert health["total_jobs"] > 0
        print(f"✓ /api/health OK: {health['total_jobs']} jobs, {health['total_clips']} clips")

        r = client.get("/api/jobs")
        assert r.status_code == 200
        jobs_res = r.json()
        assert len(jobs_res) > 0
        assert "edit_stats" in jobs_res[0]["clips"][0]
        assert "social_metadata" in jobs_res[0]["clips"][0]
        print(f"✓ Phase 1-6 Job & Clip contracts intact with edit_stats and social_metadata.")

    print("\n" + "=" * 70)
    print("🎉 ALL PHASE 7 TEST SUITES PASSED FLAWLESSLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()

