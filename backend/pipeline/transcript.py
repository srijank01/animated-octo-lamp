"""Transcript extraction module for YouTube videos.

Provides zero-download transcript retrieval using youtube-transcript-api
with a robust fallback to yt-dlp.
"""

import json
import logging
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    CouldNotRetrieveTranscript,
)

logger = logging.getLogger(__name__)


def extract_video_id(url: str) -> str:
    """Extract an 11-character YouTube video ID from various URL formats or raw ID.

    Supports:
    - Standard: https://www.youtube.com/watch?v=VIDEO_ID
    - Shortened: https://youtu.be/VIDEO_ID
    - Shorts: https://www.youtube.com/shorts/VIDEO_ID
    - Embed: https://www.youtube.com/embed/VIDEO_ID
    - Live: https://www.youtube.com/live/VIDEO_ID
    - Direct 11-char ID: VIDEO_ID
    """
    if not url:
        raise ValueError("URL cannot be empty")

    cleaned = url.strip()

    # Direct 11-character video ID
    if len(cleaned) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", cleaned):
        return cleaned

    # Common regex patterns for YouTube video URLs
    patterns = [
        r"(?:https?:\/\/)?(?:www\.|m\.)?youtube\.com\/watch\?(?:.*&)?v=([A-Za-z0-9_-]{11})",
        r"(?:https?:\/\/)?youtu\.be\/([A-Za-z0-9_-]{11})",
        r"(?:https?:\/\/)?(?:www\.|m\.)?youtube\.com\/(?:shorts|embed|live|v)\/([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return match.group(1)

    # Fallback parsing via urllib
    try:
        parsed = urllib.parse.urlparse(cleaned)
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" in qs and len(qs["v"][0]) == 11:
            return qs["v"][0]
    except Exception:
        pass

    raise ValueError(f"Could not extract a valid 11-character YouTube video ID from '{url}'")


def _fetch_with_youtube_transcript_api(video_id: str) -> list[dict[str, Any]]:
    """Attempt transcript fetch using youtube-transcript-api.

    Prefers manual English captions, falling back to auto-generated English,
    or any available English track.
    """
    english_codes = ["en", "en-US", "en-GB", "en-CA", "en-AU", "en-NZ", "en-IE"]

    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    transcript = None

    # 1. Prefer manually created English captions
    try:
        transcript = transcript_list.find_manually_created_transcript(english_codes)
    except Exception:
        pass

    # 2. Fallback to auto-generated English captions
    if not transcript:
        try:
            transcript = transcript_list.find_generated_transcript(english_codes)
        except Exception:
            pass

    # 3. Fallback to any transcript containing English
    if not transcript:
        try:
            transcript = transcript_list.find_transcript(english_codes)
        except Exception:
            pass

    # 4. Fallback to the first available transcript in any language
    if not transcript:
        for t in transcript_list:
            transcript = t
            break

    if not transcript:
        raise NoTranscriptFound(video_id, english_codes, transcript_list)

    fetched = transcript.fetch()

    # Convert FetchedTranscript to standard list of dicts
    if hasattr(fetched, "to_raw_data"):
        raw_items = fetched.to_raw_data()
    else:
        raw_items = [
            {"text": item.text, "start": item.start, "duration": item.duration}
            if hasattr(item, "text") else item
            for item in fetched
        ]

    normalized = []
    for item in raw_items:
        text = str(item.get("text", "")).strip().replace("\n", " ")
        if not text:
            continue
        start = round(float(item.get("start", 0.0)), 2)
        duration = round(float(item.get("duration", 0.0)), 2)
        end = round(start + duration, 2)
        normalized.append({
            "text": text,
            "start": start,
            "duration": duration,
            "end": end,
        })

    return normalized


def _fetch_with_ytdlp_fallback(video_id: str) -> list[dict[str, Any]]:
    """Fallback transcript extraction using `yt-dlp --skip-download --write-auto-sub`."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        outtmpl = str(Path(tmpdir) / "%(id)s.%(ext)s")
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--skip-download",
            "--write-auto-sub",
            "--write-subs",
            "--sub-lang",
            "en.*,en",
            "--sub-format",
            "vtt/srt/best",
            "--no-playlist",
            "--no-warnings",
            "-o",
            outtmpl,
            video_url,
        ]

        try:
            logger.info(f"Executing yt-dlp subtitle extraction for {video_id}...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except Exception as e:
            raise RuntimeError(f"yt-dlp subprocess execution failed: {e}")

        # Scan for downloaded subtitle files
        sub_files = list(Path(tmpdir).glob("*.vtt"))
        if not sub_files:
            sub_files = list(Path(tmpdir).glob("*.srt"))

        if not sub_files:
            sub_files = list(Path(tmpdir).glob("*.json3"))
            if sub_files:
                with open(sub_files[0], "r", encoding="utf-8") as f:
                    data = json.load(f)
                segments = []
                for ev in data.get("events", []):
                    if "segs" in ev:
                        text = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
                        if text:
                            start = round(float(ev.get("tStartMs", 0)) / 1000.0, 2)
                            dur = round(float(ev.get("dDurationMs", 0)) / 1000.0, 2)
                            segments.append({
                                "text": text,
                                "start": start,
                                "duration": dur,
                                "end": round(start + dur, 2),
                            })
                if segments:
                    return segments

        for sub_file in sub_files:
            content = sub_file.read_text(encoding="utf-8", errors="replace")
            if sub_file.name.endswith(".vtt"):
                segments = _parse_vtt(content)
                if segments:
                    return segments
            elif sub_file.name.endswith(".srt"):
                segments = _parse_srt(content)
                if segments:
                    return segments

        stderr_tail = (result.stderr or "")[-300:]
        raise RuntimeError(
            f"Failed to extract transcript using yt-dlp for video: {video_id}. "
            f"Exit code: {result.returncode}. Stderr: {stderr_tail}"
        )


def _parse_srt(srt_text: str) -> list[dict[str, Any]]:
    """Simple SubRip (SRT) parser to extract text and timestamp segments."""
    time_regex = re.compile(
        r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})"
    )

    def parse_sec(ts: str) -> float:
        ts = ts.replace(",", ".")
        h, m, s = ts.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    segments = []
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            match = time_regex.search(line)
            if match:
                start_s = round(parse_sec(match.group(1)), 2)
                end_s = round(parse_sec(match.group(2)), 2)
                text = " ".join(lines[idx + 1:]).strip()
                text = re.sub(r"<[^>]+>", "", text).replace("\n", " ").strip()
                if text:
                    segments.append({
                        "text": text,
                        "start": start_s,
                        "duration": round(end_s - start_s, 2),
                        "end": end_s,
                    })
                break
    return segments


def _parse_vtt(vtt_text: str) -> list[dict[str, Any]]:
    """Simple WebVTT parser to extract text and timestamp segments."""
    time_regex = re.compile(
        r"((?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*((?:\d{2}:)?\d{2}:\d{2}\.\d{3})"
    )

    def parse_sec(ts: str) -> float:
        parts = ts.strip().split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])

    segments = []
    lines = vtt_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = time_regex.search(line)
        if match:
            start_s = round(parse_sec(match.group(1)), 2)
            end_s = round(parse_sec(match.group(2)), 2)
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and not time_regex.search(lines[i]):
                # Remove VTT tags like <c> </c>
                clean_line = re.sub(r"<[^>]+>", "", lines[i]).strip()
                if clean_line:
                    text_lines.append(clean_line)
                i += 1
            text = " ".join(text_lines).strip()
            if text:
                segments.append({
                    "text": text,
                    "start": start_s,
                    "duration": round(end_s - start_s, 2),
                    "end": end_s,
                })
        else:
            i += 1

    return segments


def get_transcript(video_id: str) -> list[dict[str, Any]]:
    """Fetch video transcript using youtube-transcript-api with yt-dlp fallback.

    Args:
        video_id: 11-character YouTube video ID.

    Returns:
        List of dicts with keys: 'text', 'start', 'duration', 'end'.
    """
    clean_id = extract_video_id(video_id)

    try:
        segments = _fetch_with_youtube_transcript_api(clean_id)
        if segments:
            return segments
    except Exception as e:
        logger.warning(
            f"youtube-transcript-api failed for {clean_id}: {e}. Retrying with yt-dlp fallback..."
        )

    return _fetch_with_ytdlp_fallback(clean_id)


def format_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS string."""
    total_seconds = max(0, int(seconds))
    minutes = total_seconds // 60
    secs = total_seconds % 60
    return f"{minutes:02d}:{secs:02d}"


def format_transcript_for_llm(segments: list[dict[str, Any]]) -> str:
    """Format segments into clean text block with timestamps.

    Format: [MM:SS - MM:SS] (start_sec - end_sec): spoken text
    """
    lines = []
    for seg in segments:
        start = float(seg["start"])
        end = float(seg.get("end", start + seg.get("duration", 0.0)))
        text = str(seg.get("text", "")).strip().replace("\n", " ")
        if text:
            start_fmt = format_timestamp(start)
            end_fmt = format_timestamp(end)
            lines.append(f"[{start_fmt} - {end_fmt}] ({start:.2f}s - {end:.2f}s): {text}")
    return "\n".join(lines)
