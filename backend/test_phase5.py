"""Phase 5 Integration Verification Test Suite.

Verifies:
1. FastAPI backend running on port 8000
2. Next.js Studio frontend running on port 3000
3. CORS header validation between frontend (origin: http://localhost:3000) and backend (http://localhost:8000)
4. Frontend HTML loads with critical Studio elements
5. Backend media endpoints stream video and thumbnail assets correctly
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

BACKEND_PORT = 8000
FRONTEND_PORT = 3000


def main():
    print("=" * 80)
    print("  AI VIDEO CLIPPING SYSTEM - PHASE 5 FULL INTEGRATION TEST")
    print("  FastAPI Backend (8000) + Next.js Studio Dashboard (3000)")
    print("=" * 80)

    # 1. Start FastAPI backend on port 8000
    print(f"\n[1/5] Launching FastAPI backend on http://127.0.0.1:{BACKEND_PORT}...")
    backend_proc = subprocess.Popen(
        [
            str(BACKEND_DIR / "venv" / "bin" / "uvicorn"),
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 2. Start Next.js on port 3000
    print(f"[2/5] Launching Next.js server on http://127.0.0.1:{FRONTEND_PORT}...")
    frontend_proc = subprocess.Popen(
        ["npm", "run", "start", "--", "-p", str(FRONTEND_PORT)],
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for backend to be ready
        backend_ready = False
        for _ in range(25):
            try:
                r = httpx.get(f"http://127.0.0.1:{BACKEND_PORT}/api/health", timeout=1.0)
                if r.status_code == 200:
                    backend_ready = True
                    break
            except Exception:
                time.sleep(0.3)
        assert backend_ready, "FastAPI backend failed to start on port 8000"
        print(f"✓ FastAPI backend online (Health: {r.json()})")

        # Wait for frontend to be ready
        frontend_ready = False
        for _ in range(30):
            try:
                r_fe = httpx.get(f"http://127.0.0.1:{FRONTEND_PORT}", timeout=1.5)
                if r_fe.status_code == 200:
                    frontend_ready = True
                    break
            except Exception:
                time.sleep(0.3)
        assert frontend_ready, "Next.js frontend failed to start on port 3000"
        print(f"✓ Next.js Studio frontend online (Status: {r_fe.status_code})")

        # 3. Test CORS Headers
        print("\n[3/5] Testing CORS headers between Frontend and Backend...")
        cors_req = httpx.options(
            f"http://127.0.0.1:{BACKEND_PORT}/api/jobs",
            headers={
                "Origin": f"http://localhost:{FRONTEND_PORT}",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        print(f"  OPTIONS /api/jobs -> status {cors_req.status_code}")
        allow_origin = cors_req.headers.get("access-control-allow-origin")
        print(f"  Access-Control-Allow-Origin: {allow_origin}")
        assert allow_origin in ["*", f"http://localhost:{FRONTEND_PORT}"], f"Invalid CORS origin: {allow_origin}"
        print("✓ CORS validation passed: Frontend can communicate with Backend!")

        # 4. Test Frontend HTML Content
        print("\n[4/5] Inspecting Frontend rendered HTML...")
        html = r_fe.text
        assert "AutoClip" in html or "Viral" in html, "Brand title missing in frontend HTML"
        assert "Steve Jobs" in html or "Demo" in html or "Viral Shorts" in html, "Studio elements missing in HTML"
        print("✓ Frontend page rendered successfully with branding and studio elements.")

        # 5. Test Media Assets & Streaming
        print("\n[5/5] Testing Media Streaming & Seed Data Availability...")
        jobs_res = httpx.get(f"http://127.0.0.1:{BACKEND_PORT}/api/jobs")
        assert jobs_res.status_code == 200
        jobs = jobs_res.json()
        assert len(jobs) >= 1, "No jobs found in backend"
        seed_job = next((j for j in jobs if j["id"] == "seed-stanford-jobs-2005"), jobs[0])
        assert len(seed_job["clips"]) == 3, f"Expected 3 clips, got {len(seed_job['clips'])}"
        print(f"✓ Seed Job Loaded: {seed_job['id']} with {len(seed_job['clips'])} clips")

        for idx, clip in enumerate(seed_job["clips"]):
            clip_video_url = f"http://127.0.0.1:{BACKEND_PORT}{clip['video_url']}"
            clip_prev_url = f"http://127.0.0.1:{BACKEND_PORT}{clip['preview_url']}"

            # Stream video range
            with httpx.stream("GET", clip_video_url) as stream:
                assert stream.status_code == 200
                first_chunk = next(stream.iter_bytes(chunk_size=16384))
                assert len(first_chunk) > 0

            # Get preview image
            img_res = httpx.get(clip_prev_url)
            assert img_res.status_code == 200
            assert len(img_res.content) > 5000

            print(f"  - Clip {idx+1}: '{clip['title']}' | Score: {clip['virality_score']}/100 | Video & Preview 200 OK")

        print("\n" + "=" * 80)
        print("  🎉 PHASE 5 INTEGRATION TEST PASSED CLEANLY! BOTH SERVERS VERIFIED!")
        print("=" * 80)

    finally:
        print("\nTerminating background test servers...")
        backend_proc.terminate()
        frontend_proc.terminate()
        try:
            backend_proc.wait(timeout=3)
            frontend_proc.wait(timeout=3)
        except Exception:
            backend_proc.kill()
            frontend_proc.kill()
        print("✓ All test servers stopped.")


if __name__ == "__main__":
    main()

