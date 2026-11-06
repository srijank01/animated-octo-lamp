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


def extract_video_heatmap_peaks(
    source_url_or_id: str,
    top_n: int = 3,
    min_separation_sec: float = 30.0,
) -> list[dict[str, Any]]:
    """Extract YouTube audience retention heatmap/replay peaks using yt-dlp.

    Returns the top N highest-intensity viewer replay timestamp ranges,
    enforcing a minimum time separation between peaks to ensure diverse moments.
    Safely catches any exceptions and returns an empty list if heatmap data
    is unavailable or unparseable.

    Args:
        source_url_or_id: YouTube URL or 11-char video ID.
        top_n: Number of peak moments to return (default: 3).
        min_separation_sec: Minimum spacing in seconds between chosen peak centers.

    Returns:
        List of dicts: [
            {
                "start_time": float,
                "end_time": float,
                "peak_time": float,
                "intensity": float,
                "display": str,
            }, ...
        ]
    """
    clean_url = source_url_or_id.strip()
    if "?si=" in clean_url:
        clean_url = clean_url.split("?si=")[0]
    elif "&si=" in clean_url:
        clean_url = clean_url.split("&si=")[0]

    if len(clean_url) == 11 and not clean_url.startswith("http"):
        clean_url = f"https://www.youtube.com/watch?v={clean_url}"

    try:
        import yt_dlp
    except ImportError:
        logger.warning("yt_dlp module not found; skipping heatmap extraction.")
        return []

    ydl_opts = {
        "extract_flat": False,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            heatmap = info.get("heatmap")
            if not heatmap or not isinstance(heatmap, list):
                logger.info(f"No retention heatmap available for {clean_url}")
                return []

            valid_buckets = [b for b in heatmap if b.get("value") is not None]
            if not valid_buckets:
                return []

            # Sort buckets by intensity descending
            sorted_buckets = sorted(
                valid_buckets,
                key=lambda b: float(b.get("value", 0.0)),
                reverse=True,
            )

            peaks: list[dict[str, Any]] = []
            for b in sorted_buckets:
                val = float(b.get("value", 0.0))
                s = float(b.get("start_time", 0.0))
                e = float(b.get("end_time", 0.0))
                mid = (s + e) / 2.0

                # Enforce minimum separation from already chosen peaks
                if any(abs(mid - p["peak_time"]) < min_separation_sec for p in peaks):
                    continue

                # Expand to adjacent buckets that are within 85% of peak intensity (max +/- 12s)
                b_idx = heatmap.index(b)
                range_start = s
                range_end = e
                threshold = val * 0.85

                l_idx = b_idx - 1
                while (
                    l_idx >= 0
                    and float(heatmap[l_idx].get("value", 0.0)) >= threshold
                    and (s - float(heatmap[l_idx].get("start_time", 0.0))) <= 12.0
                ):
                    range_start = float(heatmap[l_idx].get("start_time", range_start))
                    l_idx -= 1

                r_idx = b_idx + 1
                while (
                    r_idx < len(heatmap)
                    and float(heatmap[r_idx].get("value", 0.0)) >= threshold
                    and (float(heatmap[r_idx].get("end_time", 0.0)) - e) <= 12.0
                ):
                    range_end = float(heatmap[r_idx].get("end_time", range_end))
                    r_idx += 1

                m_s, s_s = int(range_start // 60), int(range_start % 60)
                m_e, s_e = int(range_end // 60), int(range_end % 60)
                intensity_pct = int(round(val * 100)) if val <= 1.0 else int(round(val))

                peaks.append({
                    "start_time": round(range_start, 2),
                    "end_time": round(range_end, 2),
                    "peak_time": round(mid, 2),
                    "intensity": round(val, 3),
                    "display": (
                        f"{m_s:02d}:{s_s:02d} - {m_e:02d}:{s_e:02d} "
                        f"({range_start:.1f}s - {range_end:.1f}s, peak: {mid:.1f}s, intensity: {intensity_pct}%)"
                    ),
                })

                if len(peaks) >= top_n:
                    break

            logger.info(f"Extracted {len(peaks)} heatmap peaks for {clean_url}: {[p['display'] for p in peaks]}")
            return peaks

    except Exception as exc:
        logger.warning(f"Could not extract heatmap for {clean_url}: {exc}")
        return []


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

    # Try different format and client strategies across retries to prevent 403 Forbidden.
    # Capped strictly to 1080p max to avoid downloading and decoding massive 4K/1440p streams.
    strategies = [
        # Strategy 1: Default yt-dlp client negotiation capped at 1080p (fastest, most reliable)
        {
            "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080][ext=mp4]/best",
            "extractor_args": None,
        },
        # Strategy 2: TV client fallback capped at 1080p
        {
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "extractor_args": "youtube:player_client=tv",
        },
        # Strategy 3: Standard single stream fallback capped at 1080p
        {
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "extractor_args": "youtube:player_client=web",
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
        ]
        if strat.get("extractor_args"):
            cmd.extend(["--extractor-args", strat["extractor_args"]])
        cmd.extend([
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
        ])

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
