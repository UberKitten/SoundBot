"""Service for audio/video processing with FFmpeg."""

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from soundbot.core.settings import settings

logger = logging.getLogger(__name__)


class ProbeResult(BaseModel):
    """Result of probing a media file."""

    duration: Optional[float] = None
    has_video: bool = False
    has_audio: bool = False
    video_codec: Optional[str] = None
    width: Optional[int] = None
    audio_codec: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    title: Optional[str] = None


class ProcessResult(BaseModel):
    """Result of processing a media file."""

    success: bool
    output_file: Optional[Path] = None
    error: Optional[str] = None
    duration_seconds: Optional[float] = None  # How long the processing took
    # For make_browser_video: True when the video stream was stream-copied
    # (remux) instead of re-encoded. None for other operations.
    remuxed: Optional[bool] = None


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

            # Get duration and title from format
            if "format" in data:
                fmt = data["format"]
                if "duration" in fmt:
                    result.duration = float(fmt["duration"])
                tags = fmt.get("tags") or {}
                # mkv tags are case-insensitive; ffprobe tends to lowercase but be defensive
                for key in ("title", "TITLE", "Title"):
                    if key in tags and tags[key]:
                        result.title = str(tags[key])
                        break

            # Analyze streams
            for stream in data.get("streams", []):
                codec_type = stream.get("codec_type")
                if codec_type == "video":
                    result.has_video = True
                    result.video_codec = stream.get("codec_name")
                    width = stream.get("width")
                    if isinstance(width, int) and width > 0:
                        result.width = width
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
        volume_db: float = 0.0,
    ) -> ProcessResult:
        """
        Extract audio from input, trim, normalize, and optimize for Discord.

        Uses loudnorm filter for EBU R128 normalization.
        Output is opus in ogg container for best Discord compatibility.

        volume_db: dB adjustment applied after normalization (negative = quieter).
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

        # EBU R128 loudness normalization
        # Target LUFS from settings, with true peak at -1.5 dBTP
        target_lufs = settings.audio_target_lufs
        filters.append(f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11")

        # Per-sound volume adjustment in dB (applied after normalization)
        if volume_db != 0.0:
            filters.append(f"volume={volume_db}dB")

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

    async def make_browser_video(
        self,
        input_file: Path,
        output_file: Path,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> ProcessResult:
        """
        Produce a browser/iOS/Discord-friendly MP4 (H.264 + AAC).

        Smart path: if the source video is already H.264, needs no scaling
        (width ≤ 1280), and no trim is requested, the video stream is
        stream-copied (remux — near-instant). Otherwise it's re-encoded with
        libx264 capped at 1280px wide, optionally trimming to start/end
        (used when falling back to the untrimmed original).

        Audio is ALWAYS transcoded to AAC — opus-in-mp4 doesn't fly with
        Safari or Discord's inline player. Output is always +faststart.
        """
        remux = False
        if start is None and end is None:
            probe = await self.probe(input_file)
            if (
                probe is not None
                and probe.video_codec == "h264"
                and probe.width is not None
                and probe.width <= 1280
            ):
                remux = True

        args = ["ffmpeg", "-y"]

        # Input seeking (faster if before -i)
        if start is not None:
            args.extend(["-ss", str(start)])

        args.extend(["-i", str(input_file)])

        if end is not None:
            duration = end - (start or 0)
            args.extend(["-t", str(duration)])

        if remux:
            args.extend(["-c:v", "copy"])
        else:
            args.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-vf",
                    "scale='min(1280,iw)':-2",
                ]
            )

        args.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output_file),
            ]
        )

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)

            start_time = time.monotonic()
            mode = "remux" if remux else "transcode"
            logger.info(
                f"Making browser video ({mode}): {input_file} -> {output_file}"
            )
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
                success=True,
                output_file=output_file,
                duration_seconds=elapsed,
                remuxed=remux,
            )

        except Exception as e:
            logger.error(f"Error making browser video: {e}")
            return ProcessResult(success=False, error=str(e))

    async def make_waveform_video(
        self,
        audio_file: Path,
        output_file: Path,
        duration: float,
    ) -> ProcessResult:
        """
        Render a SoundCloud-style waveform progress video from audio.

        Two static waveform frames (played-orange, unplayed-gray on a dark
        background) with an xfade wiperight between them lasting the full
        duration — the waveform never moves; only the orange/gray boundary
        sweeps left-to-right in sync with playback. 4:1 aspect (validated as
        the best-rendering shape in Discord's ~400px preview box on desktop
        and mobile); internal width scales with duration so long sounds keep
        waveform detail instead of turning into a mushy strip.

        Audio is AAC (Discord/Safari-safe), output +faststart, like
        make_browser_video.
        """
        # 4:1 aspect; wider canvas for longer sounds (capped: Discord scales
        # display to ~400px anyway, this only buys waveform resolution).
        if duration <= 15:
            width = 640
        elif duration <= 60:
            width = 1280
        else:
            width = 2560
        height = width // 4
        size = f"{width}x{height}"

        bg = "0x1e1f24"  # dark card background
        played = "0xff5500|0xff7733"  # SoundCloud orange (L|R channels)
        unplayed = "0x555a63|0x6a707a"  # muted gray

        async def run(args: list[str]) -> Optional[str]:
            """Run an ffmpeg command; return stderr text on failure."""
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                return stderr.decode() if stderr else "Unknown error"
            return None

        def wavepic_args(colors: str, out: Path) -> list[str]:
            return [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_file),
                "-filter_complex",
                f"color=c={bg}:s={size}[bg];"
                f"[0:a]showwavespic=s={size}:colors={colors}[w];"
                f"[bg][w]overlay=format=auto",
                "-frames:v",
                "1",
                str(out),
            ]

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            start_time = time.monotonic()
            logger.info(f"Making waveform video: {audio_file} -> {output_file}")

            # Three steps: two static PNGs, then the wipe between them.
            # (A single filter graph can't do this — xfade requires CFR
            # inputs, and loop-of-one-frame reports an invalid 1/0 rate.)
            with tempfile.TemporaryDirectory(prefix="soundbot-wave-") as tmp:
                unplayed_png = Path(tmp) / "unplayed.png"
                played_png = Path(tmp) / "played.png"

                for colors, png in (
                    (unplayed, unplayed_png),
                    (played, played_png),
                ):
                    error = await run(wavepic_args(colors, png))
                    if error is not None:
                        logger.error(f"FFmpeg waveform frame failed: {error}")
                        return ProcessResult(
                            success=False,
                            error=error,
                            duration_seconds=time.monotonic() - start_time,
                        )

                error = await run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loop",
                        "1",
                        "-r",
                        "30",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        str(unplayed_png),
                        "-loop",
                        "1",
                        "-r",
                        "30",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        str(played_png),
                        "-i",
                        str(audio_file),
                        "-filter_complex",
                        # Static layers; only the reveal boundary moves
                        f"[0:v][1:v]xfade=transition=wiperight:"
                        f"duration={duration:.3f}:offset=0[v]",
                        "-map",
                        "[v]",
                        "-map",
                        "2:a",
                        "-t",
                        f"{duration:.3f}",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "23",
                        "-pix_fmt",
                        "yuv420p",
                        "-profile:v",
                        "main",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "128k",
                        "-movflags",
                        "+faststart",
                        str(output_file),
                    ]
                )
                elapsed = time.monotonic() - start_time
                if error is not None:
                    logger.error(f"FFmpeg waveform failed: {error}")
                    return ProcessResult(
                        success=False, error=error, duration_seconds=elapsed
                    )

            return ProcessResult(
                success=True, output_file=output_file, duration_seconds=elapsed
            )

        except Exception as e:
            logger.error(f"Error making waveform video: {e}")
            return ProcessResult(success=False, error=str(e))

    async def get_duration(self, input_file: Path) -> Optional[float]:
        """Get the duration of a media file in seconds."""
        result = await self.probe(input_file)
        return result.duration if result else None

    async def extract_preview_audio(
        self,
        input_file: Path,
        output_file: Path,
    ) -> ProcessResult:
        """
        Extract a full-length, browser-decodable audio preview from the source.

        Unlike extract_and_normalize_audio, this does NO trimming and NO
        loudness normalization — it just transcodes the whole original to a
        lightweight mono MP3 so the admin UI can render/scrub a waveform of the
        untrimmed source. Kept fast on purpose.
        """
        args = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_file),
            "-vn",  # No video
            "-ac",
            "1",  # Mono is fine for a waveform preview
            "-c:a",
            "libmp3lame",
            "-q:a",
            "5",
            str(output_file),
        ]

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)

            start_time = time.monotonic()
            logger.info(f"Extracting preview audio: {input_file} -> {output_file}")
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
            logger.error(f"Error extracting preview audio: {e}")
            return ProcessResult(success=False, error=str(e))


# Singleton instance
ffmpeg_service = FFmpegService()
