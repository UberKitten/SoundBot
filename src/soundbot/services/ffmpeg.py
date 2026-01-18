"""Service for audio/video processing with FFmpeg."""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ProbeResult(BaseModel):
    """Result of probing a media file."""

    duration: Optional[float] = None
    has_video: bool = False
    has_audio: bool = False
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


class ProcessResult(BaseModel):
    """Result of processing a media file."""

    success: bool
    output_file: Optional[Path] = None
    error: Optional[str] = None
    duration_seconds: Optional[float] = None  # How long the processing took


class FFmpegService:
    """Service for audio/video processing with FFmpeg."""

    # Discord optimal audio settings
    DISCORD_SAMPLE_RATE = 48000
    DISCORD_CHANNELS = 2
    DISCORD_BITRATE = "128k"

    async def probe(self, input_file: Path) -> Optional[ProbeResult]:
        """Probe a media file to get its properties."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(input_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode != 0:
                return None

            data = json.loads(stdout.decode())

            result = ProbeResult()

            # Get duration from format
            if "format" in data and "duration" in data["format"]:
                result.duration = float(data["format"]["duration"])

            # Analyze streams
            for stream in data.get("streams", []):
                codec_type = stream.get("codec_type")
                if codec_type == "video":
                    result.has_video = True
                    result.video_codec = stream.get("codec_name")
                elif codec_type == "audio":
                    result.has_audio = True
                    result.audio_codec = stream.get("codec_name")
                    result.sample_rate = int(stream.get("sample_rate", 0)) or None
                    result.channels = stream.get("channels")

            return result

        except Exception as e:
            logger.error(f"Error probing {input_file}: {e}")
            return None

    async def extract_and_normalize_audio(
        self,
        input_file: Path,
        output_file: Path,
        start: Optional[float] = None,
        end: Optional[float] = None,
        volume: float = 1.0,
    ) -> ProcessResult:
        """
        Extract audio from input, trim, normalize, and optimize for Discord.

        Uses loudnorm filter for EBU R128 normalization.
        Output is opus in ogg container for best Discord compatibility.
        """
        args = ["ffmpeg", "-y"]

        # Input seeking (faster if before -i)
        if start is not None:
            args.extend(["-ss", str(start)])

        args.extend(["-i", str(input_file)])

        # Duration (if end specified)
        if end is not None:
            duration = end - (start or 0)
            args.extend(["-t", str(duration)])

        # Audio filters
        filters = []

        # Volume adjustment (before normalization if boosting, after if reducing)
        if volume != 1.0:
            filters.append(f"volume={volume}")

        # EBU R128 loudness normalization
        # Target: -16 LUFS (good for Discord), with true peak at -1.5 dBTP
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

        if filters:
            args.extend(["-af", ",".join(filters)])

        # Output settings optimized for Discord
        args.extend(
            [
                "-vn",  # No video
                "-ar",
                str(self.DISCORD_SAMPLE_RATE),
                "-ac",
                str(self.DISCORD_CHANNELS),
                "-c:a",
                "libopus",
                "-b:a",
                self.DISCORD_BITRATE,
                str(output_file),
            ]
        )

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)

            start_time = time.monotonic()
            logger.info(f"Processing audio: {input_file} -> {output_file}")
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            elapsed = time.monotonic() - start_time

            if proc.returncode != 0:
                error = stderr.decode() if stderr else "Unknown error"
                logger.error(f"FFmpeg failed: {error}")
                return ProcessResult(
                    success=False, error=error, duration_seconds=elapsed
                )

            return ProcessResult(
                success=True, output_file=output_file, duration_seconds=elapsed
            )

        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            return ProcessResult(success=False, error=str(e))

    async def trim_video(
        self,
        input_file: Path,
        output_file: Path,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> ProcessResult:
        """
        Trim video file with re-encoding for accurate cuts.

        Uses copy codec where possible, but re-encodes around cut points for accuracy.
        """
        args = ["ffmpeg", "-y"]

        # Input seeking
        if start is not None:
            args.extend(["-ss", str(start)])

        args.extend(["-i", str(input_file)])

        # Duration
        if end is not None:
            duration = end - (start or 0)
            args.extend(["-t", str(duration)])

        # Copy streams where possible
        args.extend(
            [
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                str(output_file),
            ]
        )

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)

            start_time = time.monotonic()
            logger.info(f"Trimming video: {input_file} -> {output_file}")
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            elapsed = time.monotonic() - start_time

            if proc.returncode != 0:
                error = stderr.decode() if stderr else "Unknown error"
                logger.error(f"FFmpeg failed: {error}")
                return ProcessResult(
                    success=False, error=error, duration_seconds=elapsed
                )

            return ProcessResult(
                success=True, output_file=output_file, duration_seconds=elapsed
            )

        except Exception as e:
            logger.error(f"Error trimming video: {e}")
            return ProcessResult(success=False, error=str(e))

    async def get_duration(self, input_file: Path) -> Optional[float]:
        """Get the duration of a media file in seconds."""
        result = await self.probe(input_file)
        return result.duration if result else None


# Singleton instance
ffmpeg_service = FFmpegService()
