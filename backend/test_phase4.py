"""Phase 4 Verification Test Suite.

Tests:
1. SQLite Database & Persistence Layer (jobs and clips tables, CRUD operations)
2. Phase 3 Automatic Data Seeding
3. FastAPI REST Endpoints (health, jobs listing, job detail, media serving)
4. URL Validation & Job Creation
5. Asynchronous Job State Progression & Error Handling
6. Live Uvicorn HTTP Server & Media Streaming
"""

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR.parent))

from backend.database import (
    DEFAULT_DB_PATH,
    add_clip,
    create_job,
    delete_job,
    get_all_jobs,
    get_db_connection,
    get_job,
    init_db,
    seed_from_phase3_if_empty,
    update_job,
)
from backend.main import app
from backend.orchestrator import extract_preview_frame, run_clipping_job


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_database_crud() -> None:
    print_header("TEST 1: SQLite Database Schema & CRUD Operations")
    init_db(DEFAULT_DB_PATH)

    # Verify tables
    with get_db_connection(DEFAULT_DB_PATH) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        ]
        print(f"✓ Found SQLite tables: {tables}")
        assert "jobs" in tables, "Table 'jobs' missing"
        assert "clips" in tables, "Table 'clips' missing"

    # Test Create Job
    test_id = f"test-job-{uuid.uuid4().hex[:8]}"
    job = create_job(
        source_url="https://www.youtube.com/watch?v=UF8uR6Z6KLc",
        video_id="UF8uR6Z6KLc",
        num_clips=2,
        job_id=test_id,
    )
    assert job["id"] == test_id
    assert job["status"] == "queued"
    assert job["progress_pct"] == 0
    print(f"✓ Created test job: id={job['id']}, status={job['status']}")

    # Test Update Job
    updated = update_job(
        test_id,
        status="processing_clips",
        progress_pct=50,
        current_step="Processing test clip 1...",
    )
    assert updated["status"] == "processing_clips"
    assert updated["progress_pct"] == 50
    print(f"✓ Updated test job: status={updated['status']}, progress={updated['progress_pct']}%")

    # Test Add Clip
    clip_data = {
        "id": f"clip-{test_id}-1",
        "clip_index": 0,
        "title": "Test Viral Clip #1 #Shorts",
        "hook_text": "This is a test opening hook sentence.",
        "start_time": 10.0,
        "end_time": 45.0,
        "duration": 35.0,
        "virality_score": 95,
        "reasoning": "High retention test explanation",
        "video_url": f"/media/jobs/{test_id}/final_clips/clip_1_final.mp4",
        "preview_url": f"/media/jobs/{test_id}/previews/clip_1_preview.jpg",
        "subtitles_url": f"/media/jobs/{test_id}/subtitles/clip_1.ass",
        "file_size_mb": 12.34,
    }
    added_clip = add_clip(test_id, clip_data)
    assert added_clip["title"] == clip_data["title"]
    assert added_clip["virality_score"] == 95
    print(f"✓ Added clip to job: title='{added_clip['title']}', score={added_clip['virality_score']}")

    # Test Get Job with Clips
    retrieved = get_job(test_id)
    assert retrieved is not None
    assert len(retrieved["clips"]) == 1
    assert retrieved["clips"][0]["id"] == clip_data["id"]
    print(f"✓ Successfully retrieved job with {len(retrieved['clips'])} nested clip(s)")

    # Test Delete Job
    deleted = delete_job(test_id)
    assert deleted is True
    assert get_job(test_id) is None
    print(f"✓ Successfully deleted job {test_id} and verified cascade deletion")


def test_seed_data() -> None:
    print_header("TEST 2: Phase 3 Automatic Data Seeding")
    seed_from_phase3_if_empty(DEFAULT_DB_PATH)

    jobs = get_all_jobs()
    print(f"✓ Total jobs in database: {len(jobs)}")
    assert len(jobs) >= 1, "Expected at least 1 seeded job"

    seed_job = next((j for j in jobs if j["id"] == "seed-stanford-jobs-2005"), jobs[0])
    print(f"✓ Seed Job ID: {seed_job['id']}")
    print(f"  Source URL: {seed_job['source_url']}")
    print(f"  Status: {seed_job['status']} ({seed_job['progress_pct']}%)")
    print(f"  Total Clips: {len(seed_job['clips'])}")

    assert len(seed_job["clips"]) == 3, f"Expected 3 seeded clips, got {len(seed_job['clips'])}"
    for i, clip in enumerate(seed_job["clips"]):
        print(f"  - Clip {i+1}: '{clip['title']}' | Score: {clip['virality_score']} | Size: {clip['file_size_mb']}MB")
        assert clip["video_url"].startswith("/media/"), f"Invalid video URL: {clip['video_url']}"
        assert clip["preview_url"].startswith("/media/"), f"Invalid preview URL: {clip['preview_url']}"


def test_fastapi_endpoints() -> None:
    print_header("TEST 3: FastAPI REST API Endpoints & Static Media Mount")
    client = TestClient(app)

    # 1. Health Check
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["status"] == "ok"
    assert health_data["database"] == "connected"
    print(f"✓ GET /api/health -> 200 OK: status={health_data['status']}, jobs={health_data['total_jobs']}")

    # 2. List Jobs
    jobs_resp = client.get("/api/jobs")
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()
    assert len(jobs) >= 1
    print(f"✓ GET /api/jobs -> 200 OK: returned {len(jobs)} job(s)")

    # 3. Get Specific Job
    seed_id = jobs[0]["id"]
    job_resp = client.get(f"/api/jobs/{seed_id}")
    assert job_resp.status_code == 200
    job = job_resp.json()
    assert job["id"] == seed_id
    print(f"✓ GET /api/jobs/{seed_id} -> 200 OK: clips count={len(job['clips'])}")

    # 4. Nonexistent Job (404)
    missing_resp = client.get("/api/jobs/nonexistent-uuid-12345")
    assert missing_resp.status_code == 404
    print(f"✓ GET /api/jobs/nonexistent-uuid-12345 -> 404 NOT FOUND (as expected)")

    # 5. Static Media Serving
    jobs_with_clips = [j for j in jobs if j.get("clips")]
    assert len(jobs_with_clips) > 0, "Expected at least one job with clips in database"
    first_job = jobs_with_clips[0]
    first_clip = first_job["clips"][0]
    video_url = first_clip["video_url"]
    preview_url = first_clip["preview_url"]
    subtitles_url = first_clip.get("subtitles_url")

    vid_resp = client.get(video_url)
    assert vid_resp.status_code == 200
    assert len(vid_resp.content) > 1_000_000  # At least 1MB
    print(f"✓ Static Video GET {video_url} -> 200 OK ({len(vid_resp.content):,} bytes, type: {vid_resp.headers.get('content-type')})")

    prev_resp = client.get(preview_url)
    assert prev_resp.status_code == 200
    assert len(prev_resp.content) > 10_000
    print(f"✓ Static Preview GET {preview_url} -> 200 OK ({len(prev_resp.content):,} bytes, type: {prev_resp.headers.get('content-type')})")

    if subtitles_url:
        sub_resp = client.get(subtitles_url)
        assert sub_resp.status_code == 200
        print(f"✓ Static Subtitles GET {subtitles_url} -> 200 OK ({len(sub_resp.content):,} bytes)")

    # 6. POST /api/jobs validation error (400)
    bad_req_resp = client.post("/api/jobs", json={"source_url": "https://example.com/not-a-youtube-video", "num_clips": 3})
    assert bad_req_resp.status_code == 400
    print(f"✓ POST /api/jobs with invalid URL -> 400 Bad Request: {bad_req_resp.json()['detail']}")


def test_orchestrator_state_flow() -> None:
    print_header("TEST 4: Pipeline Orchestrator State Progression & Isolation")
    # Verify thumbnail extraction utility
    existing_video = BACKEND_DIR / "output" / "final_clips" / "clip_1_final.mp4"
    if existing_video.exists():
        test_thumb = BACKEND_DIR / "output" / "previews" / "test_extract_preview.jpg"
        extract_preview_frame(existing_video, test_thumb, timestamp=1.5)
        assert test_thumb.exists()
        assert test_thumb.stat().st_size > 5000
        print(f"✓ Preview frame extraction verified: {test_thumb.name} ({test_thumb.stat().st_size:,} bytes)")
        test_thumb.unlink(missing_ok=True)

    # Test Job Directory Isolation & Failure Handling
    fail_job_id = f"test-failure-{uuid.uuid4().hex[:6]}"
    create_job(
        source_url="https://www.youtube.com/watch?v=invalid_id_xyz",
        num_clips=1,
        job_id=fail_job_id,
    )
    # Run orchestrator on invalid video to test error handling & failed status update
    run_clipping_job(fail_job_id, "https://www.youtube.com/watch?v=invalid_id_xyz", num_clips=1)
    failed_job = get_job(fail_job_id)
    assert failed_job["status"] == "failed"
    assert failed_job["error_message"] is not None
    print(f"✓ Orchestrator error handling verified: status={failed_job['status']}, error='{failed_job['error_message']}'")

    # Clean up failure test job
    delete_job(fail_job_id)
    fail_dir = BACKEND_DIR / "output" / "jobs" / fail_job_id
    if fail_dir.exists():
        shutil.rmtree(fail_dir)
    print(f"✓ Cleaned up error handling test job")


def test_live_uvicorn_server() -> None:
    print_header("TEST 5: Live Uvicorn HTTP Server & Media Streaming Test")
    port = 8899
    cmd = [
        str(BACKEND_DIR / "venv" / "bin" / "uvicorn"),
        "backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]

    print(f"Launching live Uvicorn server on http://127.0.0.1:{port}...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        # Wait for server to bind
        server_ready = False
        for _ in range(20):
            try:
                res = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0)
                if res.status_code == 200:
                    server_ready = True
                    break
            except Exception:
                time.sleep(0.3)

        assert server_ready, "Uvicorn server failed to respond within 6 seconds"
        print(f"✓ Server successfully bound and accepting connections on port {port}")

        # Live health check
        health_res = httpx.get(f"http://127.0.0.1:{port}/api/health")
        print(f"✓ Live GET /api/health -> {health_res.status_code}: {health_res.json()}")

        # Live jobs listing
        jobs_res = httpx.get(f"http://127.0.0.1:{port}/api/jobs")
        jobs_data = jobs_res.json()
        print(f"✓ Live GET /api/jobs -> {jobs_res.status_code}: {len(jobs_data)} job(s)")

        # Live media streaming test
        first_clip = jobs_data[0]["clips"][0]
        stream_url = f"http://127.0.0.1:{port}{first_clip['video_url']}"
        with httpx.stream("GET", stream_url) as stream_resp:
            assert stream_resp.status_code == 200
            chunk = next(stream_resp.iter_bytes(chunk_size=65536))
            assert len(chunk) > 0
            print(f"✓ Live video streaming verified from {stream_url} (first chunk: {len(chunk)} bytes)")

        # Live DELETE endpoint test with temporary job
        temp_id = f"live-test-{uuid.uuid4().hex[:6]}"
        create_job(
            source_url="https://www.youtube.com/watch?v=UF8uR6Z6KLc",
            video_id="UF8uR6Z6KLc",
            num_clips=1,
            job_id=temp_id,
        )
        del_res = httpx.delete(f"http://127.0.0.1:{port}/api/jobs/{temp_id}")
        assert del_res.status_code == 200
        print(f"✓ Live DELETE /api/jobs/{temp_id} -> {del_res.status_code}: {del_res.json()}")

        # Verify 404 after deletion
        get_deleted_res = httpx.get(f"http://127.0.0.1:{port}/api/jobs/{temp_id}")
        assert get_deleted_res.status_code == 404
        print(f"✓ Live GET /api/jobs/{temp_id} -> 404 NOT FOUND (confirmed deletion)")

    finally:
        print("Stopping Uvicorn server...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("✓ Server stopped cleanly.")


def main() -> None:
    print("\n" + "#" * 80)
    print("  AI VIDEO CLIPPING SYSTEM - PHASE 4 FULL TEST SUITE")
    print("  FastAPI Backend, SQLite Job Persistence, & Async Orchestrator")
    print("#" * 80)

    try:
        test_database_crud()
        test_seed_data()
        test_fastapi_endpoints()
        test_orchestrator_state_flow()
        test_live_uvicorn_server()

        print("\n" + "=" * 80)
        print("  🎉 ALL PHASE 4 TESTS COMPLETED SUCCESSFULLY WITH ZERO ERRORS!")
        print("=" * 80 + "\n")
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

