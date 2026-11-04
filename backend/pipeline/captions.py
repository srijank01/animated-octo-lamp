"""Viral Karaoke Subtitle Generator & High-Retention Burn-In Engine.

Generates dynamic ASS subtitle files with word-by-word active karaoke highlighting,
and burns styled captions into 1080x1920 vertical video using FFmpeg libass or Pillow fallback.
"""

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def format_ass_timestamp(seconds: float) -> str:
    """Format seconds into ASS timestamp format: H:MM:SS.cc"""
    safe_sec = max(0.0, float(seconds))
    cs = int(round(safe_sec * 100))
    c = cs % 100
    total_s = cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def group_words_into_chunks(
    words: list[dict[str, Any]],
    min_words: int = 1,
    max_words: int = 3,
    max_chars: int = 14,
    pause_threshold: float = 0.30,
) -> list[list[dict[str, Any]]]:
    """Group words into short, high-retention chunks (1-3 words, max 14 chars).

    Ensures that subtitle text never overflows the 1080px vertical screen width
    even with large bold viral typography. Breaks on punctuation, audio pauses,
    or character budget limits.
    """
    if not words:
        return []

    chunks: list[list[dict[str, Any]]] = []
    current_chunk: list[dict[str, Any]] = []
    current_chars = 0

    for i, w in enumerate(words):
        word_text = str(w["word"]).strip()
        word_len = len(word_text)

        # Pause duration between this word and the next
        next_pause = 0.0
        if i + 1 < len(words):
            next_pause = float(words[i + 1]["start"]) - float(w["end"])

        ends_sentence = any(word_text.endswith(p) for p in [".", "!", "?"])
        ends_clause = any(word_text.endswith(p) for p in [",", ";", ":", "—", "-"])

        projected_chars = current_chars + (1 if current_chars > 0 else 0) + word_len

        # Check if adding this word exceeds limits
        reached_word_limit = len(current_chunk) >= max_words
        reached_char_limit = projected_chars > max_chars and len(current_chunk) >= 1
        natural_break = len(current_chunk) >= min_words and (ends_clause or next_pause > pause_threshold)

        if current_chunk and (reached_word_limit or reached_char_limit or natural_break):
            chunks.append(current_chunk)
            current_chunk = [w]
            current_chars = word_len
        else:
            current_chunk.append(w)
            current_chars = projected_chars

        if ends_sentence and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def generate_ass_subtitles(
    words: list[dict[str, Any]],
    output_ass_path: str | Path,
    resolution: tuple[int, int] = (1080, 1920),
    font_name: str = "Arial Black",
    font_size: int = 58,
    highlight_color: str = "&H0000D7FF&",  # Viral Gold/Yellow (BGR)
    primary_color: str = "&H00FFFFFF&",    # Crisp White (BGR)
    outline_color: str = "&H00000000&",    # Solid Black (BGR)
    margin_v: int = 420,                   # Safe zone above bottom controls
) -> str:
    """Generate an Advanced SubStation Alpha (.ass) file with dynamic karaoke highlights.

    Args:
        words: List of dicts with 'word', 'start', 'end'.
        output_ass_path: Path to save the generated .ass file.
        resolution: (width, height) tuple, default (1080, 1920).
        font_name: Sans-serif font family.
        font_size: Point size for captions (default: 58, optimized for 1080x1920 safe zone).
        highlight_color: ASS color code for active word.
        primary_color: ASS color code for inactive words.
        outline_color: ASS color code for text outline.
        margin_v: Vertical margin from bottom (safe zone).

    Returns:
        Absolute path to the generated .ass file.
    """
    out_path = Path(output_ass_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    play_res_x, play_res_y = resolution
    chunks = group_words_into_chunks(words, min_words=1, max_words=3, max_chars=14)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{font_name},{font_size},{primary_color},{highlight_color},{outline_color},&H80000000,-1,0,0,0,100,100,1,0,1,4.5,2.5,2,90,90,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines: list[str] = []

    for chunk in chunks:
        chunk_words = [str(w["word"]).strip().upper() for w in chunk]
        total_in_chunk = len(chunk)

        for active_idx, active_item in enumerate(chunk):
            w_start = format_ass_timestamp(active_item["start"])
            
            # If this is the last word in the chunk, keep on screen slightly or until word end
            w_end = format_ass_timestamp(active_item["end"])

            # Avoid zero-duration events
            if w_start == w_end:
                w_end = format_ass_timestamp(float(active_item["end"]) + 0.1)

            # Build line text with active word highlighted and scaled by +8%
            formatted_tokens = []
            for idx, token in enumerate(chunk_words):
                if idx == active_idx:
                    # Active word in Viral Yellow with subtle pop-in scaling (\fscx108\fscy108)
                    highlighted = (
                        f"{{\\c{highlight_color}\\fscx108\\fscy108}}"
                        f"{token}"
                        f"{{\\c{primary_color}\\fscx100\\fscy100}}"
                    )
                    formatted_tokens.append(highlighted)
                else:
                    formatted_tokens.append(token)

            line_text = " ".join(formatted_tokens)
            dialogue_lines.append(
                f"Dialogue: 0,{w_start},{w_end},Karaoke,,0,0,0,,{line_text}"
            )

    full_content = header + "\n".join(dialogue_lines) + "\n"
    out_path.write_text(full_content, encoding="utf-8")
    logger.info(f"Generated dynamic karaoke ASS subtitles at: {out_path} ({len(dialogue_lines)} events)")
    return str(out_path)


def get_system_font(font_size: int = 58) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Find and load an available bold sans-serif font for Pillow."""
    candidate_fonts = [
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Black.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for font_path in candidate_fonts:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, font_size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_captions_pillow_fallback(
    input_video_path: str | Path,
    words: list[dict[str, Any]],
    output_video_path: str | Path,
    resolution: tuple[int, int] = (1080, 1920),
) -> str:
    """Fallback frame-by-frame subtitle burn-in using Pillow and FFmpeg pipe."""
    in_path = Path(input_video_path).resolve()
    out_path = Path(output_video_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Using Pillow frame-by-frame renderer fallback...")

    # Probe input video FPS and duration
    probe_cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,duration:format=duration",
        "-of", "json", str(in_path)
    ]
    probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    probe_info = json.loads(probe_res.stdout)
    fps_str = probe_info.get("streams", [{}])[0].get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = map(float, fps_str.split("/"))
        fps = num / den if den != 0 else 30.0
    else:
        fps = float(fps_str)

    width, height = resolution
    chunks = group_words_into_chunks(words, min_words=1, max_words=3, max_chars=14)
    font = get_system_font(58)

    # Build timeline lookup of active lines
    timeline_events = []
    for chunk in chunks:
        chunk_words = [str(w["word"]).strip().upper() for w in chunk]
        for active_idx, active_item in enumerate(chunk):
            timeline_events.append({
                "start": float(active_item["start"]),
                "end": float(active_item["end"]),
                "words": chunk_words,
                "active_idx": active_idx,
            })

    # FFmpeg reader (raw video out)
    read_cmd = [
        "ffmpeg", "-i", str(in_path),
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-"
    ]
    # FFmpeg writer (raw video in + audio from input)
    write_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}", "-pix_fmt", "bgr24",
        "-r", str(fps), "-i", "-",
        "-i", str(in_path),
        "-map", "0:v", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(out_path)
    ]

    read_proc = subprocess.Popen(read_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    write_proc = subprocess.Popen(write_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    frame_bytes = width * height * 3
    frame_idx = 0
    margin_v = 420

    while True:
        raw_frame = read_proc.stdout.read(frame_bytes)
        if not raw_frame or len(raw_frame) < frame_bytes:
            break

        current_time = frame_idx / fps

        # Find active event
        active_ev = None
        for ev in timeline_events:
            if ev["start"] <= current_time <= ev["end"] + 0.1:
                active_ev = ev
                break

        if active_ev:
            # Render using PIL
            img = Image.frombytes("RGB", (width, height), raw_frame, "raw", "BGR")
            draw = ImageDraw.Draw(img)

            full_text = " ".join(active_ev["words"])
            bbox = draw.textbbox((0, 0), full_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            start_x = max(60, (width - text_w) / 2)
            start_y = height - margin_v - text_h

            # Draw word by word
            curr_x = start_x
            for idx, w_tok in enumerate(active_ev["words"]):
                is_active = (idx == active_ev["active_idx"])
                color = (255, 215, 0) if is_active else (255, 255, 255)
                # Draw thick black outline
                for ox in (-4, 0, 4):
                    for oy in (-4, 0, 4):
                        if ox != 0 or oy != 0:
                            draw.text((curr_x + ox, start_y + oy), w_tok, font=font, fill=(0, 0, 0))
                draw.text((curr_x, start_y), w_tok, font=font, fill=color)
                w_bbox = draw.textbbox((0, 0), w_tok + " ", font=font)
                curr_x += (w_bbox[2] - w_bbox[0])

            raw_frame = img.tobytes("raw", "BGR")

        write_proc.stdin.write(raw_frame)
        frame_idx += 1

    read_proc.stdout.close()
    read_proc.wait()
    write_proc.stdin.close()
    write_proc.wait()

    return str(out_path)


def burn_captions(
    input_vertical_video: str | Path,
    words: list[dict[str, Any]],
    ass_path: str | Path,
    output_final_video: str | Path,
) -> str:
    """Burn dynamic word-by-word karaoke captions into a vertical video.

    Attempts native FFmpeg libass filter first, falling back to Pillow frame renderer
    if libass encounters path/font errors.

    Args:
        input_vertical_video: Path to input 1080x1920 MP4.
        words: List of word timestamp dicts.
        ass_path: Path to .ass subtitle file (will generate if not existing).
        output_final_video: Path to output final captioned MP4.

    Returns:
        Absolute path to the final captioned MP4 video.
    """
    in_path = Path(input_vertical_video).resolve()
    out_path = Path(output_final_video).resolve()
    sub_path = Path(ass_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not in_path.exists():
        raise FileNotFoundError(f"Input vertical video not found: {in_path}")

    # Generate ASS file if not present
    if not sub_path.exists():
        generate_ass_subtitles(words, sub_path)

    # Escape path characters for FFmpeg filter graph
    escaped_sub_path = str(sub_path).replace("\\", "/").replace(":", "\\:")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(in_path),
        "-vf",
        f"ass='{escaped_sub_path}'",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "copy",
        str(out_path),
    ]

    logger.info(f"Burning captions using FFmpeg libass: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        logger.warning(
            f"FFmpeg libass burning failed (code {result.returncode}): "
            f"{result.stderr[-300:]}\nTriggering Pillow fallback renderer..."
        )
        return render_captions_pillow_fallback(in_path, words, out_path)

    if not out_path.exists() or out_path.stat().st_size == 0:
        logger.warning("Burned output file missing. Triggering Pillow fallback renderer...")
        return render_captions_pillow_fallback(in_path, words, out_path)

    logger.info(f"Successfully burned captions to: {out_path} ({out_path.stat().st_size:,} bytes)")
    return str(out_path)

