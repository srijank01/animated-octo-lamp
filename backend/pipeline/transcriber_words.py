"""Word-level audio transcription and timestamp extraction using faster-whisper.

Extracts 16kHz audio from a sliced video clip and generates precise word-by-word
timestamps aligned to the clip's local timeline (0.0s to duration).
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Cache model instance so subsequent clip transcriptions are instantaneous
_WHISPER_MODEL = None


def get_whisper_model(model_size: str = "tiny") -> Any:
    """Initialize or retrieve the cached Faster-Whisper model."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel
        logger.info(f"Loading faster-whisper model '{model_size}' (CPU/int8)...")
        _WHISPER_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def load_audio_pcm_ffmpeg(file_path: str | Path, sr: int = 16000) -> np.ndarray:
    """Extract and resample audio to 16kHz mono float32 array via FFmpeg subprocess.

    Avoids PyAV container compatibility issues across differing platforms.
    """
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-threads", "0",
        "-i", str(file_path),
        "-f", "s16le",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        "-ar", str(sr),
        "-"
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {proc.stderr.decode('utf-8', errors='replace')}")

    audio_data = np.frombuffer(proc.stdout, dtype=np.int16).flatten().astype(np.float32) / 32768.0
    return audio_data


def extract_word_timestamps(
    video_path: str | Path,
    clip_metadata: dict[str, Any] | None = None,
    model_size: str = "tiny",
) -> list[dict[str, Any]]:
    """Extract word-level timestamps for a sliced video clip.

    Args:
        video_path: Path to the sliced video file.
        clip_metadata: Optional dictionary with clip info (e.g. title, expected duration).
        model_size: Faster-Whisper model name ('tiny', 'base', 'small').

    Returns:
        List of dicts: [{'word': str, 'start': float, 'end': float}, ...]
        All timestamps are relative to 0.0s of this specific clip.
    """
    in_path = Path(video_path).resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"Video file not found: {in_path}")

    # Load audio array via FFmpeg
    audio_arr = load_audio_pcm_ffmpeg(in_path, sr=16000)
    if len(audio_arr) == 0:
        raise ValueError(f"Extracted empty audio stream from: {in_path}")

    model = get_whisper_model(model_size)
    segments, info = model.transcribe(
        audio_arr,
        word_timestamps=True,
        language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=250),
    )

    raw_words: list[dict[str, Any]] = []
    for segment in segments:
        if segment.words:
            for word_obj in segment.words:
                w_text = word_obj.word.strip()
                if w_text:
                    raw_words.append({
                        "word": w_text,
                        "start": float(word_obj.start),
                        "end": float(word_obj.end),
                    })
        else:
            # Fallback if segment has no word breakdown: split by whitespace
            words_in_seg = segment.text.strip().split()
            if words_in_seg:
                seg_dur = max(0.2, float(segment.end - segment.start))
                per_word_dur = seg_dur / len(words_in_seg)
                for idx, w in enumerate(words_in_seg):
                    w_start = float(segment.start) + idx * per_word_dur
                    w_end = w_start + per_word_dur
                    raw_words.append({
                        "word": w.strip(),
                        "start": w_start,
                        "end": w_end,
                    })

    if not raw_words and clip_metadata and "hook_text" in clip_metadata:
        # Fallback to hook text proportional distribution
        logger.warning("Whisper returned 0 words. Falling back to hook text alignment.")
        hook = clip_metadata.get("hook_text", "")
        tokens = hook.split()
        dur = float(clip_metadata.get("duration", 30.0))
        token_dur = dur / max(1, len(tokens))
        for i, tok in enumerate(tokens):
            raw_words.append({
                "word": tok,
                "start": i * token_dur,
                "end": (i + 1) * token_dur,
            })

    # Ensure strictly monotonic timestamps, non-overlapping, with clean min durations
    cleaned_words: list[dict[str, Any]] = []
    prev_end = 0.0

    for item in raw_words:
        word_str = str(item["word"]).strip()
        if not word_str:
            continue

        raw_start = float(item["start"])
        raw_end = float(item["end"])

        # Monotonicity check
        start = max(prev_end, round(raw_start, 2))
        end = max(start + 0.08, round(raw_end, 2))
        prev_end = end

        cleaned_words.append({
            "word": word_str,
            "start": round(start, 2),
            "end": round(end, 2),
        })

    logger.info(
        f"Extracted {len(cleaned_words)} word timestamps from '{in_path.name}'. "
        f"Timeline: 0.00s to {prev_end:.2f}s"
    )

    return cleaned_words

