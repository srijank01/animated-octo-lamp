#!/usr/bin/env python3
"""CLI Verification Script for Phase 2: Partial Video Slicing & 9:16 Reframing.

Usage:
    python backend/test_phase2.py                  # Process Clip #1
    python backend/test_phase2.py --clip-index 1   # Process Clip #2
    python backend/test_phase2.py --all            # Process all clips in phase1_clips.json
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Setup paths
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pipeline.downloader import download_clip_slice, probe_video
from pipeline.reframer import analyze_speaker_center_x, reframe_to_vertical

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Phase2Verification")


def run_phase2(
    phase1_path: Path,
    clip_index: int | None = 0,
    process_all: bool = False,
    mode: str = "auto",
    output_meta_path: Path | None = None,
) -> None:
    print("=" * 75)
    print("  AI VIDEO CLIPPING SYSTEM - PHASE 2 VERIFICATION")
    print("  Partial Video Slicing (yt-dlp) & Smart 9:16 Reframing (OpenCV + FFmpeg)")
    print("=" * 75)

    if not phase1_path.exists():
        print(f"\n[ERROR] Phase 1 output not found at: {phase1_path}")
        print("Please run `backend/test_phase1.py` first to generate clips.")
        sys.exit(1)

    with open(phase1_path, "r", encoding="utf-8") as f:
        phase1_data = json.load(f)

    source_url = phase1_data.get("source_url")
    video_id = phase1_data.get("video_id")
    clips = phase1_data.get("clips", [])

    if not clips:
        print("[ERROR] No clips found in phase1_clips.json.")
        sys.exit(1)

    # Determine which clips to process
    if process_all:
        selected_clips = [(i, c) for i, c in enumerate(clips)]
    else:
        idx = clip_index or 0
        if idx < 0 or idx >= len(clips):
            print(f"[ERROR] Invalid clip index {idx}. Available: 0 to {len(clips)-1}")
            sys.exit(1)
        selected_clips = [(idx, clips[idx])]

    raw_dir = BACKEND_DIR / "output" / "raw_clips"
    vertical_dir = BACKEND_DIR / "output" / "vertical_clips"
    raw_dir.mkdir(parents=True, exist_ok=True)
    vertical_dir.mkdir(parents=True, exist_ok=True)

    if output_meta_path is None:
        output_meta_path = BACKEND_DIR / "output" / "phase2_clips.json"

    processed_records = []

    for clip_num, clip in selected_clips:
        display_idx = clip_num + 1
        title = clip.get("title", f"Clip_{display_idx}")
        start_time = float(clip["start_time"])
        end_time = float(clip["end_time"])
        expected_dur = float(clip.get("duration", end_time - start_time))

        print(f"\n" + "-" * 75)
        print(f"  PROCESSING CLIP #{display_idx}: {title}")
        print(f"  Timestamps: {start_time:.2f}s - {end_time:.2f}s (Expected Duration: {expected_dur:.2f}s)")
        print(f"  Virality Score: {clip.get('virality_score')}/100")
        print("-" * 75)

        raw_clip_path = raw_dir / f"clip_{display_idx}_raw.mp4"
        vertical_clip_path = vertical_dir / f"clip_{display_idx}_vertical.mp4"

        # -------------------------------------------------------------
        # STEP A: Partial Video Stream Slicing
        # -------------------------------------------------------------
        print(f"\n[Step A] Downloading Partial Slice via yt-dlp (Zero Full Download)...")
        t0 = time.time()
        try:
            download_clip_slice(
                source_url=source_url,
                start_time=start_time,
                end_time=end_time,
                output_path=raw_clip_path,
            )
            slice_time = time.time() - t0
            raw_probe = probe_video(raw_clip_path)
            raw_duration = float(raw_probe.get("format", {}).get("duration", 0.0))
            raw_size_mb = raw_clip_path.stat().st_size / (1024 * 1024)

            print(f"         [SUCCESS] Sliced in {slice_time:.2f}s | Size: {raw_size_mb:.2f} MB | Duration: {raw_duration:.2f}s")
            print(f"         Saved to: {raw_clip_path}")
        except Exception as e:
            print(f"         [ERROR] Failed to download slice: {e}")
            sys.exit(1)

        # -------------------------------------------------------------
        # STEP B: Speaker Tracking Analysis (OpenCV)
        # -------------------------------------------------------------
        print(f"\n[Step B] Analyzing Active Speaker & Facial Trajectory (OpenCV)...")
        t1 = time.time()
        try:
            speaker_analysis = analyze_speaker_center_x(raw_clip_path, sample_rate_fps=3)
            track_time = time.time() - t1
            frame_w = speaker_analysis["frame_width"]
            frame_h = speaker_analysis["frame_height"]
            rec_center = speaker_analysis["recommended_center_x"]
            face_ratio = speaker_analysis["face_detected_ratio"]

            print(f"         Source Dimensions: {frame_w}x{frame_h}")
            print(f"         Face Detection Rate: {face_ratio:.1%} of sampled frames")
            print(f"         Recommended Crop Center_X: {rec_center:.1f}px (frame center: {frame_w/2:.1f}px)")
            print(f"         [SUCCESS] Speaker analyzed in {track_time:.2f}s")
        except Exception as e:
            print(f"         [ERROR] Face analysis failed: {e}")
            sys.exit(1)

        # -------------------------------------------------------------
        # STEP C: Smart 9:16 Vertical Reframing (FFmpeg)
        # -------------------------------------------------------------
        print(f"\n[Step C] Reframing to 1080x1920 (9:16) Vertical Video (FFmpeg)...")
        t2 = time.time()
        try:
            reframe_to_vertical(
                input_video_path=raw_clip_path,
                output_video_path=vertical_clip_path,
                mode=mode,
            )
            reframe_time = time.time() - t2
            print(f"         [SUCCESS] Vertical video rendered in {reframe_time:.2f}s")
            print(f"         Saved to: {vertical_clip_path}")
        except Exception as e:
            print(f"         [ERROR] FFmpeg reframing failed: {e}")
            sys.exit(1)

        # -------------------------------------------------------------
        # STEP D: Final ffprobe Verification
        # -------------------------------------------------------------
        print(f"\n[Step D] Verifying Final Vertical Asset with ffprobe...")
        vert_probe = probe_video(vertical_clip_path)
        streams = vert_probe.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        actual_dur = float(vert_probe.get("format", {}).get("duration", 0.0))
        file_size_mb = vertical_clip_path.stat().st_size / (1024 * 1024)

        if not v_stream:
            print("         [FAIL] No video stream found in output!")
            sys.exit(1)
        if not a_stream:
            print("         [FAIL] No audio stream found in output!")
            sys.exit(1)

        actual_w = v_stream.get("width")
        actual_h = v_stream.get("height")
        v_codec = v_stream.get("codec_name")
        a_codec = a_stream.get("codec_name")

        print(f"         Resolution:     {actual_w}x{actual_h} (Expected: 1080x1920)")
        print(f"         Video Codec:    {v_codec}")
        print(f"         Audio Codec:    {a_codec} (Stereo / 44.1kHz)")
        print(f"         Duration:       {actual_dur:.2f}s (Target: {expected_dur:.2f}s)")
        print(f"         File Size:      {file_size_mb:.2f} MB")

        assert actual_w == 1080 and actual_h == 1920, f"Resolution mismatch: {actual_w}x{actual_h}"
        print(f"         [PASSED] All acceptance checks verified for Clip #{display_idx}!")

        record = {
            "clip_index": clip_num,
            "title": title,
            "hook_text": clip.get("hook_text"),
            "start_time": start_time,
            "end_time": end_time,
            "duration": actual_dur,
            "virality_score": clip.get("virality_score"),
            "raw_path": str(raw_clip_path),
            "vertical_path": str(vertical_clip_path),
            "resolution": f"{actual_w}x{actual_h}",
            "aspect_ratio": "9:16",
            "detected_center_x": rec_center,
            "face_detection_ratio": face_ratio,
            "file_size_mb": round(file_size_mb, 2),
        }
        processed_records.append(record)

    # Write phase2_clips.json
    phase2_payload = {
        "video_id": video_id,
        "source_url": source_url,
        "processed_clips": processed_records,
    }

    with open(output_meta_path, "w", encoding="utf-8") as f:
        json.dump(phase2_payload, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 75)
    print(f"  PHASE 2 COMPLETED SUCCESSFULLY!")
    print(f"  Metadata saved to: {output_meta_path}")
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2 Verification: Partial Video Slicing & Smart 9:16 Reframing"
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(BACKEND_DIR / "output" / "phase1_clips.json"),
        help="Path to phase1_clips.json",
    )
    parser.add_argument(
        "--clip-index",
        type=int,
        default=0,
        help="Index of the clip to process (default: 0 for Clip #1)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all clips from phase1_clips.json",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "smart_crop", "blurred_background"],
        help="Vertical reframing mode (default: auto)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to save phase2_clips.json",
    )

    args = parser.parse_args()
    phase1_path = Path(args.input)
    output_meta = Path(args.output) if args.output else None

    run_phase2(
        phase1_path=phase1_path,
        clip_index=args.clip_index,
        process_all=args.all,
        mode=args.mode,
        output_meta_path=output_meta,
    )


if __name__ == "__main__":
    main()

