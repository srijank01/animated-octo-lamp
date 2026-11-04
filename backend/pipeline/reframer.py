"""Smart 9:16 vertical video reframer using OpenCV and FFmpeg.

Detects active speakers using OpenCV face detection, applies trajectory smoothing,
supports 2-speaker podcast split-screen mode, and produces crisp 1080x1920 (9:16)
vertical videos formatted for YouTube Shorts / Reels.
Includes blurred-pillar background fallback for wide scenes or slides.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def analyze_speaker_center_x(
    video_path: str | Path,
    sample_rate_fps: int = 2,
) -> dict[str, Any]:
    """Sample frames from video to track speaker faces and detect layout opportunities.

    Detects:
    - Single speaker center_x smoothed trajectory
    - 2-speaker podcast split-screen mode (2 distinct faces separated by > 25% width)

    Args:
        video_path: Path to the input video file.
        sample_rate_fps: How many frames per second to sample for face detection.

    Returns:
        Dictionary with video dimensions, face detection statistics, layout recommendation,
        and coordinates for single speaker or dual-speaker split-screen.
    """
    path_str = str(video_path)
    cap = cv2.VideoCapture(path_str)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    classifier = cv2.CascadeClassifier(cascade_path)
    if classifier.empty():
        raise RuntimeError("Failed to load OpenCV Haar Cascade face classifier.")

    sample_step = max(1, int(round(fps / max(1, sample_rate_fps))))
    default_center_x = frame_width / 2.0
    last_known_center = default_center_x

    samples: list[dict[str, Any]] = []
    face_detected_count = 0
    two_faces_count = 0
    sampled_frame_count = 0
    frame_idx = 0

    left_speaker_centers: list[float] = []
    right_speaker_centers: list[float] = []

    min_face_sep = frame_width * 0.25

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_step == 0:
            sampled_frame_count += 1
            timestamp = round(frame_idx / fps, 2)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)

            min_size = (max(24, int(frame_height * 0.08)), max(24, int(frame_height * 0.08)))
            faces = classifier.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=4,
                minSize=min_size,
            )

            is_two_faces = False
            if len(faces) >= 2:
                # Sort top 2 faces by area
                top2 = sorted(faces, key=lambda b: b[2] * b[3], reverse=True)[:2]
                c1_x = float(top2[0][0] + top2[0][2] / 2.0)
                c2_x = float(top2[1][0] + top2[1][2] / 2.0)
                left_x, right_x = min(c1_x, c2_x), max(c1_x, c2_x)

                if (right_x - left_x) >= min_face_sep:
                    is_two_faces = True
                    two_faces_count += 1
                    left_speaker_centers.append(left_x)
                    right_speaker_centers.append(right_x)

            if len(faces) > 0:
                face_detected_count += 1
                largest = max(faces, key=lambda b: b[2] * b[3])
                fx, fy, fw, fh = largest
                current_center = float(fx + fw / 2.0)
                last_known_center = current_center
                detected = True
            else:
                current_center = last_known_center
                detected = False

            samples.append({
                "time": timestamp,
                "frame_idx": frame_idx,
                "center_x": current_center,
                "face_detected": detected,
                "two_faces": is_two_faces,
            })

        frame_idx += 1

    cap.release()

    if not samples:
        return {
            "frame_width": frame_width,
            "frame_height": frame_height,
            "fps": fps,
            "total_frames": total_frames,
            "face_detected_ratio": 0.0,
            "two_faces_ratio": 0.0,
            "recommended_center_x": default_center_x,
            "recommended_layout": "blurred_background",
            "samples": [],
        }

    # Smoothing and deadband filter
    smoothed_samples: list[dict[str, Any]] = []
    ema_center = samples[0]["center_x"]
    alpha = 0.25
    deadband_threshold = frame_width * 0.03

    for s in samples:
        raw_x = s["center_x"]
        if abs(raw_x - ema_center) > deadband_threshold:
            ema_center = alpha * raw_x + (1 - alpha) * ema_center

        smoothed_samples.append({
            "time": s["time"],
            "raw_center_x": round(raw_x, 2),
            "smoothed_center_x": round(ema_center, 2),
            "face_detected": s["face_detected"],
            "two_faces": s["two_faces"],
        })

    detected_centers = [s["raw_center_x"] for s in smoothed_samples if s["face_detected"]]
    recommended_center = float(np.median(detected_centers)) if detected_centers else default_center_x

    face_ratio = face_detected_count / max(1, sampled_frame_count)
    two_faces_ratio = two_faces_count / max(1, sampled_frame_count)

    # Determine recommended layout
    if two_faces_ratio >= 0.30 and frame_width > frame_height:
        recommended_layout = "split_screen"
    elif face_ratio >= 0.10 and frame_width > frame_height:
        recommended_layout = "smart_crop"
    elif frame_width == 1080 and frame_height == 1920:
        recommended_layout = "passthrough"
    else:
        recommended_layout = "blurred_background"

    speaker1_x = float(np.median(left_speaker_centers)) if left_speaker_centers else (frame_width * 0.30)
    speaker2_x = float(np.median(right_speaker_centers)) if right_speaker_centers else (frame_width * 0.70)

    logger.info(
        f"Speaker Tracking: sampled {sampled_frame_count} frames, "
        f"face in {face_detected_count} ({face_ratio:.1%}), "
        f"two faces in {two_faces_count} ({two_faces_ratio:.1%}) -> Layout: '{recommended_layout}'"
    )

    return {
        "frame_width": frame_width,
        "frame_height": frame_height,
        "fps": fps,
        "total_frames": total_frames,
        "face_detected_ratio": round(face_ratio, 3),
        "two_faces_ratio": round(two_faces_ratio, 3),
        "recommended_center_x": round(recommended_center, 2),
        "speaker1_center_x": round(speaker1_x, 2),
        "speaker2_center_x": round(speaker2_x, 2),
        "recommended_layout": recommended_layout,
        "samples": smoothed_samples,
    }


def reframe_to_vertical(
    input_video_path: str | Path,
    output_video_path: str | Path,
    mode: str = "auto",
    return_info: bool = False,
) -> str | tuple[str, dict[str, Any]]:
    """Convert a video to a crisp 1080x1920 (9:16) vertical MP4 with speaker tracking.

    Supports:
    - 'smart_crop': Centered 9:16 crop tracking single speaker face
    - 'split_screen': 2-speaker podcast split-screen (top/bottom halves + 4px divider)
    - 'blurred_background': High quality blurred canvas fallback for wide shots / slides
    - 'passthrough': Direct copy if video is already 1080x1920

    Args:
        input_video_path: Path to input horizontal video.
        output_video_path: Destination path for vertical output MP4.
        mode: Reframing mode ('auto', 'smart_crop', 'split_screen', or 'blurred_background').
        return_info: Whether to return a tuple (path, info_dict).

    Returns:
        Absolute path to the reframed 1080x1920 video (or tuple if return_info=True).
    """
    in_path = Path(input_video_path).resolve()
    out_path = Path(output_video_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not in_path.exists():
        raise FileNotFoundError(f"Input video not found: {in_path}")

    analysis = analyze_speaker_center_x(in_path)
    frame_w = analysis["frame_width"]
    frame_h = analysis["frame_height"]
    center_x = analysis["recommended_center_x"]
    speaker1_x = analysis.get("speaker1_center_x", frame_w * 0.3)
    speaker2_x = analysis.get("speaker2_center_x", frame_w * 0.7)

    chosen_mode = analysis["recommended_layout"] if mode == "auto" else mode
    logger.info(f"Reframing '{in_path.name}' to vertical using mode: '{chosen_mode}'")

    if chosen_mode == "split_screen":
        # 2-Speaker Vertical Split-Screen (1080x1920)
        # Top half: 1080x960 (ratio 9:8), Bottom half: 1080x960 (ratio 9:8)
        crop_h = min(frame_h, int(frame_h * 0.95))
        crop_h = crop_h - (crop_h % 2)
        crop_w = int(crop_h * 9.0 / 8.0)
        crop_w = crop_w - (crop_w % 2)
        if crop_w > frame_w:
            crop_w = frame_w - (frame_w % 2)
            crop_h = int(crop_w * 8.0 / 9.0)
            crop_h = crop_h - (crop_h % 2)

        # Speaker 1 (top half, left speaker)
        x1 = int(round(speaker1_x - crop_w / 2.0))
        x1 = max(0, min(x1, frame_w - crop_w))
        x1 = x1 - (x1 % 2)

        # Speaker 2 (bottom half, right speaker)
        x2 = int(round(speaker2_x - crop_w / 2.0))
        x2 = max(0, min(x2, frame_w - crop_w))
        x2 = x2 - (x2 % 2)

        y_off = max(0, (frame_h - crop_h) // 2)

        filter_str = (
            f"[0:v]crop={crop_w}:{crop_h}:{x1}:{y_off},scale=1080:960:flags=lanczos,setsar=1[top];"
            f"[0:v]crop={crop_w}:{crop_h}:{x2}:{y_off},scale=1080:960:flags=lanczos,setsar=1[bot];"
            f"[top][bot]vstack[stacked];"
            f"[stacked]drawbox=x=0:y=958:w=1080:h=4:color=0x18181b@1.0:t=fill[v]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(in_path),
            "-filter_complex",
            filter_str,
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
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            str(out_path),
        ]

    elif chosen_mode == "smart_crop":
        # Single Speaker Centered 9:16 Crop
        crop_w = int(frame_h * 9.0 / 16.0)
        crop_w = crop_w - (crop_w % 2)
        crop_h = frame_h - (frame_h % 2)

        crop_x = int(round(center_x - crop_w / 2.0))
        crop_x = max(0, min(crop_x, frame_w - crop_w))
        crop_x = crop_x - (crop_x % 2)

        filter_str = f"crop={crop_w}:{crop_h}:{crop_x}:0,scale=1080:1920:flags=lanczos,setsar=1"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(in_path),
            "-vf",
            filter_str,
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
            "-ar",
            "44100",
            str(out_path),
        ]

    elif chosen_mode == "passthrough":
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(in_path),
            "-c",
            "copy",
            str(out_path),
        ]

    else:
        # Blurred background canvas fallback
        filter_str = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=20:10,setsar=1[bg];"
            "[0:v]scale=1080:-2:force_original_aspect_ratio=decrease,setsar=1[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(in_path),
            "-filter_complex",
            filter_str,
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
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            str(out_path),
        ]

    logger.info(f"Executing FFmpeg reframe ({chosen_mode}): {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg vertical reframing failed with return code {result.returncode}.\n"
            f"Stderr:\n{result.stderr[-500:]}"
        )

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise FileNotFoundError(f"Reframed video was not created at: {out_path}")

    info = {
        "layout_mode": chosen_mode,
        "face_detected_ratio": analysis["face_detected_ratio"],
        "two_faces_ratio": analysis["two_faces_ratio"],
        "center_x": center_x,
    }

    if return_info:
        return str(out_path), info
    return str(out_path)
