"""Cinematic Blur Fill 9:16 Vertical Video Reframer using FFmpeg.

Replaces AI face cropping with a cinematic letterbox approach:
1. Background Stream ([bg]): Original video scaled and cropped to fill 1080x1920,
   heavily blurred with boxblur to create an aesthetic ambient backdrop.
2. Foreground Stream ([fg]): Original video scaled to 1080px width while preserving
   its native aspect ratio (1080x608 for 16:9 content).
3. Overlay: Centers the foreground video vertically: overlay=0:(H-h)/2.
"""

import json
import logging
import platform
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HAS_VIDEOTOOLBOX: bool | None = None


def has_videotoolbox() -> bool:
    """Check if Apple Silicon / macOS VideoToolbox H.264 hardware encoder is available."""
    global _HAS_VIDEOTOOLBOX
    if _HAS_VIDEOTOOLBOX is not None:
        return _HAS_VIDEOTOOLBOX
    if platform.system() != "Darwin":
        _HAS_VIDEOTOOLBOX = False
        return False
    try:
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
        )
        _HAS_VIDEOTOOLBOX = "h264_videotoolbox" in res.stdout
    except Exception:
        _HAS_VIDEOTOOLBOX = False
    return _HAS_VIDEOTOOLBOX


def get_h264_encoder_args(bitrate: str = "8M") -> list[str]:
    """Return hardware-accelerated VideoToolbox encoder args or fast libx264 fallback."""
    if has_videotoolbox():
        return ["-c:v", "h264_videotoolbox", "-b:v", bitrate]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]


def probe_video_dimensions(file_path: str | Path) -> tuple[int, int]:
    """Inspect video width and height using ffprobe without OpenCV."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(file_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if streams:
                w = int(streams[0].get("width", 0))
                h = int(streams[0].get("height", 0))
                if w > 0 and h > 0:
                    return w, h
    except Exception as exc:
        logger.warning(f"Could not probe video dimensions for {file_path}: {exc}")

    return 1920, 1080


def analyze_speaker_center_x(
    video_path: str | Path,
    sample_rate_fps: int = 2,
) -> dict[str, Any]:
    """Backward-compatible stub for legacy scripts.

    Face tracking and crop panning have been replaced by cinematic Blur Fill reframing.
    """
    w, h = probe_video_dimensions(video_path)
    return {
        "frame_width": w,
        "frame_height": h,
        "fps": 30.0,
        "total_frames": 0,
        "face_detected_ratio": 0.0,
        "two_faces_ratio": 0.0,
        "recommended_center_x": w / 2.0,
        "recommended_layout": "blur_fill",
        "samples": [],
    }


def reframe_to_vertical(
    input_video_path: str | Path,
    output_video_path: str | Path,
    mode: str = "blur_fill",
    return_info: bool = False,
) -> str | tuple[str, dict[str, Any]]:
    """Convert a video to a cinematic 1080x1920 (9:16) vertical MP4 using FFmpeg Blur Fill.

    Architecture:
    - Background: Original video scaled and cropped to 1080x1920 with heavy boxblur.
    - Foreground: Original 16:9 footage scaled to width 1080 (maintaining aspect ratio with lanczos).
    - Composition: Foreground centered vertically at overlay=0:(H-h)/2.
    - Subtitle Safe Zone: Subtitles sit in the lower third blurred zone below the 16:9 video.

    Args:
        input_video_path: Path to input horizontal or arbitrary video.
        output_video_path: Destination path for vertical output MP4.
        mode: Reframing mode (default: 'blur_fill').
        return_info: Whether to return a tuple (path, info_dict).

    Returns:
        Absolute path to reframed 1080x1920 MP4 (or tuple if return_info=True).
    """
    in_path = Path(input_video_path).resolve()
    out_path = Path(output_video_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not in_path.exists():
        raise FileNotFoundError(f"Input video not found: {in_path}")

    frame_w, frame_h = probe_video_dimensions(in_path)
    logger.info(f"Reframing '{in_path.name}' ({frame_w}x{frame_h}) to 1080x1920 via Cinematic Blur Fill")

    # If already native 1080x1920 vertical video, passthrough
    if frame_w == 1080 and frame_h == 1920:
        logger.info("Video is already 1080x1920 vertical canvas. Performing passthrough copy.")
        cmd = ["ffmpeg", "-y", "-i", str(in_path), "-c", "copy", str(out_path)]
        subprocess.run(cmd, capture_output=True, check=True)
        info = {
            "layout_mode": "passthrough",
            "frame_width": 1080,
            "frame_height": 1920,
        }
        return (str(out_path), info) if return_info else str(out_path)

    # Optimized FFmpeg Blur Fill Filter Complex:
    # 1. [bg]: Downscale background stream to 360:640, apply boxblur=12:12, then scale up
    #    to 1080x1920. This reduces mathematical blur load by >80% while retaining ambient aesthetic.
    # 2. [fg]: Scale original to 1080px width maintaining aspect ratio with lanczos
    # 3. Overlay: Centered vertically at 0:(H-h)/2
    filter_complex = (
        "[0:v]scale=360:640:force_original_aspect_ratio=increase,"
        "crop=360:640,boxblur=12:12,scale=1080:1920:flags=bicubic,setsar=1[bg];"
        "[0:v]scale=1080:-2:flags=lanczos,setsar=1[fg];"
        "[bg][fg]overlay=0:(H-h)/2[v]"
    )

    encoder_args = get_h264_encoder_args("8M")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(in_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        *encoder_args,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        str(out_path),
    ]

    logger.info(f"Executing FFmpeg Blur Fill reframe: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg vertical Blur Fill reframing failed with return code {result.returncode}.\n"
            f"Stderr:\n{result.stderr[-500:]}"
        )

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise FileNotFoundError(f"Reframed video was not created at: {out_path}")

    info = {
        "layout_mode": "passthrough" if (frame_w == 1080 and frame_h == 1920) else (mode if mode == "split_screen" else "blur_fill"),
        "source_width": frame_w,
        "source_height": frame_h,
        "target_width": 1080,
        "target_height": 1920,
    }

    if return_info:
        return str(out_path), info
    return str(out_path)
