"""Asynchronous Pipeline Orchestrator for AI Video Clipping.

Executes the complete multi-stage pipeline:
1. Transcript Extraction (youtube-transcript-api / yt-dlp)
2. Viral Hook Selection (Gemini 2.5/3.5)
3. Partial Video Stream Slicing (yt-dlp --download-sections)
4. Smart 9:16 Vertical Reframing (OpenCV face tracking + FFmpeg)
5. Word-Level Timestamp Extraction (faster-whisper)
6. Dynamic Karaoke Subtitle Generation & Burn-In (.ass + FFmpeg libass)
7. Preview Frame Generation & SQLite DB Progressive Persistence
"""

import json
import logging
import os
import shutil
import subprocess
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.database import DEFAULT_DB_PATH, add_clip, update_job
from backend.pipeline.captions import burn_captions, generate_ass_subtitles
from backend.pipeline.downloader import download_clip_slice, extract_video_heatmap_peaks
from backend.pipeline.llm_hooks import find_viral_clips
from backend.pipeline.reframer import reframe_to_vertical
from backend.pipeline.smart_editor import (
    assemble_clip_segments,
    apply_dynamic_zooms,
    probe_video_durations,
    remove_dead_air,
)
from backend.pipeline.transcriber_words import extract_word_timestamps
from backend.pipeline.transcript import extract_video_id, format_transcript_for_llm, get_transcript

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BACKEND_DIR / "output"


def extract_preview_frame(video_path: Path | str, output_image_path: Path | str, timestamp: float = 2.0) -> str:
    """Extract a single high-quality frame from a video at the given timestamp."""
    out_file = Path(output_image_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
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
        str(out_file),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return str(out_file)


def run_clipping_job(
    job_id: str,
    source_url: str,
    num_clips: int = 3,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    """Execute the end-to-end clipping pipeline for a job."""
    logger.info(f"Starting clipping job {job_id} for URL: {source_url} (target clips: {num_clips})")

    # Set up isolated job directories
    job_dir = OUTPUT_DIR / "jobs" / job_id
    raw_clips_dir = job_dir / "raw_clips"
    vertical_clips_dir = job_dir / "vertical_clips"
    subtitles_dir = job_dir / "subtitles"
    final_clips_dir = job_dir / "final_clips"
    previews_dir = job_dir / "previews"

    for d in [raw_clips_dir, vertical_clips_dir, subtitles_dir, final_clips_dir, previews_dir]:
        d.mkdir(parents=True, exist_ok=True)

    t_job_start = time.time()
    timing_metrics = {
        "download": 0.0,
        "transcription": 0.0,
        "llm_hooks": 0.0,
        "ffmpeg": 0.0,
    }

    try:
        # ---------------------------------------------------------
        # STEP 1: Extract Video ID and Transcript (10%)
        # ---------------------------------------------------------
        update_job(
            job_id,
            status="extracting_transcript",
            progress_pct=10,
            current_step="Extracting video ID and fetching transcript...",
            db_path=db_path,
        )

        video_id = extract_video_id(source_url)
        update_job(job_id, video_id=video_id, db_path=db_path)

        logger.info(f"[{job_id}] Fetching transcript for video_id={video_id}")
        t_tx0 = time.time()
        transcript_segments = get_transcript(video_id)
        formatted_transcript = format_transcript_for_llm(transcript_segments)
        timing_metrics["transcription"] += (time.time() - t_tx0)

        # Save transcript to disk for inspection
        with open(job_dir / "transcript.txt", "w", encoding="utf-8") as f:
            f.write(formatted_transcript)

        # ---------------------------------------------------------
        # STEP 1.5: Extract Audience Heatmap Replay Peaks (Waterfall Priority 1)
        # ---------------------------------------------------------
        update_job(
            job_id,
            progress_pct=18,
            current_step="Extracting crowd-sourced retention heatmap & replay peaks...",
            db_path=db_path,
        )
        t_hm0 = time.time()
        heatmap_peaks = extract_video_heatmap_peaks(source_url)
        timing_metrics["download"] += (time.time() - t_hm0)

        if heatmap_peaks:
            logger.info(f"[{job_id}] Extracted {len(heatmap_peaks)} crowd-sourced retention peaks: {[p['display'] for p in heatmap_peaks]}")
            with open(job_dir / "heatmap_peaks.json", "w", encoding="utf-8") as f:
                json.dump(heatmap_peaks, f, indent=2)
        else:
            logger.info(f"[{job_id}] No retention heatmap available; falling back to Chain-of-Thought Virality Scoring")

        # ---------------------------------------------------------
        # STEP 2: Gemini Viral Hook Selection (25%)
        # ---------------------------------------------------------
        step_desc = (
            f"Analyzing transcript & {len(heatmap_peaks)} retention peaks with Gemini (Waterfall Strategy)..."
            if heatmap_peaks
            else "Analyzing transcript with Gemini (Chain-of-Thought Virality Scoring)..."
        )
        update_job(
            job_id,
            status="selecting_hooks",
            progress_pct=25,
            current_step=step_desc,
            db_path=db_path,
        )

        logger.info(f"[{job_id}] Requesting {num_clips} viral hooks from Gemini using Waterfall Strategy")
        t_llm0 = time.time()
        hook_response = find_viral_clips(
            formatted_transcript,
            num_clips=num_clips,
            heatmap_peaks=heatmap_peaks,
        )
        timing_metrics["llm_hooks"] += (time.time() - t_llm0)
        viral_clips = hook_response.clips

        if not viral_clips:
            raise ValueError("No viral clips could be identified from the transcript.")

        logger.info(f"[{job_id}] Gemini selected {len(viral_clips)} viral clips")
        with open(job_dir / "selected_hooks.json", "w", encoding="utf-8") as f:
            json.dump(hook_response.model_dump(), f, indent=2)

        # ---------------------------------------------------------
        # STEP 3: Process Each Clip (30% -> 95%)
        # ---------------------------------------------------------
        total_clips = len(viral_clips)
        successful_clips = 0
        clip_errors: list[str] = []

        update_job(
            job_id,
            status="processing_clips",
            progress_pct=30,
            current_step=f"Identified {total_clips} viral clips. Beginning video slicing & processing...",
            db_path=db_path,
        )

        for i, clip in enumerate(viral_clips):
            clip_idx = i + 1
            clip_base_pct = 30 + int(i * (65.0 / total_clips))
            clip_span = 65.0 / total_clips

            logger.info(
                f"[{job_id}] Processing clip {clip_idx}/{total_clips}: '{clip.title}' "
                f"({clip.start_time:.1f}s -> {clip.end_time:.1f}s, {clip.duration:.1f}s)"
            )

            try:
                # 3A: Narrative Multi-Segment Slicing & Assembly (Download Phase)
                slice_pct = int(clip_base_pct + clip_span * 0.15)
                seg_count = len(clip.segments)
                step_desc = (
                    f"Clip {clip_idx}/{total_clips}: Assembling {seg_count}-part narrative arc ({clip.start_time:.0f}s - {clip.end_time:.0f}s)..."
                    if seg_count > 1
                    else f"Clip {clip_idx}/{total_clips}: Slicing stream ({clip.start_time:.0f}s - {clip.end_time:.0f}s)..."
                )
                update_job(
                    job_id,
                    progress_pct=slice_pct,
                    current_step=step_desc,
                    db_path=db_path,
                )
                raw_path = raw_clips_dir / f"clip_{clip_idx}_raw.mp4"
                temp_seg_dir = job_dir / f"temp_clip_{clip_idx}"

                t_dl_seg0 = time.time()
                assemble_clip_segments(source_url, clip.segments, raw_path, temp_seg_dir)
                timing_metrics["download"] += (time.time() - t_dl_seg0)

                # 3B: Dead-Air / Silence Removal (Jump Cuts) (FFmpeg Rendering Phase)
                jumpcut_pct = int(clip_base_pct + clip_span * 0.30)
                update_job(
                    job_id,
                    progress_pct=jumpcut_pct,
                    current_step=f"Clip {clip_idx}/{total_clips}: Removing dead-air pauses (tightening jump cuts)...",
                    db_path=db_path,
                )
                tightened_path = raw_clips_dir / f"clip_{clip_idx}_tightened.mp4"
                t_ff_cut0 = time.time()
                tightened_path, jump_stats = remove_dead_air(
                    raw_path,
                    tightened_path,
                    max_pause_sec=0.35,
                    min_keep_pad_sec=0.08,
                )
                timing_metrics["ffmpeg"] += (time.time() - t_ff_cut0)

                # 3C: Cinematic 9:16 Vertical Reframing (FFmpeg Blur Fill HW accelerated)
                reframe_pct = int(clip_base_pct + clip_span * 0.50)
                update_job(
                    job_id,
                    progress_pct=reframe_pct,
                    current_step=f"Clip {clip_idx}/{total_clips}: Reframing to 9:16 vertical (cinematic blur fill)...",
                    db_path=db_path,
                )
                vertical_path = vertical_clips_dir / f"clip_{clip_idx}_vertical.mp4"
                t_ff_ref0 = time.time()
                vertical_path, reframe_info = reframe_to_vertical(
                    tightened_path,
                    vertical_path,
                    mode="blur_fill",
                    return_info=True,
                )
                timing_metrics["ffmpeg"] += (time.time() - t_ff_ref0)
                zoom_count = 0

                # 3E: Word-Level Transcription on the tightened, final vertical video (Whisper)
                transcribe_pct = int(clip_base_pct + clip_span * 0.75)
                update_job(
                    job_id,
                    progress_pct=transcribe_pct,
                    current_step=f"Clip {clip_idx}/{total_clips}: Generating word-level timestamps on tightened audio (faster-whisper)...",
                    db_path=db_path,
                )
                t_wh0 = time.time()
                words = extract_word_timestamps(str(vertical_path))
                timing_metrics["transcription"] += (time.time() - t_wh0)

                words_path = subtitles_dir / f"clip_{clip_idx}_words.json"
                with open(words_path, "w", encoding="utf-8") as wf:
                    json.dump(words, wf, indent=2)

                # 3F: Dynamic Karaoke .ass & Burn-in (FFmpeg libass HW accelerated)
                burn_pct = int(clip_base_pct + clip_span * 0.90)
                update_job(
                    job_id,
                    progress_pct=burn_pct,
                    current_step=f"Clip {clip_idx}/{total_clips}: Generating dynamic karaoke subtitles & burning in...",
                    db_path=db_path,
                )
                ass_path = subtitles_dir / f"clip_{clip_idx}.ass"
                generate_ass_subtitles(words, ass_path)

                final_video_path = final_clips_dir / f"clip_{clip_idx}_final.mp4"
                t_ff_burn0 = time.time()
                burn_captions(str(vertical_path), words, ass_path, str(final_video_path))
                timing_metrics["ffmpeg"] += (time.time() - t_ff_burn0)

                # 3G: Extract Preview Thumbnail
                preview_image_path = previews_dir / f"clip_{clip_idx}_preview.jpg"
                final_dur, _, _ = probe_video_durations(final_video_path)
                sample_time = min(2.5, max(0.5, final_dur / 4.0))
                t_ff_th0 = time.time()
                try:
                    extract_preview_frame(final_video_path, preview_image_path, timestamp=sample_time)
                except Exception as pe:
                    logger.warning(f"Could not extract preview frame at {sample_time}s: {pe}, using 0.5s")
                    extract_preview_frame(final_video_path, preview_image_path, timestamp=0.5)
                timing_metrics["ffmpeg"] += (time.time() - t_ff_th0)

                # 3H: Compute metrics, assemble edit_stats & add to DB
                file_size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2)
                layout_mode = reframe_info.get("layout_mode", "blur_fill")
                edit_stats = {
                    "jump_cuts_count": jump_stats.get("jump_cuts_count", 0),
                    "dead_air_removed_sec": jump_stats.get("dead_air_removed_sec", 0.0),
                    "layout_mode": layout_mode,
                    "segments_count": len(clip.segments),
                    "dynamic_zooms_count": zoom_count,
                    "hook_strategy": getattr(clip, "hook_strategy", ""),
                    "peak_moment": getattr(clip, "peak_moment", ""),
                }

                clip_record = {
                    "id": f"{job_id}-clip-{clip_idx}",
                    "clip_index": i,
                    "title": clip.title,
                    "hook_text": clip.hook_text,
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "duration": round(final_dur, 2),
                    "virality_score": clip.virality_score,
                    "reasoning": clip.reasoning,
                    "video_url": f"/media/jobs/{job_id}/final_clips/clip_{clip_idx}_final.mp4",
                    "preview_url": f"/media/jobs/{job_id}/previews/clip_{clip_idx}_preview.jpg",
                    "subtitles_url": f"/media/jobs/{job_id}/subtitles/clip_{clip_idx}.ass",
                    "file_size_mb": file_size_mb,
                    "edit_stats": edit_stats,
                    "social_metadata": clip.social_metadata.model_dump() if getattr(clip, "social_metadata", None) else None,
                }
                add_clip(job_id, clip_record, db_path=db_path)
                successful_clips += 1

                # 3I: Immediate Intermediate Artifact Cleanup (prevent SSD choke)
                if Path(temp_seg_dir).exists():
                    shutil.rmtree(temp_seg_dir, ignore_errors=True)
                for intermediate_file in [raw_path, tightened_path, vertical_path]:
                    p = Path(intermediate_file) if intermediate_file else None
                    if p and p.exists():
                        try:
                            p.unlink()
                            logger.info(f"[{job_id}] Cleaned up intermediate artifact: {p.name}")
                        except Exception as ce:
                            logger.warning(f"Could not remove intermediate artifact {p}: {ce}")

                # Update progress
                finish_pct = int(clip_base_pct + clip_span)
                update_job(
                    job_id,
                    progress_pct=min(95, finish_pct),
                    current_step=f"Clip {clip_idx}/{total_clips} complete: '{clip.title}'",
                    db_path=db_path,
                )

            except Exception as clip_exc:
                err_text = f"Clip {clip_idx} failed: {type(clip_exc).__name__}: {clip_exc}"
                logger.error(f"[{job_id}] {err_text}\n{traceback.format_exc()}")
                clip_errors.append(err_text)
                update_job(
                    job_id,
                    current_step=f"Clip {clip_idx} failed. Continuing with remaining clips...",
                    db_path=db_path,
                )

        if successful_clips == 0:
            combined_err = " | ".join(clip_errors) if clip_errors else "No clips could be processed."
            raise RuntimeError(f"All clips failed during processing: {combined_err}")

        # ---------------------------------------------------------
        # STEP 4: Completed (100%) & Performance Telemetry
        # ---------------------------------------------------------
        now_iso = datetime.now(timezone.utc).isoformat()
        finish_message = (
            "All viral clips generated and ready for download!"
            if successful_clips == total_clips
            else f"{successful_clips} of {total_clips} clips generated successfully!"
        )
        update_job(
            job_id,
            status="completed",
            progress_pct=100,
            current_step=finish_message,
            completed_at=now_iso,
            db_path=db_path,
        )

        total_job_time = time.time() - t_job_start
        telemetry_summary = {
            "job_id": job_id,
            "total_elapsed_sec": round(total_job_time, 2),
            "phase_1_download_sec": round(timing_metrics["download"], 2),
            "phase_2_transcription_sec": round(timing_metrics["transcription"], 2),
            "phase_3_llm_hooks_sec": round(timing_metrics["llm_hooks"], 2),
            "phase_4_ffmpeg_rendering_sec": round(timing_metrics["ffmpeg"], 2),
            "successful_clips": successful_clips,
            "total_clips": total_clips,
        }
        with open(job_dir / "telemetry.json", "w", encoding="utf-8") as tf:
            json.dump(telemetry_summary, tf, indent=2)

        pct_dl = (timing_metrics["download"] / total_job_time * 100) if total_job_time > 0 else 0
        pct_tx = (timing_metrics["transcription"] / total_job_time * 100) if total_job_time > 0 else 0
        pct_llm = (timing_metrics["llm_hooks"] / total_job_time * 100) if total_job_time > 0 else 0
        pct_ff = (timing_metrics["ffmpeg"] / total_job_time * 100) if total_job_time > 0 else 0

        logger.info(
            f"\n"
            f"======================================================================\n"
            f"  PERFORMANCE AUDIT & TELEMETRY SUMMARY - Job [{job_id}]\n"
            f"======================================================================\n"
            f"  1. Download Phase (yt-dlp stream slices & meta):   {timing_metrics['download']:>6.2f}s ({pct_dl:>5.1f}%)\n"
            f"  2. Transcription Phase (YT API + Whisper int8): {timing_metrics['transcription']:>6.2f}s ({pct_tx:>5.1f}%)\n"
            f"  3. LLM Hooks Phase (Gemini Waterfall):          {timing_metrics['llm_hooks']:>6.2f}s ({pct_llm:>5.1f}%)\n"
            f"  4. FFmpeg Rendering Phase (Apple Silicon HW):    {timing_metrics['ffmpeg']:>6.2f}s ({pct_ff:>5.1f}%)\n"
            f"  ----------------------------------------------------------------------\n"
            f"  Total Pipeline Execution Time:                  {total_job_time:>6.2f}s ({successful_clips}/{total_clips} clips rendered)\n"
            f"======================================================================"
        )

    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.error(f"[{job_id}] Pipeline failed: {err_msg}\n{traceback.format_exc()}")
        update_job(
            job_id,
            status="failed",
            error_message=err_msg,
            current_step=f"Failed: {err_msg}",
            db_path=db_path,
        )

