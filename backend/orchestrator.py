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

from backend.database import DEFAULT_DB_PATH, add_clip, get_job, update_job
from backend.pipeline.captions import burn_captions, generate_ass_subtitles
from backend.pipeline.downloader import download_clip_slice, extract_video_heatmap_peaks
from backend.pipeline.llm_hooks import (
    ClipSegment,
    ViralClip,
    analyze_video_options,
    find_viral_clips,
)
from backend.pipeline.reframer import reframe_to_vertical
from backend.pipeline.smart_editor import (
    assemble_clip_segments,
    apply_dynamic_zooms,
    probe_video_durations,
    remove_dead_air,
    remap_words_after_cuts,
)
from backend.pipeline.transcriber_words import extract_word_timestamps
from backend.pipeline.transcript import (
    build_sentence_blocks,
    extract_video_id,
    fit_window_from_anchor,
    format_sentence_blocks_for_llm,
    format_transcript_for_llm,
    get_transcript,
    list_candidate_windows,
    snap_range_to_blocks,
)

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


def _ensure_job_dirs(job_dir: Path) -> dict[str, Path]:
    """Create (if needed) and return the standard artifact directories for a job."""
    dirs = {
        "raw_clips": job_dir / "raw_clips",
        "vertical_clips": job_dir / "vertical_clips",
        "subtitles": job_dir / "subtitles",
        "final_clips": job_dir / "final_clips",
        "previews": job_dir / "previews",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def process_single_clip(
    job_id: str,
    clip: ViralClip,
    clip_idx: int,
    total_clips: int,
    clip_base_pct: int,
    clip_span: float,
    source_url: str,
    job_dir: Path,
    db_path: Path | str,
    timing_metrics: dict[str, float],
    edit_style: str = "strict",
) -> None:
    """Render one selected clip: slice, tighten, reframe, caption, preview.

    Whisper runs exactly once per clip (on the assembled raw clip). The word
    timestamps are then remapped across the dead-air cuts and reused for the
    karaoke captions, avoiding a second transcription pass.

    In ``strict`` mode dead-air removal is skipped so the sentence-aligned
    duration is preserved (no choppy jump cuts). In ``remix`` mode it trims
    pauses gently so the stitched narrative stays tight.
    """
    dirs = _ensure_job_dirs(job_dir)
    raw_clips_dir = dirs["raw_clips"]
    vertical_clips_dir = dirs["vertical_clips"]
    subtitles_dir = dirs["subtitles"]
    final_clips_dir = dirs["final_clips"]
    previews_dir = dirs["previews"]

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

    # 3B: Transcribe once on the raw clip, then use those words for the
    # dead-air detection so we do not need a second Whisper pass later.
    transcribe_pct = int(clip_base_pct + clip_span * 0.30)
    update_job(
        job_id,
        progress_pct=transcribe_pct,
        current_step=f"Clip {clip_idx}/{total_clips}: Transcribing audio once (faster-whisper)...",
        db_path=db_path,
    )
    t_wh0 = time.time()
    raw_words = extract_word_timestamps(str(raw_path))
    timing_metrics["transcription"] += (time.time() - t_wh0)

    # 3C: Dead-Air / Silence Removal (Jump Cuts)
    jumpcut_pct = int(clip_base_pct + clip_span * 0.45)
    tightened_path = raw_clips_dir / f"clip_{clip_idx}_tightened.mp4"
    if str(edit_style).lower() == "strict":
        # Preserve the exact sentence-aligned window so the output opens and
        # closes cleanly and keeps its intended duration.
        update_job(
            job_id,
            progress_pct=jumpcut_pct,
            current_step=f"Clip {clip_idx}/{total_clips}: Preserving natural pacing (strict mode)...",
            db_path=db_path,
        )
        tightened_path = raw_path
        raw_duration, _, _ = probe_video_durations(raw_path)
        jump_stats = {
            "jump_cuts_count": 0,
            "dead_air_removed_sec": 0.0,
            "original_duration": round(raw_duration, 2),
            "final_duration": round(raw_duration, 2),
            "kept_intervals": [[0.0, round(raw_duration, 3)]],
        }
        words = raw_words
    else:
        update_job(
            job_id,
            progress_pct=jumpcut_pct,
            current_step=f"Clip {clip_idx}/{total_clips}: Gently removing long pauses (remix mode)...",
            db_path=db_path,
        )
        t_ff_cut0 = time.time()
        tightened_path, jump_stats = remove_dead_air(
            raw_path,
            tightened_path,
            words=raw_words,
            max_pause_sec=0.6,
            min_keep_pad_sec=0.15,
        )
        timing_metrics["ffmpeg"] += (time.time() - t_ff_cut0)

        # Remap the original word timestamps onto the concatenated cut timeline.
        words = remap_words_after_cuts(raw_words, jump_stats.get("kept_intervals"))

    # 3D: Cinematic 9:16 Vertical Reframing
    reframe_pct = int(clip_base_pct + clip_span * 0.60)
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

    # Persist the (already computed) word timestamps.
    words_path = subtitles_dir / f"clip_{clip_idx}_words.json"
    with open(words_path, "w", encoding="utf-8") as wf:
        json.dump(words, wf, indent=2)

    # 3E: Dynamic Karaoke .ass & Burn-in
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

    # 3F: Extract Preview Thumbnail
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

    # 3G: Persist clip record
    file_size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2)
    edit_stats = {
        "jump_cuts_count": jump_stats.get("jump_cuts_count", 0),
        "dead_air_removed_sec": jump_stats.get("dead_air_removed_sec", 0.0),
        "layout_mode": reframe_info.get("layout_mode", "blur_fill"),
        "segments_count": len(clip.segments),
        "dynamic_zooms_count": 0,
        "hook_strategy": getattr(clip, "hook_strategy", ""),
        "peak_moment": getattr(clip, "peak_moment", ""),
    }

    clip_record = {
        "id": f"{job_id}-clip-{clip_idx}",
        "clip_index": clip_idx - 1,
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

    # 3H: Cleanup intermediate artifacts (prevent SSD choke)
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

    finish_pct = int(clip_base_pct + clip_span)
    update_job(
        job_id,
        progress_pct=min(95, finish_pct),
        current_step=f"Clip {clip_idx}/{total_clips} complete: '{clip.title}'",
        db_path=db_path,
    )


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
                process_single_clip(
                    job_id=job_id,
                    clip=clip,
                    clip_idx=clip_idx,
                    total_clips=total_clips,
                    clip_base_pct=clip_base_pct,
                    clip_span=clip_span,
                    source_url=source_url,
                    job_dir=job_dir,
                    db_path=db_path,
                    timing_metrics=timing_metrics,
                    edit_style="remix",
                )
                successful_clips += 1

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


def _blocks_text(blocks: list[dict[str, Any]], start: float, end: float) -> str:
    """Return the transcript text covered by a time range."""
    parts = [
        str(b.get("text", "")).strip()
        for b in blocks
        if float(b["end"]) > start and float(b["start"]) < end
    ]
    return " ".join(p for p in parts if p).strip()


def _overlaps_existing(
    start: float,
    end: float,
    used_ranges: list[tuple[float, float]],
    threshold: float = 0.3,
) -> bool:
    """Reject options that overlap a previously chosen option too much."""
    for other_start, other_end in used_ranges:
        overlap = max(0.0, min(end, other_end) - max(start, other_start))
        smaller = min(end - start, other_end - other_start)
        if smaller > 0 and overlap / smaller > threshold:
            return True
    return False


def _normalize_analysis_options(
    clips: list[ViralClip],
    blocks: list[dict[str, Any]],
    edit_style: str,
    num_options: int,
    max_duration: float = 30.0,
    min_duration: float = 20.0,
) -> list[ViralClip]:
    """Snap options to sentence blocks and enforce the duration/continuity rules."""
    style = "remix" if str(edit_style).lower() == "remix" else "strict"
    normalized: list[ViralClip] = []
    used_ranges: list[tuple[float, float]] = []

    for clip in clips:
        new_segments: list[ClipSegment] = []
        total = 0.0

        if style == "strict":
            anchor = clip.segments[0].start_time if clip.segments else clip.start_time
            window = fit_window_from_anchor(anchor, blocks, max_duration, min_duration)
            if not window:
                continue
            start, end = window
            new_segments = [
                ClipSegment(start_time=start, end_time=end, segment_role="core_insight")
            ]
        else:
            for segment in clip.segments:
                start, end = snap_range_to_blocks(
                    float(segment.start_time), float(segment.end_time), blocks
                )
                if total + (end - start) > max_duration:
                    end = round(start + max(0.5, max_duration - total), 3)
                if end - start < 0.5:
                    continue
                new_segments.append(
                    ClipSegment(
                        start_time=start,
                        end_time=end,
                        segment_role=getattr(segment, "segment_role", "core_insight"),
                    )
                )
                total += end - start

            # If the remix is too short, extend the final segment to the next
            # complete sentence block without exceeding the cap.
            if new_segments and total < min_duration:
                last = new_segments[-1]
                for block in blocks:
                    block_end = float(block["end"])
                    if block_end <= last.end_time + 0.01:
                        continue
                    added = block_end - last.end_time
                    if total + added > max_duration:
                        break
                    last.end_time = round(block_end, 3)
                    total += added
                    if total >= min_duration:
                        break

        if not new_segments:
            continue

        start = min(float(s.start_time) for s in new_segments)
        end = max(float(s.end_time) for s in new_segments)
        duration = round(sum(float(s.end_time - s.start_time) for s in new_segments), 2)

        if duration > max_duration + 0.01 or duration < min_duration:
            logger.info(
                f"Skipping option '{clip.title[:40]}': duration {duration:.1f}s "
                f"outside {min_duration:.0f}-{max_duration:.0f}s"
            )
            continue
        if _overlaps_existing(start, end, used_ranges):
            logger.info(f"Skipping overlapping option '{clip.title[:40]}'")
            continue

        clip.segments = new_segments
        clip.start_time = round(start, 3)
        clip.end_time = round(end, 3)
        clip.duration = duration
        normalized.append(clip)
        used_ranges.append((start, end))

    # Fallback: fill missing options with sentence-aligned candidate windows.
    if len(normalized) < num_options:
        for start, end in list_candidate_windows(
            blocks, max_duration, min_duration, limit=30
        ):
            if _overlaps_existing(start, end, used_ranges):
                continue
            text = _blocks_text(blocks, start, end)
            if not text:
                continue
            snippet = text[:110].strip()
            try:
                fallback_clip = ViralClip(
                    title=f"{snippet[:58].rstrip()} #Shorts",
                    hook_text=snippet,
                    virality_score=70,
                    reasoning=(
                        "Auto-selected sentence-aligned highlight (fallback because "
                        "Gemini returned too few valid options)."
                    ),
                    segments=[
                        ClipSegment(
                            start_time=start,
                            end_time=end,
                            segment_role="core_insight",
                        )
                    ],
                )
            except Exception as exc:
                logger.warning(f"Could not build fallback option: {exc}")
                continue
            normalized.append(fallback_clip)
            used_ranges.append((start, end))
            if len(normalized) >= num_options:
                break

    return normalized[:num_options]


def analyze_video_job(
    job_id: str,
    source_url: str,
    num_options: int = 3,
    vibe_override: str | None = None,
    edit_style: str = "strict",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    """Analyze a video and store vibe + render-ready clip options.

    This phase never downloads video slices or runs Whisper/FFmpeg. It only
    fetches the transcript + retention heatmap and asks Gemini for options.
    """
    job_dir = OUTPUT_DIR / "jobs" / job_id
    _ensure_job_dirs(job_dir)

    try:
        update_job(
            job_id,
            status="extracting_transcript",
            progress_pct=10,
            current_step="Extracting video ID and fetching transcript...",
            db_path=db_path,
        )

        video_id = extract_video_id(source_url)
        update_job(job_id, video_id=video_id, db_path=db_path)
        logger.info(f"[{job_id}] Analyzing video_id={video_id} (vibe={vibe_override or 'auto'})")

        transcript_segments = get_transcript(video_id)
        blocks = build_sentence_blocks(transcript_segments)
        formatted_transcript = format_sentence_blocks_for_llm(blocks)
        with open(job_dir / "transcript.txt", "w", encoding="utf-8") as f:
            f.write(formatted_transcript)
        with open(job_dir / "sentence_blocks.json", "w", encoding="utf-8") as f:
            json.dump(blocks, f, indent=2)

        update_job(
            job_id,
            progress_pct=18,
            current_step="Extracting crowd-sourced retention heatmap & replay peaks...",
            db_path=db_path,
        )
        heatmap_peaks = extract_video_heatmap_peaks(source_url)
        if heatmap_peaks:
            with open(job_dir / "heatmap_peaks.json", "w", encoding="utf-8") as f:
                json.dump(heatmap_peaks, f, indent=2)

        update_job(
            job_id,
            status="selecting_hooks",
            progress_pct=45,
            current_step="Detecting video vibe and generating clip options with Gemini...",
            db_path=db_path,
        )

        analysis = analyze_video_options(
            formatted_transcript,
            num_options=num_options,
            heatmap_peaks=heatmap_peaks,
            vibe_override=vibe_override,
            edit_style=edit_style,
            max_duration=30.0,
        )

        if not analysis.clips:
            raise ValueError("Gemini did not return any clip options.")

        normalized_clips = _normalize_analysis_options(
            analysis.clips,
            blocks,
            edit_style=edit_style,
            num_options=num_options,
            max_duration=30.0,
            min_duration=20.0,
        )
        if not normalized_clips:
            raise ValueError(
                "Could not build any sentence-aligned clips within 30s. "
                "Try remix mode or a shorter video."
            )

        options_payload = [clip.model_dump() for clip in normalized_clips]
        with open(job_dir / "selected_hooks.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "content_profile": analysis.content_profile.model_dump(),
                    "clips": options_payload,
                },
                f,
                indent=2,
            )

        profile = analysis.content_profile
        update_job(
            job_id,
            status="awaiting_selection",
            progress_pct=100,
            current_step=(
                f"Detected vibe: {profile.primary_vibe} "
                f"({profile.confidence}%). Choose your clip options to render."
            ),
            content_profile=json.dumps(profile.model_dump()),
            options_json=json.dumps(options_payload),
            db_path=db_path,
        )
        logger.info(
            f"[{job_id}] Analysis complete: vibe={profile.primary_vibe} "
            f"({profile.confidence}%), {len(options_payload)} options ready."
        )

    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.error(f"[{job_id}] Analysis failed: {err_msg}\n{traceback.format_exc()}")
        update_job(
            job_id,
            status="failed",
            error_message=err_msg,
            current_step=f"Analysis failed: {err_msg}",
            db_path=db_path,
        )


def render_selected_clips(
    job_id: str,
    option_indices: list[int],
    edit_style: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    """Render only the clip options the user selected during analysis."""
    job = get_job(job_id, db_path=db_path)
    if not job:
        logger.error(f"[{job_id}] Cannot render: job not found.")
        return

    style = (edit_style or job.get("edit_style") or "strict").lower()

    options = job.get("options_json") or []
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except Exception:
            options = []
    if not options:
        update_job(
            job_id,
            status="failed",
            error_message="No analysis options are available for this job.",
            current_step="Render failed: run analysis first.",
            db_path=db_path,
        )
        return

    cleaned_indices: list[int] = []
    for idx in option_indices:
        if isinstance(idx, int) and 0 <= idx < len(options):
            cleaned_indices.append(idx)
    cleaned_indices = sorted(set(cleaned_indices))
    if not cleaned_indices:
        update_job(
            job_id,
            status="failed",
            error_message="None of the selected options are valid.",
            current_step="Render failed: invalid option selection.",
            db_path=db_path,
        )
        return

    selected_clips: list[ViralClip] = []
    for idx in cleaned_indices:
        try:
            selected_clips.append(ViralClip.model_validate(options[idx]))
        except Exception as exc:
            logger.warning(f"[{job_id}] Skipping invalid option #{idx}: {exc}")

    if not selected_clips:
        update_job(
            job_id,
            status="failed",
            error_message="Selected options could not be parsed.",
            current_step="Render failed: malformed options.",
            db_path=db_path,
        )
        return

    source_url = job["source_url"]
    job_dir = OUTPUT_DIR / "jobs" / job_id
    _ensure_job_dirs(job_dir)
    timing_metrics = {"download": 0.0, "transcription": 0.0, "llm_hooks": 0.0, "ffmpeg": 0.0}
    t_job_start = time.time()
    total_clips = len(selected_clips)
    successful_clips = 0
    clip_errors: list[str] = []

    try:
        update_job(
            job_id,
            status="processing_clips",
            progress_pct=30,
            current_step=f"Rendering {total_clips} selected clip(s)...",
            db_path=db_path,
        )

        for i, clip in enumerate(selected_clips):
            clip_idx = i + 1
            clip_base_pct = 30 + int(i * (65.0 / total_clips))
            clip_span = 65.0 / total_clips
            logger.info(
                f"[{job_id}] Rendering selected clip {clip_idx}/{total_clips}: "
                f"'{clip.title}' ({clip.start_time:.1f}s -> {clip.end_time:.1f}s)"
            )
            try:
                process_single_clip(
                    job_id=job_id,
                    clip=clip,
                    clip_idx=clip_idx,
                    total_clips=total_clips,
                    clip_base_pct=clip_base_pct,
                    clip_span=clip_span,
                    source_url=source_url,
                    job_dir=job_dir,
                    db_path=db_path,
                    timing_metrics=timing_metrics,
                    edit_style=style,
                )
                successful_clips += 1
            except Exception as clip_exc:
                err_text = f"Clip {clip_idx} failed: {type(clip_exc).__name__}: {clip_exc}"
                logger.error(f"[{job_id}] {err_text}\n{traceback.format_exc()}")
                clip_errors.append(err_text)

        if successful_clips == 0:
            combined_err = " | ".join(clip_errors) if clip_errors else "No clips rendered."
            raise RuntimeError(f"All selected clips failed: {combined_err}")

        update_job(
            job_id,
            status="completed",
            progress_pct=100,
            current_step=(
                "All selected clips are ready!"
                if successful_clips == total_clips
                else f"{successful_clips} of {total_clips} selected clips rendered successfully!"
            ),
            completed_at=datetime.now(timezone.utc).isoformat(),
            db_path=db_path,
        )

        total_job_time = time.time() - t_job_start
        telemetry_summary = {
            "job_id": job_id,
            "total_elapsed_sec": round(total_job_time, 2),
            "phase_1_download_sec": round(timing_metrics["download"], 2),
            "phase_2_transcription_sec": round(timing_metrics["transcription"], 2),
            "phase_4_ffmpeg_rendering_sec": round(timing_metrics["ffmpeg"], 2),
            "successful_clips": successful_clips,
            "total_clips": total_clips,
            "selected_options": cleaned_indices,
        }
        with open(job_dir / "telemetry.json", "w", encoding="utf-8") as tf:
            json.dump(telemetry_summary, tf, indent=2)

        logger.info(
            f"[{job_id}] Render complete: {successful_clips}/{total_clips} clips in "
            f"{total_job_time:.2f}s (Whisper {timing_metrics['transcription']:.2f}s, "
            f"FFmpeg {timing_metrics['ffmpeg']:.2f}s)"
        )

    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.error(f"[{job_id}] Render failed: {err_msg}\n{traceback.format_exc()}")
        update_job(
            job_id,
            status="failed",
            error_message=err_msg,
            current_step=f"Render failed: {err_msg}",
            db_path=db_path,
        )

