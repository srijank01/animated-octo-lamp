"""Zero-Full-Download partial video stream downloader using yt-dlp.

Downloads ONLY the requested 30-60 second time section from YouTube
without fetching the full source video, merging best available video/audio into MP4.
Includes robust anti-403 retry mechanisms and player client fallbacks.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def probe_video(file_path: str | Path) -> dict[str, Any]:
    """Inspect video file streams, resolution, and duration using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,duration",
        "-of",
        "json",
        str(file_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {file_path}: {result.stderr}")
    return json.loads(result.stdout)


def download_clip_slice(
    source_url: str,
    start_time: float,
    end_time: float,
    output_path: str | Path,
) -> str:
    """Download only the requested time slice of a video using yt-dlp.

    Args:
        source_url: YouTube URL or 11-character video ID.
        start_time: Start timestamp in seconds.
        end_time: End timestamp in seconds.
        output_path: Destination filepath for the sliced MP4.

    Returns:
        Absolute path to the downloaded MP4 clip slice.
    """
    clean_url = source_url.strip()
    # Strip tracking parameters (?si=..., &si=...)
    if "?si=" in clean_url:
        clean_url = clean_url.split("?si=")[0]
    elif "&si=" in clean_url:
        clean_url = clean_url.split("&si=")[0]

    if len(clean_url) == 11 and not clean_url.startswith("http"):
        clean_url = f"https://www.youtube.com/watch?v={clean_url}"

    dest_path = Path(output_path).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # If the destination file already exists, remove it to ensure a fresh download
    if dest_path.exists():
        dest_path.unlink()

    duration = max(1.0, end_time - start_time)
    section_arg = f"*{start_time:.2f}-{end_time:.2f}"

    # Try different format and client strategies across retries to prevent 403 Forbidden
    strategies = [
        # Strategy 1: Android + Web client with best 1080p stream
        {
            "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]/best",
            "extractor_args": "youtube:player_client=android,web",
        },
        # Strategy 2: iOS / mweb client fallback
        {
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "extractor_args": "youtube:player_client=ios,mweb",
        },
        # Strategy 3: Standard single stream fallback
        {
            "format": "best[height<=1080]/best",
            "extractor_args": "youtube:player_client=tv,web",
        },
    ]

    last_error = ""

    for attempt, strat in enumerate(strategies, start=1):
        logger.info(
            f"Downloading slice (attempt {attempt}/3): {start_time:.2f}s to {end_time:.2f}s "
            f"(duration: {duration:.2f}s) from {clean_url}"
        )

        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--download-sections",
            section_arg,
            "--force-keyframes-at-cuts",
            "-f",
            strat["format"],
            "--extractor-args",
            strat["extractor_args"],
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--merge-output-format",
            "mp4",
            "--no-playlist",
            "--no-warnings",
            "-o",
            str(dest_path),
            clean_url,
        ]

        logger.info(f"Running yt-dlp command: {' '.join(cmd)}")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )

        # Check if output file was created and is non-empty
        actual_file = dest_path
        if not actual_file.exists():
            candidates = list(dest_path.parent.glob(f"{dest_path.stem}*"))
            if candidates and candidates[0].stat().st_size > 5000:
                actual_file = candidates[0]

        if actual_file.exists() and actual_file.stat().st_size > 10000:
            # Succeeded! Rename to dest_path if needed
            if actual_file != dest_path:
                shutil.move(str(actual_file), str(dest_path))
            break
        else:
            last_error = (proc.stderr or proc.stdout)[-500:]
            logger.warning(
                f"Attempt {attempt}/3 failed with code {proc.returncode}. "
                f"Waiting 2s before retry with alternative client..."
            )
            time.sleep(2.0)
    else:
        # All 3 attempts failed
        raise RuntimeError(
            f"yt-dlp partial download failed after 3 attempts.\n"
            f"Last error details:\n{last_error}"
        )

    # Verify integrity with ffprobe
    probe_data = probe_video(dest_path)
    streams = probe_data.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    file_size = dest_path.stat().st_size
    logger.info(
        f"Slice verified: size={file_size:,} bytes, "
        f"has_video={has_video}, has_audio={has_audio}"
    )

    if not has_video:
        raise ValueError(f"Downloaded slice has no video stream: {dest_path}")

    return str(dest_path)
