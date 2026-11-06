"""Gemini LLM hook selection module for identifying viral video clips.

Uses the official google-genai SDK to analyze transcripts and extract
high-retention 30-60 second clips suitable for YouTube Shorts / Reels / TikTok.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, model_validator

# Automatically locate and load backend/.env or root .env
ENV_PATHS = [
    Path(__file__).resolve().parent.parent / ".env",
    Path.cwd() / ".env",
    Path.cwd() / "backend" / ".env",
]
for env_path in ENV_PATHS:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        break

logger = logging.getLogger(__name__)


class ClipSegment(BaseModel):
    """Pydantic schema representing an individual narrative sub-segment of a clip."""

    start_time: float = Field(
        description="Exact start timestamp of this sub-segment in seconds (from the transcript)"
    )
    end_time: float = Field(
        description="Exact end timestamp of this sub-segment in seconds (from the transcript)"
    )
    segment_role: str = Field(
        default="core_insight",
        description="Narrative role: 'cold_open_hook', 'story_setup', 'core_insight', or 'climax_payoff'",
    )

    @model_validator(mode="after")
    def validate_segment_bounds(self) -> "ClipSegment":
        """Ensure segment end is after start."""
        if self.end_time <= self.start_time:
            self.end_time = round(self.start_time + 5.0, 2)
        return self


class SocialMetadata(BaseModel):
    """Platform-tailored titles, descriptions, and hashtags for social media."""

    youtube_title: str = Field(
        description="High-CTR YouTube Shorts title under 95 characters ending with #Shorts"
    )
    youtube_description: str = Field(
        description="Engaging YouTube Shorts description with summary and 5 relevant hashtags"
    )
    youtube_tags: list[str] = Field(
        default_factory=list,
        description="5 to 8 SEO keywords without hashtag symbol"
    )
    instagram_caption: str = Field(
        description="Instagram Reels caption with hook, spacing, engagement question, and 5-8 hashtags"
    )
    tiktok_caption: str = Field(
        description="Punchy 1-line TikTok caption + 4 niche/trending tags"
    )


class ViralClip(BaseModel):
    """Pydantic schema representing a viral clip candidate, supporting multi-segment stitching."""

    title: str = Field(
        description="Catchy, click-worthy YouTube Shorts title that includes #Shorts"
    )
    hook_text: str = Field(
        description="The exact opening sentence or phrase that hooks the viewer in the first 3 seconds"
    )
    hook_strategy: str = Field(
        default="Pattern Interrupt",
        description="The psychological hook strategy employed (e.g., 'Curiosity Gap', 'Negative Premise', 'Counter-Intuitive Truth', 'Extreme Reaction', 'Pattern Interrupt') to seize attention in the first 3 seconds.",
    )
    peak_moment: str = Field(
        default="Core Climax Payoff",
        description="The highest-intensity climax, insight, punchline, or emotional turning point of the clip (explicitly cite timestamp/range if anchored to a Crowd-Sourced Virality Peak).",
    )
    virality_score: int = Field(
        description="Virality rating score from 1 to 100 based on emotional hook, pacing density, and retention payoff",
        ge=1,
        le=100,
    )
    reasoning: str = Field(
        description="Detailed explanation justifying why this sequence has high retention, how it delivers on the hook without dead air, and why the duration was cut at this exact moment",
    )
    segments: list[ClipSegment] = Field(
        default_factory=list,
        description="1 to 4 ordered sub-segments stitched into a continuous high-retention narrative arc",
    )
    start_time: float = Field(
        default=0.0,
        description="Earliest start timestamp across all segments in seconds"
    )
    end_time: float = Field(
        default=0.0,
        description="Latest end timestamp across all segments in seconds"
    )
    duration: float = Field(
        default=50.0,
        description="Total stitched duration in seconds (strictly between 45.0 and 60.0 seconds)",
        ge=45.0,
        le=60.0,
    )
    social_metadata: Optional[SocialMetadata] = Field(
        default=None,
        description="Platform-tailored social copy for YouTube Shorts, Instagram Reels, and TikTok",
    )

    @model_validator(mode="before")
    @classmethod
    def clamp_pre_validation(cls, data: Any) -> Any:
        """Pre-validation hook to ensure numeric fields conform to schema constraints."""
        if isinstance(data, dict):
            if "duration" in data and data["duration"] is not None:
                try:
                    d = float(data["duration"])
                    if d < 45.0:
                        data["duration"] = 45.0
                    elif d > 60.0:
                        data["duration"] = 60.0
                except (ValueError, TypeError):
                    pass
            if "virality_score" in data and data["virality_score"] is not None:
                try:
                    v = int(round(float(data["virality_score"])))
                    data["virality_score"] = max(1, min(100, v))
                except (ValueError, TypeError):
                    pass
        return data

    @model_validator(mode="after")
    def validate_duration_and_segments(self) -> "ViralClip":
        """Synchronize sub-segments, start/end bounds, enforce duration bounds and social copy."""
        # Auto-populate segments if only flat start_time/end_time was provided
        if not self.segments:
            s_start = round(float(self.start_time), 2)
            s_end = round(float(self.end_time), 2)
            if s_end <= s_start:
                s_end = round(s_start + 50.0, 2)
            self.segments = [
                ClipSegment(
                    start_time=s_start,
                    end_time=s_end,
                    segment_role="core_insight",
                )
            ]

        # Calculate stitched duration as sum of individual segment durations
        calculated_duration = round(
            sum(max(0.1, s.end_time - s.start_time) for s in self.segments),
            2,
        )

        # Enforce duration bounds (strictly between 45.0 and 60.0 seconds)
        if calculated_duration < 45.0:
            diff = 45.0 - calculated_duration
            self.segments[-1].end_time = round(self.segments[-1].end_time + diff, 2)
            calculated_duration = 45.0
        elif calculated_duration > 60.0:
            diff = calculated_duration - 60.0
            last_seg = self.segments[-1]
            last_seg_dur = last_seg.end_time - last_seg.start_time
            if last_seg_dur > diff + 3.0:
                last_seg.end_time = round(last_seg.end_time - diff, 2)
            calculated_duration = 60.0

        self.duration = calculated_duration
        self.start_time = min(s.start_time for s in self.segments)
        self.end_time = max(s.end_time for s in self.segments)

        # Auto-populate social metadata if not provided
        if self.social_metadata is None:
            clean_title = self.title if "#Shorts" in self.title else f"{self.title} #Shorts"
            self.social_metadata = SocialMetadata(
                youtube_title=clean_title[:95],
                youtube_description=(
                    f"{self.hook_text}\n\n"
                    f"{self.reasoning}\n\n"
                    "#viral #shorts #trending #motivation #insights"
                ),
                youtube_tags=["viral", "shorts", "trending", "insights", "storytelling"],
                instagram_caption=(
                    f"{self.hook_text} 🔥\n\n"
                    f"{self.reasoning}\n\n"
                    "What's your take on this? Let us know below! 👇\n\n"
                    "#reels #viralvideos #reelsinstagram #trending #insights #shorts"
                ),
                tiktok_caption=f"{self.hook_text[:75]} #fyp #viral #trending #story",
            )

        return self


class ClipSelectionResponse(BaseModel):
    """Wrapper response schema containing selected viral clips."""

    clips: list[ViralClip] = Field(
        description="List of selected viral clips meeting all criteria"
    )


def get_genai_client(api_key: Optional[str] = None) -> genai.Client:
    """Initialize and return the official Google GenAI Client.

    Raises:
        ValueError: If GEMINI_API_KEY is not configured.
    """
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key or key.strip() in ("", "your_key_here", "your_gemini_api_key_here"):
        raise ValueError(
            "GEMINI_API_KEY is not set or contains placeholder text.\n"
            "Please add your Gemini API key to `backend/.env`:\n"
            "GEMINI_API_KEY=AIzaSy..."
        )
    return genai.Client(api_key=key.strip())


def find_viral_clips(
    transcript_text: str,
    num_clips: int = 3,
    model: str = "gemini-3.5-flash-lite",
    api_key: Optional[str] = None,
    heatmap_peaks: Optional[list[dict[str, Any]]] = None,
) -> ClipSelectionResponse:
    """Analyze a timestamped transcript and return viral clip candidates using the Waterfall Strategy.

    Args:
        transcript_text: Formatted timestamped transcript block.
        num_clips: Number of top viral clips to extract (default: 3).
        model: Gemini model identifier (default: 'gemini-3.5-flash-lite').
        api_key: Optional explicit Gemini API key override.
        heatmap_peaks: Optional list of crowd-sourced viewer replay retention peaks from yt-dlp.

    Returns:
        ClipSelectionResponse object containing the list of ViralClip models.
    """
    if not transcript_text or not transcript_text.strip():
        raise ValueError("Transcript text cannot be empty")

    client = get_genai_client(api_key)

    system_instruction = (
        "You are an elite short-form video editor and viral content strategist (specializing in OpusClip, Hormozi, and MrBeast retention editing).\n"
        "Your task is to analyze the provided YouTube transcript with timestamps and identify "
        f"the top {num_clips} most engaging, self-contained segments that would perform exceptionally well as "
        "YouTube Shorts, Instagram Reels, and TikTok clips.\n\n"
        "=== THE WATERFALL STRATEGY FOR CLIP SELECTION ===\n"
        "1. PRIORITY 1 (Crowd-Sourced Virality Peaks):\n"
        "   - If 'Crowd-Sourced Virality Peaks' (YouTube replay heatmap data) are provided below, you MUST prioritize "
        "building your clip narrative around those exact moments.\n"
        "   - The heatmap represents real audience behavior where thousands of viewers replayed, shared, or looped.\n"
        "   - Structure the clip so that the peak timestamp acts as the emotional climax, profound insight, or punchline payoff "
        "(e.g., segment_role='climax_payoff' or 'core_insight'), or as an explosive cold-open hook teaser (segment_role='cold_open_hook').\n"
        "   - In the 'peak_moment' field, explicitly cite the exact timestamp range you anchored to and explain the climax.\n"
        "   - BUILDING A 45-60s NARRATIVE ARC AROUND PEAKS: A heatmap peak itself is typically 15-30 seconds long. Because every clip "
        "MUST be strictly between 45.0 and 60.0 seconds, you MUST build the complete narrative arc around the peak: incorporate the essential "
        "setup leading into it and/or the takeaway aftermath following it (or multi-segment stitch). Do NOT return isolated 20-30 second fragments.\n\n"
        "2. PRIORITY 2 (Chain-of-Thought Virality Scoring Fallback):\n"
        "   - If NO heatmap peaks are available (or for clips beyond available peaks), you MUST fall back to 'Chain-of-Thought Virality Scoring'.\n"
        "   - Systematically scan the transcript and prioritize moments of:\n"
        "     * High Controversy or Counter-Intuitive Truths (provocative claims that challenge conventional wisdom)\n"
        "     * Extreme Humor or Unfiltered Emotional Reactions\n"
        "     * Profound 'Aha!' Epiphanies or High-Utility Actionable Wisdom\n"
        "     * High-Stakes Narrative (a compelling setup, conflict/crisis, and breakthrough resolution)\n"
        "   - You MUST formulate your 'hook_strategy', articulate the 'peak_moment', rate the 'virality_score' (1-100), and explain "
        "your 'reasoning' to justify your selection and pacing BEFORE defining segment timestamps.\n\n"
        "=== TARGET DURATION & STRICT PACING RULES ===\n"
        "- TARGET LENGTH: Each clip's total stitched duration (sum of segment durations) MUST be strictly between 45.0 and 60.0 seconds.\n"
        "- STRICT PACING RULE: \"Do not pad clips with dead air to hit the 60-second mark. Every single second must contain value, curiosity, or conflict. "
        "If a thought naturally concludes at 52 seconds, cut it there.\"\n\n"
        "=== NON-LINEAR MULTI-SEGMENT EDITING RULES ===\n"
        "- Each clip can consist of 1 to 4 sub-segments stitched together seamlessly.\n"
        "- COLD-OPEN HOOK TEASERS: If an explosive punchline, emotional reaction, or climax happens later in the speech, "
        "place a punchy 3-5 second teaser as segment 1 with segment_role='cold_open_hook', followed by segment_role='story_setup', "
        "'core_insight', and 'climax_payoff'.\n"
        "- TANGENT REMOVAL: If the speaker goes on a rambling 5-20 second tangent in the middle, cut it out by specifying 2-3 tight sub-segments "
        "that connect directly into a continuous, high-energy narrative.\n"
        "- SINGLE CONTINUOUS CLIPS: If a continuous thought is already tight, coherent, and compelling without dead weight, use 1 segment.\n\n"
        "=== STRICT CRITERIA FOR EACH CLIP ===\n"
        "1. DURATION: Total stitched duration MUST be strictly between 45.0 and 60.0 seconds.\n"
        "2. HOOK: Must start with a powerful, attention-grabbing hook in the first 3 seconds.\n"
        "3. COMPLETION: Must end on a complete thought or impactful sentence (never cut mid-sentence).\n"
        "4. TIMESTAMPS: start_time and end_time for each segment MUST be exact float seconds matching the timestamps provided in the transcript.\n"
        "5. TITLE: High-CTR, punchy title ending with #Shorts.\n"
        "6. VIRALITY SCORE: Rate potential virality from 1 to 100 based on narrative momentum, emotional hook, and clarity.\n"
        "7. HOOK STRATEGY & PEAK MOMENT: Explicitly detail the psychological hook mechanism and peak moment."
    )

    # Format Crowd-Sourced Virality Peaks if available
    peaks_block = ""
    if heatmap_peaks:
        peak_items = []
        for idx, p in enumerate(heatmap_peaks, 1):
            s = float(p.get("start_time", 0.0))
            e = float(p.get("end_time", 0.0))
            mid = float(p.get("peak_time", (s + e) / 2.0))
            intensity = float(p.get("intensity", 1.0))
            pct = int(round(intensity * 100)) if intensity <= 1.0 else int(round(intensity))
            m_s, s_s = int(s // 60), int(s % 60)
            m_e, s_e = int(e // 60), int(e % 60)
            peak_items.append(
                f"  - Peak #{idx}: {m_s:02d}:{s_s:02d} - {m_e:02d}:{s_e:02d} "
                f"({s:.1f}s - {e:.1f}s, Center: ~{mid:.1f}s, Audience Replay Intensity: {pct}%)"
            )
        peaks_block = (
            "=== CROWD-SOURCED VIRALITY PEAKS (Audience Replay Heatmap) ===\n"
            "The following timestamp ranges represent the highest viewer replay / retention peaks recorded for this video:\n"
            + "\n".join(peak_items) + "\n\n"
            "WATERFALL MANDATE: You MUST prioritize building the clip narrative around these exact peak moments.\n\n"
        )
    else:
        peaks_block = (
            "=== CROWD-SOURCED VIRALITY PEAKS ===\n"
            "No audience retention heatmap is available for this video.\n"
            "WATERFALL MANDATE: Fall back to Chain-of-Thought Virality Scoring. "
            "Prioritize moments of peak controversy, extreme humor, high-stakes storytelling, or profound 'aha' epiphanies.\n\n"
        )

    user_prompt = (
        f"{peaks_block}"
        f"Analyze this transcript and extract the top {num_clips} viral clips between 45.0 and 60.0 seconds long:\n"
        "Strict Pacing Rule: Do not pad clips with dead air to hit the 60-second mark. Every single second must contain value, curiosity, or conflict. "
        "If a thought naturally concludes at 52 seconds, cut it there.\n\n"
        "MANDATORY DURATION CONSTRAINT: Every clip's total stitched duration MUST be strictly between 45.0 and 60.0 seconds. "
        "Never output clips shorter than 45 seconds or longer than 60 seconds.\n\n"
        "--- TRANSCRIPT START ---\n"
        f"{transcript_text}\n"
        "--- TRANSCRIPT END ---\n\n"
        f"Return exactly {num_clips} high-performing clips conforming to the ClipSelectionResponse schema."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=ClipSelectionResponse,
        temperature=0.2,
    )

    default_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    active_model = model or default_model

    # Model fallback chain prioritizing verified active models
    candidate_models = [active_model]
    for fallback in [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
    ]:
        if fallback not in candidate_models:
            candidate_models.append(fallback)

    last_error = None
    for target_model in candidate_models:
        for attempt in range(1, 4):
            try:
                logger.info(f"Calling Gemini model: {target_model} (attempt {attempt})")
                response = client.models.generate_content(
                    model=target_model,
                    contents=user_prompt,
                    config=config,
                )
                raw_text = response.text
                if not raw_text:
                    raise ValueError("Received empty response from Gemini API")

                parsed = ClipSelectionResponse.model_validate_json(raw_text)
                return parsed

            except Exception as e:
                err_msg = str(e)
                last_error = e

                # If 404 (model deprecated / unavailable), break immediately to next model
                if "404" in err_msg or "not available" in err_msg.lower():
                    logger.warning(f"Model {target_model} is unavailable (404/deprecated). Switching to next candidate...")
                    break

                # If 503 or 429 (temporary demand/rate limit), back off and retry
                if ("503" in err_msg or "429" in err_msg or "high demand" in err_msg.lower()) and attempt < 3:
                    wait_sec = attempt * 2
                    logger.warning(
                        f"Model {target_model} encountered temporary load ({err_msg}). Retrying in {wait_sec}s..."
                    )
                    time.sleep(wait_sec)
                    continue

                # If still failing after retries, try next candidate model
                logger.warning(f"Model {target_model} attempt {attempt} failed: {err_msg}")
                break

    raise RuntimeError(f"All candidate Gemini models failed. Last error: {last_error}")


def generate_social_metadata_for_clip(
    clip_dict: dict[str, Any],
    custom_prompt: Optional[str] = None,
    model: str = "gemini-3.5-flash-lite",
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Generate high-performing multi-platform copy for a clip using Gemini with safe fallback.

    Args:
        clip_dict: Dictionary with title, hook_text, reasoning, etc.
        custom_prompt: Optional user styling or angle directions.
        model: Gemini model identifier.
        api_key: Optional Gemini API key override.

    Returns:
        dict conforming to SocialMetadata schema.
    """
    title = clip_dict.get("title", "Viral Short")
    hook = clip_dict.get("hook_text", "")
    reasoning = clip_dict.get("reasoning", "")

    fallback = SocialMetadata(
        youtube_title=f"{title} #Shorts"[:95],
        youtube_description=(
            f"{hook}\n\n"
            f"{reasoning}\n\n"
            "#viral #shorts #trending #motivation #insights"
        ),
        youtube_tags=["viral", "shorts", "trending", "insights", "storytelling"],
        instagram_caption=(
            f"{hook} 🔥\n\n"
            f"{reasoning}\n\n"
            "Drop your thoughts below! 👇\n\n"
            "#reels #viralvideos #reelsinstagram #trending #insights #shorts"
        ),
        tiktok_caption=f"{hook[:75]} #fyp #viral #trending #story",
    )

    try:
        client = get_genai_client(api_key)
        system_instruction = (
            "You are a top social media copywriter for viral TikTok, Instagram Reels, and YouTube Shorts. "
            "Given the title, opening hook, and reasoning for a video clip, create highly engaging copy "
            "optimized for each platform algorithm according to the SocialMetadata schema."
        )
        user_prompt = (
            f"Title: {title}\n"
            f"Opening Hook: {hook}\n"
            f"Context / Core Insight: {reasoning}\n"
        )
        if custom_prompt:
            user_prompt += f"\nCustom Instruction: {custom_prompt}\n"
        user_prompt += "\nGenerate optimized social media copy conforming to the SocialMetadata schema."

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=SocialMetadata,
            temperature=0.3,
        )

        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=config,
        )
        if response.text:
            parsed = SocialMetadata.model_validate_json(response.text)
            return parsed.model_dump()
    except Exception as e:
        logger.warning(f"Could not generate social copy with Gemini ({e}). Using algorithmic fallback.")

    return fallback.model_dump()

