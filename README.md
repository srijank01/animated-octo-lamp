# AutoClip AI — Automated Viral Video Clipping System

AutoClip AI is an automated short-form video generation system (inspired by OpusClip & Alex Hormozi style shorts). It transforms any YouTube video into high-retention 9:16 vertical shorts with smart active-speaker reframing and burned dynamic karaoke subtitles.

---

## Key Features

1. **Zero Full-Video Downloads**:
   - Fetches subtitles via `youtube-transcript-api` (with automatic fallback to `yt-dlp`).
   - Slices only the selected 30–60s segments using `yt-dlp --download-sections`.

2. **Gemini Viral Hook Selection**:
   - Uses `gemini-3.5-flash-lite` / `gemini-3.5-flash` with structured Pydantic JSON output.
   - Scores clips from 1–100 based on storytelling, tension, and opening 3-second hook strength.

3. **Active Speaker 9:16 Reframing**:
   - Real-time face detection using OpenCV Haar cascades with exponential moving average (EMA) smoothing and a 3% deadband filter to eliminate camera jitter.
   - Reframes 16:9 landscape video into 1080x1920 vertical video.

4. **Dynamic Karaoke Captions**:
   - Word-level audio timestamping using `faster-whisper`.
   - Generates `.ass` subtitle files formatted in 3–5 word punchy chunks with lower-third safe zones (`MarginV: 420`).
   - Highlighting active words in Viral Gold (`#FFD700`) with pop-in scale animation (`\fscx108\fscy108`) burned via FFmpeg `libass`.

5. **FastAPI + SQLite Persistence & Orchestrator**:
   - Thread-safe SQLite database (`jobs.db`) managing job queues and generated clips.
   - Asynchronous background worker orchestrating pipeline execution.
   - Automatic seeding of verified demo clips.

6. **Next.js Studio Dashboard**:
   - Dark-mode dashboard built with Next.js 16 (App Router), TypeScript, and Tailwind CSS.
   - Interactive 9:16 vertical video player mockups.
   - Real-time job polling with animated progress bars.
   - Direct MP4 and subtitle download buttons.

---

## Quick Start

### 1. Requirements
- macOS or Linux
- Python 3.10+ (tested on Python 3.14)
- Node.js 18+ & npm
- FFmpeg (with `libass` support, e.g. via Homebrew: `brew install ffmpeg`)
- Gemini API Key in `backend/.env`:
  ```bash
  GEMINI_API_KEY=your_gemini_api_key_here
  ```

### 2. Run Both Servers (Single Command)
Run the root startup script to launch the FastAPI backend (`http://localhost:8000`) and Next.js frontend (`http://localhost:3000`):
```bash
./run_dev.sh
```

### 3. Run Manually

**Terminal 1 — Backend (FastAPI):**
```bash
cd backend
source venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend (Next.js):**
```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## API Documentation

FastAPI provides an interactive Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs).

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Service health, DB connectivity, and clip counts |
| `POST` | `/api/jobs` | Enqueue a new video clipping job (`{ source_url, num_clips }`) |
| `GET` | `/api/jobs` | List all historical and active jobs |
| `GET` | `/api/jobs/{id}` | Real-time status, progress, and clips for a job |
| `DELETE` | `/api/jobs/{id}` | Delete job and local files |
| `GET` | `/media/...` | Static video, thumbnail, and subtitle file streaming |

---

## Verification Test Suites

Each phase includes a standalone verification script:
```bash
# Phase 1: Transcript & Gemini Hooks
backend/venv/bin/python backend/test_phase1.py

# Phase 2: Stream Slicing & 9:16 Face Reframing
backend/venv/bin/python backend/test_phase2.py

# Phase 3: Word Timestamps & Dynamic Karaoke Burn-In
backend/venv/bin/python backend/test_phase3.py

# Phase 4: SQLite Database & FastAPI API Endpoints
backend/venv/bin/python backend/test_phase4.py

# Phase 5: Full End-to-End Frontend + Backend Integration
backend/venv/bin/python backend/test_phase5.py
```

