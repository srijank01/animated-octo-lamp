"""Smart Editing Engine for Short-Form Viral Video.

Provides:
1. Multi-Segment Narrative Stitching (cold-open teasers, tangent removal, audio-aligned concatenation)
2. Automatic Dead-Air / Silence Removal (high-energy jump cuts with natural breathing pad)
3. Dynamic Camera Punch-In Zooms (1.12x-1.15x face-centered zooms on alternating beats)
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from backend.pipeline.downloader import download_clip_slice
from backend.pipeline.transcriber_words import extract_word_timestamps

logger = logging.getLogger(__name__)


def probe_video_durations(video_path: str | Path) -> tuple[float, float, float]:
    """Probe container duration, video stream duration, and audio stream duration using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=duration,codec_type",
        "-of",
        "json",
        str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(res.stdout)
    container_dur = float(info.get("format", {}).get("duration", 0.0))
    video_dur = container_dur
    audio_dur = container_dur

    for s in info.get("streams", []):
        ctype = s.get("codec_type")
        sdur = float(s.get("duration", 0.0) or 0.0)
        if ctype == "video" and sdur > 0:
            video_dur = sdur
        elif ctype == "audio" and sdur > 0:
            audio_dur = sdur

    return container_dur, video_dur, audio_dur


def _get_seg_fields(seg: Any) -> tuple[float, float, str]:
    """Safely extract (start_time, end_time, segment_role) from a ClipSegment or dict."""
    if isinstance(seg, dict):
        s_start = float(seg.get("start_time", 0.0))
        s_end = float(seg.get("end_time", 0.0))
        role = str(seg.get("segment_role", "segment"))
    else:
        s_start = float(getattr(seg, "start_time", 0.0))
        s_end = float(getattr(seg, "end_time", 0.0))
        role = str(getattr(seg, "segment_role", "segment"))
    return s_start, s_end, role


def assemble_clip_segments(
    source_url: str,
    segments: list[Any],
    output_path: str | Path,
    temp_dir: str | Path,
) -> str:
    """Download and stitch multiple narrative sub-segments in sequence.

    Args:
        source_url: YouTube video URL.
        segments: List of ClipSegment objects (or dicts) with start_time and end_time.
        output_path: Destination path for the assembled raw video.
        temp_dir: Directory to store individual segment downloads.

    Returns:
        Absolute path to the assembled MP4.
    """
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    t_dir = Path(temp_dir).resolve()
    t_dir.mkdir(parents=True, exist_ok=True)

    if not segments:
        raise ValueError("Cannot assemble clip: segments list is empty.")

    # Single segment optimization: direct download
    if len(segments) == 1:
        s_start, s_end, _ = _get_seg_fields(segments[0])
        logger.info(f"Single segment clip: downloading {s_start:.2f}s -> {s_end:.2f}s")
        download_clip_slice(source_url, s_start, s_end, str(out_file))
        return str(out_file)

    # Multi-segment assembly
    logger.info(f"Multi-segment assembly: downloading {len(segments)} narrative sub-segments...")
    downloaded_files: list[Path] = []

    for idx, seg in enumerate(segments):
        s_start, s_end, role = _get_seg_fields(seg)
        seg_file = t_dir / f"subseg_{idx}_{role}.mp4"

        logger.info(f"  Downloading Sub-Segment #{idx + 1} ({role}): {s_start:.2f}s -> {s_end:.2f}s")
        download_clip_slice(source_url, s_start, s_end, str(seg_file))
        downloaded_files.append(seg_file)

    # Stitch using FFmpeg concat filter
    input_args: list[str] = []
    filter_inputs: list[str] = []
    for idx, fpath in enumerate(downloaded_files):
        input_args.extend(["-i", str(fpath)])
        filter_inputs.append(f"[{idx}:v][{idx}:a]")

    filter_complex = f"{''.join(filter_inputs)}concat=n={len(downloaded_files)}:v=1:a=1[outv][outa]"

    cmd = [
        "ffmpeg",
        "-y",
        *input_args,
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(out_file),
    ]

    logger.info(f"Stitching {len(downloaded_files)} sub-segments into: {out_file.name}")
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Multi-segment stitching failed (code {res.returncode}): {res.stderr[-400:]}")

    logger.info(f"Successfully stitched {len(downloaded_files)} sub-segments into: {out_file}")
    return str(out_file)


def detect_speech_intervals(
    video_path: str | Path,
    words: list[dict[str, Any]] | None = None,
    max_pause_sec: float = 0.35,
    min_keep_pad_sec: float = 0.08,
) -> tuple[list[tuple[float, float]], float]:
    """Detect spoken intervals and identify dead air gaps exceeding max_pause_sec.

    Uses word-level timestamps (or runs faster-whisper) for reliable speech
    detection even over loud background music or cheering.

    Returns:
        (kept_intervals, total_duration)
    """
    total_dur, _, _ = probe_video_durations(video_path)
    if total_dur <= 0:
        return [(0.0, 0.0)], 0.0

    word_list = words
    if word_list is None:
        try:
            word_list = extract_word_timestamps(video_path)
        except Exception as e:
            logger.warning(f"Could not extract words for dead air removal: {e}. Keeping full clip.")
            return [(0.0, total_dur)], total_dur

    if not word_list:
        return [(0.0, total_dur)], total_dur

    raw_intervals: list[tuple[float, float]] = []
    current_start = max(0.0, float(word_list[0]["start"]) - min_keep_pad_sec)

    for i in range(len(word_list) - 1):
        w_end = float(word_list[i]["end"])
        next_start = float(word_list[i + 1]["start"])
        gap = next_start - w_end

        if gap > max_pause_sec:
            # End current speech interval with natural breathing pad
            current_end = min(total_dur, w_end + min_keep_pad_sec)
            if current_end > current_start + 0.1:
                raw_intervals.append((current_start, current_end))
            current_start = max(0.0, next_start - min_keep_pad_sec)

    # Add final interval
    last_end = min(total_dur, float(word_list[-1]["end"]) + min_keep_pad_sec * 1.5)
    if last_end > current_start + 0.1:
        raw_intervals.append((current_start, last_end))

    if not raw_intervals:
        return [(0.0, total_dur)], total_dur

    # Merge overlapping or close intervals
    merged: list[tuple[float, float]] = []
    for s, e in raw_intervals:
        if not merged:
            merged.append((s, e))
        else:
            prev_s, prev_e = merged[-1]
            if s <= prev_e + 0.05:
                merged[-1] = (prev_s, max(prev_e, e))
            else:
                merged.append((s, e))

    return merged, total_dur


def remove_dead_air(
    video_path: str | Path,
    output_path: str | Path,
    words: list[dict[str, Any]] | None = None,
    max_pause_sec: float = 0.35,
    min_keep_pad_sec: float = 0.08,
) -> tuple[str, dict[str, Any]]:
    """Remove dead air pauses longer than max_pause_sec with natural breathing margins.

    Returns:
        (output_video_path, edit_stats_dict)
    """
    in_file = Path(video_path).resolve()
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    intervals, total_dur = detect_speech_intervals(
        in_file,
        words=words,
        max_pause_sec=max_pause_sec,
        min_keep_pad_sec=min_keep_pad_sec,
    )

    jump_cuts_count = max(0, len(intervals) - 1)
    planned_dur = sum(e - s for s, e in intervals)
    dead_air_potential = total_dur - planned_dur

    # If no significant dead air to remove (< 0.4s or 0 cuts), copy/transcode cleanly
    if jump_cuts_count == 0 or dead_air_potential < 0.30:
        logger.info(f"Dead-air detector found no significant pauses (> {max_pause_sec}s). Keeping original audio flow.")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(in_file),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            str(out_file),
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return str(out_file), {
            "jump_cuts_count": 0,
            "dead_air_removed_sec": 0.0,
            "original_duration": round(total_dur, 2),
            "final_duration": round(total_dur, 2),
        }

    # Construct single-pass FFmpeg trim filter
    filter_parts: list[str] = []
    concat_inputs: list[str] = []

    for idx, (s, e) in enumerate(intervals):
        filter_parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{idx}]")
        filter_parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{idx}]")
        concat_inputs.append(f"[v{idx}][a{idx}]")

    filter_complex = f"{';'.join(filter_parts)};{''.join(concat_inputs)}concat=n={len(intervals)}:v=1:a=1[outv][outa]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(in_file),
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(out_file),
    ]

    logger.info(
        f"Executing dead-air removal: {jump_cuts_count} jump cuts, "
        f"removing ~{dead_air_potential:.2f}s of silence..."
    )
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        logger.warning(f"Dead air removal failed (code {res.returncode}): {res.stderr[-300:]}. Falling back to source video.")
        shutil_cmd = ["cp", str(in_file), str(out_file)]
        subprocess.run(shutil_cmd, check=True)
        return str(out_file), {
            "jump_cuts_count": 0,
            "dead_air_removed_sec": 0.0,
            "original_duration": round(total_dur, 2),
            "final_duration": round(total_dur, 2),
        }

    final_dur, v_dur, a_dur = probe_video_durations(out_file)
    actual_removed = max(0.0, round(total_dur - final_dur, 2))

    logger.info(
        f"Dead-air jump cuts complete: {jump_cuts_count} cuts, "
        f"{actual_removed:.2f}s removed (final duration: {final_dur:.2f}s, a/v sync diff: {abs(v_dur - a_dur):.3f}s)"
    )

    return str(out_file), {
        "jump_cuts_count": jump_cuts_count,
        "dead_air_removed_sec": actual_removed,
        "original_duration": round(total_dur, 2),
        "final_duration": round(final_dur, 2),
    }


def apply_dynamic_zooms(
    vertical_video_path: str | Path,
    output_path: str | Path,
    zoom_factor: float = 1.14,
    interval_sec: float = 3.5,
) -> tuple[str, int]:
    """Apply dynamic 1.12x-1.15x camera punch-in zooms on alternating beats to reset retention.

    Operates on 1080x1920 vertical video.

    Returns:
        (output_video_path, total_zooms_applied)
    """
    in_file = Path(vertical_video_path).resolve()
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    total_dur, _, _ = probe_video_durations(in_file)
    if total_dur < interval_sec * 1.5:
        # Too short for dynamic zooms
        cmd = ["ffmpeg", "-y", "-i", str(in_file), "-c", "copy", str(out_file)]
        subprocess.run(cmd, capture_output=True, check=True)
        return str(out_file), 0

    # Calculate 1.14x crop dimensions inside 1080x1920
    crop_w = int(round(1080.0 / zoom_factor))
    crop_w = crop_w - (crop_w % 2)
    crop_h = int(round(1920.0 / zoom_factor))
    crop_h = crop_h - (crop_h % 2)
    off_x = (1080 - crop_w) // 2
    off_y = (1920 - crop_h) // 2

    # FFmpeg crop expression toggling every `interval_sec` seconds
    filter_expr = (
        f"[0:v]crop=w='if(mod(floor(t/{interval_sec:.2f}), 2), {crop_w}, 1080)':"
        f"h='if(mod(floor(t/{interval_sec:.2f}), 2), {crop_h}, 1920)':"
        f"x='if(mod(floor(t/{interval_sec:.2f}), 2), {off_x}, 0)':"
        f"y='if(mod(floor(t/{interval_sec:.2f}), 2), {off_y}, 0)',"
        f"scale=1080:1920:flags=lanczos[v]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(in_file),
        "-filter_complex",
        filter_expr,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "copy",
        str(out_file),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        logger.warning(f"Dynamic zoom failed (code {res.returncode}): {res.stderr[-300:]}. Using unzoomed vertical video.")
        cmd = ["ffmpeg", "-y", "-i", str(in_file), "-c", "copy", str(out_file)]
        subprocess.run(cmd, capture_output=True, check=True)
        return str(out_file), 0

    zoom_cycles = int(total_dur // (interval_sec * 2.0))
    logger.info(f"Applied {zoom_cycles} dynamic punch-in zooms to {out_file.name}")
    return str(out_file), max(1, zoom_cycles)

