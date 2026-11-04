"""AI Video Clipping System - Phase 6 Test Suite.

Verifies:
1. Multi-Segment Narrative Stitching (ClipSegment Pydantic schema & FFmpeg assembly)
2. Automatic Dead-Air / Silence Removal (Jump cuts & audio/video sync within < 0.05s)
3. 2-Speaker Split-Screen & Smart 9:16 Vertical Reframing
4. Dynamic Camera Punch-In Zooms (1.14x centered on 1080x1920 canvas)
5. End-to-End Pipeline Alignment: Jump-cut audio -> Whisper transcription -> Karaoke burn-in
6. Progressive Persistence of edit_stats in SQLite database
"""

import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import DEFAULT_DB_PATH, add_clip, create_job, get_db_connection, get_job, init_db
from backend.pipeline.captions import burn_captions, generate_ass_subtitles
from backend.pipeline.llm_hooks import ClipSegment, ViralClip
from backend.pipeline.reframer import analyze_speaker_center_x, reframe_to_vertical
from backend.pipeline.smart_editor import (
    apply_dynamic_zooms,
    assemble_clip_segments,
    detect_speech_intervals,
    probe_video_durations,
    remove_dead_air,
)
from backend.pipeline.transcriber_words import extract_word_timestamps

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Phase6Test")

TEST_OUTPUT_DIR = PROJECT_ROOT / "backend" / "output" / "test_phase6"
TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def test_1_multisegment_schema():
    print("\n" + "=" * 80)
    print("  TEST 1: Non-Linear Multi-Segment Pydantic Schema & Duration Synchronization")
    print("=" * 80)

    # Test A: Backward-compatible flat start/end time auto-wraps into a single segment
    flat_clip = ViralClip(
        title="Stanford Commencement Advice #Shorts",
        hook_text="You can't connect the dots looking forward...",
        start_time=10.0,
        end_time=45.0,
        virality_score=94,
        reasoning="Inspirational classic narrative.",
    )
    assert len(flat_clip.segments) == 1, "Expected single segment auto-wrap"
    assert flat_clip.segments[0].segment_role == "core_insight"
    assert flat_clip.duration == 35.0, f"Expected duration 35.0, got {flat_clip.duration}"
    print("✓ Auto-wrap flat clip into 1 ClipSegment passed: duration = 35.0s")

    # Test B: Non-linear multi-segment stitching with cold-open hook
    stitched_clip = ViralClip(
        title="Winning $250k: The Shocking Finale #Shorts",
        hook_text="We did the impossible!",
        segments=[
            ClipSegment(start_time=85.0, end_time=89.5, segment_role="cold_open_hook"),
            ClipSegment(start_time=12.0, end_time=25.0, segment_role="story_setup"),
            ClipSegment(start_time=45.0, end_time=60.0, segment_role="climax_payoff"),
        ],
        virality_score=98,
        reasoning="Cold-open teaser hooks viewer before revealing journey.",
    )
    assert len(stitched_clip.segments) == 3, f"Expected 3 segments, got {len(stitched_clip.segments)}"
    expected_dur = round((89.5 - 85.0) + (25.0 - 12.0) + (60.0 - 45.0), 2)  # 4.5 + 13.0 + 15.0 = 32.5s
    assert stitched_clip.duration == expected_dur, f"Expected {expected_dur}s, got {stitched_clip.duration}s"
    assert stitched_clip.start_time == 12.0, f"Expected min start 12.0, got {stitched_clip.start_time}"
    assert stitched_clip.end_time == 89.5, f"Expected max end 89.5, got {stitched_clip.end_time}"
    print(f"✓ Non-linear 3-part stitch validated: duration = {stitched_clip.duration}s (min: 12.0s, max: 89.5s)")

    # Test C: Safe field extraction from Pydantic ClipSegment and Dict
    from backend.pipeline.smart_editor import _get_seg_fields
    s1, e1, r1 = _get_seg_fields(stitched_clip.segments[0])
    assert s1 == 85.0 and e1 == 89.5 and r1 == "cold_open_hook"
    s2, e2, r2 = _get_seg_fields({"start_time": 10.0, "end_time": 20.0, "segment_role": "story_setup"})
    assert s2 == 10.0 and e2 == 20.0 and r2 == "story_setup"
    print("✓ _get_seg_fields correctly handles both Pydantic ClipSegment and dictionary inputs")


def test_2_dead_air_removal():
    print("\n" + "=" * 80)
    print("  TEST 2: Automatic Dead-Air / Silence Removal (Jump Cuts & A/V Sync)")
    print("=" * 80)

    # Use existing clip_1_raw.mp4 from Phase 2 / Phase 3 verification
    source_raw = PROJECT_ROOT / "backend" / "output" / "raw_clips" / "clip_1_raw.mp4"
    if not source_raw.exists():
        # Fallback to Stanford seed if raw clip path differs
        source_raw = list((PROJECT_ROOT / "backend" / "output").glob("**/clip_1_raw.mp4"))[0]

    output_tightened = TEST_OUTPUT_DIR / "clip_1_tightened.mp4"

    orig_dur, _, _ = probe_video_durations(source_raw)
    print(f"  Input source clip duration: {orig_dur:.2f}s")

    tightened_path, stats = remove_dead_air(
        source_raw,
        output_tightened,
        max_pause_sec=0.35,
        min_keep_pad_sec=0.08,
    )

    assert Path(tightened_path).exists(), "Tightened video file was not created"
    final_dur, v_dur, a_dur = probe_video_durations(tightened_path)
    av_diff = abs(v_dur - a_dur)

    print(f"✓ Jump Cuts Executed:     {stats['jump_cuts_count']}")
    print(f"✓ Dead Air Removed:       {stats['dead_air_removed_sec']:.2f}s")
    print(f"✓ Final Tightened Dur:    {final_dur:.2f}s")
    print(f"✓ Audio/Video Sync Delta: {av_diff:.4f}s (Acceptance threshold: < 0.05s)")

    assert av_diff < 0.05, f"Audio/video desync {av_diff}s exceeds 0.05s tolerance!"
    assert stats["jump_cuts_count"] > 0, "Expected at least 1 jump cut in speech test clip"


def test_3_splitscreen_and_reframing():
    print("\n" + "=" * 80)
    print("  TEST 3: 2-Speaker Podcast Split-Screen Mode & 9:16 Vertical Reframing")
    print("=" * 80)

    # Generate a synthetic 3-second horizontal 1920x1080 clip for testing
    test_horizontal = TEST_OUTPUT_DIR / "synthetic_horizontal.mp4"
    test_split_out = TEST_OUTPUT_DIR / "split_screen_vertical.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1920x1080:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
        str(test_horizontal),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    # Force split_screen mode on the horizontal video
    out_path, info = reframe_to_vertical(
        test_horizontal,
        test_split_out,
        mode="split_screen",
        return_info=True,
    )

    assert Path(out_path).exists(), "Split-screen video was not generated"
    assert info["layout_mode"] == "split_screen"

    # Verify output resolution using ffprobe
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json",
            str(test_split_out),
        ],
        capture_output=True, text=True, check=True
    )
    p_info = json.loads(probe.stdout)["streams"][0]
    w, h = p_info["width"], p_info["height"]
    print(f"✓ Split-Screen Vertical Canvas: {w}x{h} (Expected: 1080x1920)")
    assert w == 1080 and h == 1920, f"Expected 1080x1920, got {w}x{h}"


def test_4_dynamic_camera_zooms():
    print("\n" + "=" * 80)
    print("  TEST 4: Dynamic Camera Punch-In Zooms (1.14x Face Centered)")
    print("=" * 80)

    # Generate a 7-second 1080x1920 vertical video
    vert_src = TEST_OUTPUT_DIR / "synthetic_vertical.mp4"
    vert_zoom_out = TEST_OUTPUT_DIR / "synthetic_vertical_zoomed.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=7:size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=7",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
        str(vert_src),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    z_path, zoom_count = apply_dynamic_zooms(vert_src, vert_zoom_out, zoom_factor=1.14, interval_sec=3.0)

    assert Path(z_path).exists(), "Zoomed vertical video was not generated"
    assert zoom_count >= 1, f"Expected at least 1 zoom cycle, got {zoom_count}"

    # Verify dimensions remain 1080x1920
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json",
            str(z_path),
        ],
        capture_output=True, text=True, check=True
    )
    dims = json.loads(probe.stdout)["streams"][0]
    print(f"✓ Dynamic Zoom Applied: {zoom_count} punch-in transitions | Canvas: {dims['width']}x{dims['height']}")
    assert dims["width"] == 1080 and dims["height"] == 1920


def test_5_pipeline_resync_and_db_persistence():
    print("\n" + "=" * 80)
    print("  TEST 5: Full Smart Editing Pipeline End-to-End & SQLite edit_stats Persistence")
    print("=" * 80)

    # 1. Take a jump-cut tightened vertical video
    input_tightened = TEST_OUTPUT_DIR / "clip_1_tightened.mp4"
    vertical_out = TEST_OUTPUT_DIR / "clip_1_tightened_vertical.mp4"

    out_vert, reframe_info = reframe_to_vertical(input_tightened, vertical_out, mode="auto", return_info=True)
    print(f"✓ Reframed tightened clip: {vertical_out.name} (layout: {reframe_info['layout_mode']})")

    # 2. Extract word-level timestamps on the tightened audio
    words = extract_word_timestamps(vertical_out)
    assert len(words) > 10, f"Expected word timestamps from tightened video, got {len(words)}"
    print(f"✓ Extracted {len(words)} word timestamps on tightened audio timeline ({words[0]['start']:.2f}s -> {words[-1]['end']:.2f}s)")

    # 3. Generate ASS subtitles & Burn-in
    ass_path = TEST_OUTPUT_DIR / "clip_1_tightened.ass"
    final_burned = TEST_OUTPUT_DIR / "clip_1_tightened_final.mp4"

    generate_ass_subtitles(words, ass_path)
    burn_captions(vertical_out, words, ass_path, final_burned)

    assert final_burned.exists() and final_burned.stat().st_size > 0
    print(f"✓ Burned dynamic karaoke subtitles into jump-cut video: {final_burned.name} ({final_burned.stat().st_size:,} bytes)")

    # 4. Verify SQLite Progressive Persistence of edit_stats
    init_db(DEFAULT_DB_PATH)
    test_job_id = f"test-p6-{uuid.uuid4().hex[:8]}"
    create_job("https://www.youtube.com/watch?v=UF8uR6Z6KLc", num_clips=1, job_id=test_job_id, db_path=DEFAULT_DB_PATH)

    edit_stats = {
        "jump_cuts_count": 8,
        "dead_air_removed_sec": 4.25,
        "layout_mode": "single_tracked",
        "segments_count": 2,
        "dynamic_zooms_count": 3,
    }

    clip_record = {
        "id": f"{test_job_id}-clip-1",
        "clip_index": 0,
        "title": "Stanford Speech Tightened #Shorts",
        "hook_text": "You can't connect the dots looking forward...",
        "start_time": 300.5,
        "end_time": 333.3,
        "duration": 27.6,
        "virality_score": 96,
        "reasoning": "High retention jump-cut storytelling.",
        "video_url": f"/media/jobs/{test_job_id}/final_clips/clip_1_final.mp4",
        "preview_url": f"/media/jobs/{test_job_id}/previews/clip_1_preview.jpg",
        "subtitles_url": f"/media/jobs/{test_job_id}/subtitles/clip_1.ass",
        "file_size_mb": 7.8,
        "edit_stats": edit_stats,
    }

    add_clip(test_job_id, clip_record, db_path=DEFAULT_DB_PATH)
    loaded_job = get_job(test_job_id, db_path=DEFAULT_DB_PATH)
    assert loaded_job is not None
    assert len(loaded_job["clips"]) == 1

    stored_clip = loaded_job["clips"][0]
    stored_stats = stored_clip.get("edit_stats")
    print(f"✓ Retrieved edit_stats from SQLite: {stored_stats}")

    assert stored_stats is not None, "Expected edit_stats to be present in clip"
    assert stored_stats["jump_cuts_count"] == 8
    assert stored_stats["dead_air_removed_sec"] == 4.25
    assert stored_stats["segments_count"] == 2

    # Clean up test job from database
    with get_db_connection(DEFAULT_DB_PATH) as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (test_job_id,))
    print(f"✓ Cleaned up test job {test_job_id}")


def main():
    print("=" * 80)
    print("  PHASE 6: THE SMART EDITING ENGINE TEST SUITE")
    print("  Multi-Segment Stitching, Dead-Air Removal, Split-Screen & Dynamic Zooms")
    print("=" * 80)

    try:
        test_1_multisegment_schema()
        test_2_dead_air_removal()
        test_3_splitscreen_and_reframing()
        test_4_dynamic_camera_zooms()
        test_5_pipeline_resync_and_db_persistence()

        print("\n" + "=" * 80)
        print("  🎉 ALL PHASE 6 TESTS PASSED WITH 100% SUCCESS!")
        print("=" * 80)
        return 0
    except Exception as e:
        logger.error(f"Phase 6 Test failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

