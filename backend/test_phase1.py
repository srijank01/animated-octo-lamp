#!/usr/bin/env python3
"""CLI Verification Script for Phase 1: AI Video Clipping System.

Usage:
    python backend/test_phase1.py
    python backend/test_phase1.py --url "https://www.youtube.com/watch?v=UF8uR6Z6KLc"
    python backend/test_phase1.py --transcript-only
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

# Load backend/.env
env_file = BACKEND_DIR / ".env"
load_dotenv(dotenv_path=env_file)

from pipeline.transcript import (
    extract_video_id,
    get_transcript,
    format_transcript_for_llm,
)
from pipeline.llm_hooks import find_viral_clips

DEFAULT_YOUTUBE_URL = "https://www.youtube.com/watch?v=UF8uR6Z6KLc"  # Steve Jobs Stanford Commencement 2005


def check_api_key_status() -> bool:
    """Check whether a valid Gemini API key is configured."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return bool(key and key != "your_key_here" and key != "your_gemini_api_key_here")


def run_phase1_pipeline(
    url: str,
    num_clips: int = 3,
    transcript_only: bool = False,
    output_path: Path | None = None,
) -> None:
    print("=" * 70)
    print("  AI VIDEO CLIPPING SYSTEM - PHASE 1 VERIFICATION")
    print("=" * 70)

    # Step 1: Video ID Extraction
    print(f"\n[1/4] Processing Target Video...")
    print(f"      URL: {url}")
    try:
        video_id = extract_video_id(url)
        print(f"      Extracted Video ID: {video_id}")
    except Exception as e:
        print(f"      [ERROR] Failed to extract video ID: {e}")
        sys.exit(1)

    # Step 2: Transcript Extraction
    print(f"\n[2/4] Extracting Transcript (Zero-Download)...")
    try:
        segments = get_transcript(video_id)
        formatted_text = format_transcript_for_llm(segments)
        char_count = len(formatted_text)
        print(f"      [SUCCESS] Extracted {len(segments)} segments ({char_count:,} characters).")
        
        print("\n      --- Transcript Preview (First 5 lines) ---")
        preview_lines = formatted_text.strip().split("\n")[:5]
        for line in preview_lines:
            print(f"      {line}")
        print("      -----------------------------------------\n")

    except Exception as e:
        print(f"      [ERROR] Failed to extract transcript: {e}")
        sys.exit(1)

    if transcript_only:
        print("[INFO] --transcript-only flag specified. Skipping Gemini hook selection.")
        return

    # Step 3: Check API Key
    print(f"[3/4] Checking Gemini API Authentication...")
    if not check_api_key_status():
        print(
            "\n[WARNING] GEMINI_API_KEY is missing or contains placeholder text!\n"
            f"Please edit '{env_file}' and set your key:\n"
            "GEMINI_API_KEY=AIzaSy...\n"
        )
        sys.exit(1)

    print("      [SUCCESS] GEMINI_API_KEY detected.")

    # Step 4: Viral Clip Selection via Gemini
    print(f"\n[4/4] Running Gemini Viral Hook Selection (Top {num_clips} clips)...")
    try:
        selection_response = find_viral_clips(
            transcript_text=formatted_text,
            num_clips=num_clips,
        )
        clips = selection_response.clips
        print(f"      [SUCCESS] Gemini selected {len(clips)} viral clips!\n")

        print("=" * 70)
        print("  SELECTED VIRAL CLIPS")
        print("=" * 70)

        for idx, clip in enumerate(clips, 1):
            print(f"\nClip #{idx}:")
            print(f"  Title:          {clip.title}")
            print(f"  Hook Text:      \"{clip.hook_text}\"")
            print(f"  Timestamps:     {clip.start_time:.1f}s - {clip.end_time:.1f}s")
            print(f"  Duration:       {clip.duration:.1f}s")
            print(f"  Virality Score: {clip.virality_score}/100")
            print(f"  Reasoning:      {clip.reasoning}")

        # Step 5: Save JSON for Phase 2
        if output_path is None:
            output_dir = BACKEND_DIR / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "phase1_clips.json"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "video_id": video_id,
            "source_url": url,
            "clips": [clip.model_dump() for clip in clips],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        print("\n" + "=" * 70)
        print(f"  [SAVED] Output written to: {output_path}")
        print("=" * 70 + "\n")

    except Exception as e:
        print(f"      [ERROR] Gemini clip selection failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Phase 1 Verification: Transcript Extraction & Viral Hook Selection"
    )
    parser.add_argument(
        "--url",
        type=str,
        default=DEFAULT_YOUTUBE_URL,
        help=f"YouTube video URL or ID (default: {DEFAULT_YOUTUBE_URL})",
    )
    parser.add_argument(
        "--num-clips",
        type=int,
        default=3,
        help="Number of viral clips to select (default: 3)",
    )
    parser.add_argument(
        "--transcript-only",
        action="store_true",
        help="Verify only the transcript extraction step",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom output path for phase1_clips.json",
    )

    args = parser.parse_args()
    output_path = Path(args.output) if args.output else None

    run_phase1_pipeline(
        url=args.url,
        num_clips=args.num_clips,
        transcript_only=args.transcript_only,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()

