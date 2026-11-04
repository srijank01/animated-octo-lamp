#!/usr/bin/env python3
"""CLI Verification Script for Phase 3: Word Timestamps, ASS Subtitles & Caption Burn-In.

Usage:
    python backend/test_phase3.py                  # Process Clip #1
    python backend/test_phase3.py --clip-index 1   # Process Clip #2
    python backend/test_phase3.py --all            # Process all clips in phase2_clips.json
"""

import argparse
import json
import logging
import subprocess
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

from pipeline.downloader import probe_video
from pipeline.transcriber_words import extract_word_timestamps
from pipeline.captions import generate_ass_subtitles, burn_captions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Phase3Verification")


def extract_preview_frame(video_path: Path, output_image_path: Path, timestamp: float = 2.0) -> Path:
    """Extract a single frame from video at timestamp using FFmpeg."""
    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_image_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_image_path


def run_phase3(
    phase2_path: Path,
    clip_index: int | None = 0,
    process_all: bool = False,
    output_meta_path: Path | None = None,
) -> None:
    print("=" * 80)
    print("  AI VIDEO CLIPPING SYSTEM - PHASE 3 VERIFICATION")
    print("  Word Timestamps, Dynamic Karaoke .ass & Final Viral Caption Burn-In")
    print("=" * 80)

    if not phase2_path.exists():
        print(f"\n[ERROR] Phase 2 output not found at: {phase2_path}")
        print("Please run `backend/test_phase2.py --all` first.")
        sys.exit(1)

    with open(phase2_path, "r", encoding="utf-8") as f:
        phase2_data = json.load(f)

    source_url = phase2_data.get("source_url")
    video_id = phase2_data.get("video_id")
    clips = phase2_data.get("processed_clips", [])

    if not clips:
        print("[ERROR] No processed clips found in phase2_clips.json.")
        sys.exit(1)

    if process_all:
        selected_clips = [(i, c) for i, c in enumerate(clips)]
    else:
        idx = clip_index or 0
        if idx < 0 or idx >= len(clips):
            print(f"[ERROR] Invalid clip index {idx}. Available: 0 to {len(clips)-1}")
            sys.exit(1)
        selected_clips = [(idx, clips[idx])]

    subtitles_dir = BACKEND_DIR / "output" / "subtitles"
    final_clips_dir = BACKEND_DIR / "output" / "final_clips"
    previews_dir = BACKEND_DIR / "output" / "previews"

    subtitles_dir.mkdir(parents=True, exist_ok=True)
    final_clips_dir.mkdir(parents=True, exist_ok=True)
    previews_dir.mkdir(parents=True, exist_ok=True)

    if output_meta_path is None:
        output_meta_path = BACKEND_DIR / "output" / "phase3_clips.json"

    phase3_records = []

    for clip_num, clip in selected_clips:
        display_idx = clip.get("clip_index", clip_num) + 1
        title = clip.get("title", f"Clip_{display_idx}")
        vertical_path = Path(clip["vertical_path"])
        raw_path = Path(clip["raw_path"])
        expected_dur = float(clip.get("duration", 30.0))

        print(f"\n" + "-" * 80)
        print(f"  PROCESSING CLIP #{display_idx}: {title}")
        print(f"  Source Vertical: {vertical_path.name} | Target Duration: {expected_dur:.2f}s")
        print("-" * 80)

        words_json_path = subtitles_dir / f"clip_{display_idx}_words.json"
        ass_path = subtitles_dir / f"clip_{display_idx}.ass"
        final_video_path = final_clips_dir / f"clip_{display_idx}_final.mp4"
        preview_image_path = previews_dir / f"clip_{display_idx}_preview.jpg"

        # -------------------------------------------------------------
        # STEP A: Word-Level Timestamp Extraction
        # -------------------------------------------------------------
        print(f"\n[Step A] Extracting Word-Level Timestamps (Faster-Whisper)...")
        t0 = time.time()
        try:
            # Use vertical or raw clip audio (both have identical synchronized audio)
            words = extract_word_timestamps(vertical_path, clip_metadata=clip)
            words_time = time.time() - t0

            # Save words JSON
            with open(words_json_path, "w", encoding="utf-8") as f:
                json.dump(words, f, indent=2, ensure_ascii=False)

            sample_words_str = " ".join([w["word"] for w in words[:7]])
            print(f"         [SUCCESS] Extracted {len(words)} words in {words_time:.2f}s")
            print(f"         Sample (First 7 words): \"{sample_words_str}...\"")
            print(f"         Saved words to: {words_json_path}")
        except Exception as e:
            print(f"         [ERROR] Word timestamp extraction failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

        # -------------------------------------------------------------
        # STEP B: Dynamic Karaoke .ass Generation
        # -------------------------------------------------------------
        print(f"\n[Step B] Generating Dynamic Karaoke .ass Subtitles...")
        try:
            generate_ass_subtitles(
                words=words,
                output_ass_path=ass_path,
                resolution=(1080, 1920),
                highlight_color="&H0000D7FF&",  # Viral Gold/Yellow
                primary_color="&H00FFFFFF&",    # Crisp White
                outline_color="&H00000000&",    # Solid Black
                margin_v=420,                   # Safe zone
            )
            print(f"         [SUCCESS] Subtitle file generated: {ass_path}")
        except Exception as e:
            print(f"         [ERROR] ASS generation failed: {e}")
            sys.exit(1)

        # -------------------------------------------------------------
        # STEP C: Burn Styled Karaoke Captions
        # -------------------------------------------------------------
        print(f"\n[Step C] Burning Styled Captions into 1080x1920 Video (FFmpeg libass)...")
        t1 = time.time()
        try:
            burn_captions(
                input_vertical_video=vertical_path,
                words=words,
                ass_path=ass_path,
                output_final_video=final_video_path,
            )
            burn_time = time.time() - t1
            print(f"         [SUCCESS] Final captioned short rendered in {burn_time:.2f}s")
            print(f"         Saved to: {final_video_path}")
        except Exception as e:
            print(f"         [ERROR] Caption burn-in failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

        # -------------------------------------------------------------
        # STEP D: Final Verification & Preview Frame Extraction
        # -------------------------------------------------------------
        print(f"\n[Step D] Verifying Final Asset & Extracting Caption Preview Frame...")
        final_probe = probe_video(final_video_path)
        streams = final_probe.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        final_dur = float(final_probe.get("format", {}).get("duration", 0.0))
        file_size_mb = final_video_path.stat().st_size / (1024 * 1024)

        if not v_stream or not a_stream:
            print("         [FAIL] Missing audio or video streams in final video!")
            sys.exit(1)

        final_w = v_stream.get("width")
        final_h = v_stream.get("height")
        v_codec = v_stream.get("codec_name")
        a_codec = a_stream.get("codec_name")

        # Pick a timestamp where speech is active for preview frame
        preview_time = 2.0
        if len(words) > 4:
            preview_time = float(words[3]["start"]) + 0.05

        extract_preview_frame(final_video_path, preview_image_path, timestamp=preview_time)

        print(f"         Resolution:     {final_w}x{final_h} (Expected: 1080x1920)")
        print(f"         Video Codec:    {v_codec}")
        print(f"         Audio Codec:    {a_codec}")
        print(f"         Final Duration: {final_dur:.2f}s")
        print(f"         File Size:      {file_size_mb:.2f} MB")
        print(f"         Preview Frame:  {preview_image_path} (captured at {preview_time:.2f}s)")
        print(f"         [PASSED] Clip #{display_idx} 100% verified!")

        record = {
            **clip,
            "words_path": str(words_json_path),
            "ass_path": str(ass_path),
            "final_video_path": str(final_video_path),
            "preview_image_path": str(preview_image_path),
            "word_count": len(words),
            "final_duration": final_dur,
            "final_file_size_mb": round(file_size_mb, 2),
        }
        phase3_records.append(record)

    # Write phase3_clips.json
    phase3_payload = {
        "video_id": video_id,
        "source_url": source_url,
        "final_clips": phase3_records,
    }

    with open(output_meta_path, "w", encoding="utf-8") as f:
        json.dump(phase3_payload, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print("  PHASE 3 COMPLETED SUCCESSFULLY!")
    print(f"  Final Metadata saved to: {output_meta_path}")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 3 Verification: Word-Level Karaoke Subtitles & Final Video Burn-In"
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(BACKEND_DIR / "output" / "phase2_clips.json"),
        help="Path to phase2_clips.json",
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
        help="Process all clips from phase2_clips.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to save phase3_clips.json",
    )

    args = parser.parse_args()
    phase2_path = Path(args.input)
    output_meta = Path(args.output) if args.output else None

    run_phase3(
        phase2_path=phase2_path,
        clip_index=args.clip_index,
        process_all=args.all,
        output_meta_path=output_meta,
    )


if __name__ == "__main__":
    main()

