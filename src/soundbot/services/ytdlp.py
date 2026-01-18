"""Service for downloading media with yt-dlp."""

import asyncio
import json
import logging
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Cache the yt-dlp command and environment to avoid recalculating
_ytdlp_command: list[str] | None = None
_ytdlp_env: dict[str, str] | None = None


def _get_ytdlp_command() -> list[str]:
    """Get the command prefix to run yt-dlp.

    Uses the Python executable from our virtual environment directly,
    not sys.executable which can be wrong when running under a debugger.
    """
    global _ytdlp_command
    if _ytdlp_command is not None:
        return _ytdlp_command.copy()

    # Find the venv's Python by looking relative to this file's location
    # This file is in src/soundbot/services/ytdlp.py
    # The venv is at .venv/Scripts/python.exe (Windows) or .venv/bin/python (Unix)
    this_file = Path(__file__).resolve()
    project_root = this_file.parent.parent.parent.parent  # Go up 4 levels

    import os

    if os.name == "nt":
        venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = project_root / ".venv" / "bin" / "python"

    if venv_python.exists():
        logger.info(f"Using venv Python: {venv_python}")
        _ytdlp_command = [str(venv_python), "-m", "yt_dlp"]
    else:
        # Fall back to sys.executable if venv not found (e.g., in Docker)
        logger.info(
            f"Venv not found at {venv_python}, using sys.executable: {sys.executable}"
        )
        _ytdlp_command = [sys.executable, "-m", "yt_dlp"]

    return _ytdlp_command.copy()


def _get_clean_env() -> dict[str, str]:
    """Get a clean environment for subprocess execution.

    Removes debugger-related environment variables that can interfere
    with Python module resolution in subprocesses.
    """
    global _ytdlp_env
    if _ytdlp_env is not None:
        return _ytdlp_env.copy()

    import os

    env = os.environ.copy()

    # Remove variables that can interfere with subprocess Python
    # These are commonly set by debuggers and can break module imports
    vars_to_remove = [
        "PYTHONPATH",  # Can cause wrong modules to be found
        "PYDEVD_USE_FRAME_EVAL",  # debugpy
        "PYDEVD_LOAD_VALUES_ASYNC",  # debugpy
        "DEBUGPY_PROCESS_SPAWN_TIMEOUT",  # debugpy
    ]
    for var in vars_to_remove:
        env.pop(var, None)

    _ytdlp_env = env
    logger.debug(f"Created clean environment (removed: {vars_to_remove})")
    return _ytdlp_env.copy()


class StepTiming(BaseModel):
    """Timing information for a processing step."""

    step: str
    duration_seconds: float

    def __str__(self) -> str:
        return f"{self.step}: {self.duration_seconds:.2f}s"


class DownloadResult(BaseModel):
    """Result of a yt-dlp download."""

    success: bool
    original_file: Optional[Path] = None
    metadata_file: Optional[Path] = None
    subtitles_file: Optional[Path] = None
    metadata: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[float] = None
    timings: list[StepTiming] = []

    def timing_summary(self) -> str:
        """Get a formatted summary of timings."""
        if not self.timings:
            return ""
        parts = [str(t) for t in self.timings]
        total = sum(t.duration_seconds for t in self.timings)
        parts.append(f"Total: {total:.2f}s")
        return " | ".join(parts)


class YtdlpService:
    """Service for downloading and managing media with yt-dlp."""

    def __init__(self):
        self._last_update: Optional[datetime] = None
        self._update_lock = asyncio.Lock()

    async def update_ytdlp(self) -> tuple[bool, str]:
        """Update yt-dlp to the latest version. Returns (success, message)."""
        async with self._update_lock:
            try:
                logger.info("Updating yt-dlp...")
                cmd = _get_ytdlp_command() + ["--update"]
                logger.debug(f"Running command: {' '.join(cmd)}")
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_get_clean_env(),
                )
                stdout, stderr = await proc.communicate()

                output = stdout.decode().strip()
                if proc.returncode == 0:
                    self._last_update = datetime.now()
                    logger.info(f"yt-dlp update: {output}")
                    return True, output
                else:
                    error = stderr.decode().strip() or "Unknown error"
                    logger.error(f"Failed to update yt-dlp: {error}")
                    if stderr:
                        logger.error(f"yt-dlp update stderr: {stderr.decode()}")
                    return False, error
            except Exception as e:
                logger.error(f"Error updating yt-dlp: {e}")
                return False, str(e)

    async def _do_download(
        self,
        url: str,
        output_dir: Path,
        sound_name: str,
    ) -> DownloadResult:
        """Internal download implementation."""
        timings: list[StepTiming] = []
        output_dir.mkdir(parents=True, exist_ok=True)

        # Output template - use sound name as base filename
        output_template = str(output_dir / f"{sound_name}.%(ext)s")
        metadata_file = output_dir / "metadata.json"

        # Build yt-dlp command
        args = _get_ytdlp_command()

        # Add arguments
        args.extend(
            [
                url,
                "--output",
                output_template,
                # Best quality video+audio, or best audio only
                "--format",
                "bestvideo+bestaudio/best/bestaudio",
                # Write metadata to JSON
                "--write-info-json",
                # Write subtitles if available
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                "en,en-US,en-GB",
                "--sub-format",
                "srt/vtt/best",
                # Embed metadata in file
                "--embed-metadata",
                # Don't overwrite existing files
                "--no-overwrites",
                # Output JSON info to stdout for parsing
                "--print-json",
                # Merge to mkv to preserve all streams
                "--merge-output-format",
                "mkv",
            ]
        )

        try:
            start_time = time.monotonic()
            logger.info(f"Downloading {url} to {output_dir}")
            logger.debug(f"Running command: {' '.join(args)}")

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=output_dir,
                env=_get_clean_env(),
            )
            stdout, stderr = await proc.communicate()

            download_time = time.monotonic() - start_time
            timings.append(StepTiming(step="Download", duration_seconds=download_time))

            # Always log stderr if present, even on success
            if stderr:
                stderr_text = stderr.decode().strip()
                if stderr_text:
                    logger.info(f"yt-dlp stderr: {stderr_text}")

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(
                    f"yt-dlp failed with return code {proc.returncode}: {error_msg}"
                )
                return DownloadResult(success=False, error=error_msg, timings=timings)

            # Parse the JSON output from yt-dlp to know what file was created
            try:
                stdout_text = stdout.decode().strip()
                logger.debug(f"yt-dlp stdout length: {len(stdout_text)} bytes")
                if stdout_text:
                    # Sometimes there's multiple lines, take the last JSON object
                    for line in reversed(stdout_text.splitlines()):
                        line = line.strip()
                        if line.startswith("{"):
                            metadata = json.loads(line)
                            break
                    else:
                        metadata = {}
                        logger.warning("No JSON found in stdout")
                else:
                    metadata = {}
                    logger.warning("Empty stdout from yt-dlp")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON from stdout: {e}")
                # Try reading from the .info.json file
                info_files = list(output_dir.glob("*.info.json"))
                if info_files:
                    logger.info(f"Reading metadata from {info_files[0]}")
                    metadata = json.loads(info_files[0].read_text())
                else:
                    metadata = {}
                    logger.warning("No .info.json file found either")

            # Save metadata to our standard location
            if metadata:
                metadata_file.write_text(json.dumps(metadata, indent=2, default=str))
                logger.debug(f"Saved metadata to {metadata_file}")

            # Find the downloaded file - check what yt-dlp actually created
            logger.debug(f"Searching for downloaded file with base name '{sound_name}'")
            original_file = None

            # First try to get filename from metadata
            if metadata and "_filename" in metadata:
                actual_filename = metadata["_filename"]
                logger.debug(f"yt-dlp reported filename: {actual_filename}")
                # Check if this file exists in our output directory
                potential_file = output_dir / actual_filename
                if potential_file.exists():
                    original_file = potential_file
                    logger.info(f"Found file from metadata: {original_file}")

            # If not found via metadata, search for expected name
            if not original_file:
                for ext in ["mkv", "mp4", "webm", "mp3", "m4a", "opus", "ogg", "wav"]:
                    potential_file = output_dir / f"{sound_name}.{ext}"
                    logger.debug(f"Checking: {potential_file}")
                    if potential_file.exists():
                        original_file = potential_file
                        logger.info(f"Found media file: {original_file}")
                        break

            # If not found with expected name, look for any media file
            if not original_file:
                logger.warning(
                    f"No file found with expected name '{sound_name}', searching for any media files"
                )
                all_files = list(output_dir.iterdir())
                logger.debug(f"Files in directory: {[f.name for f in all_files]}")
                for ext in ["mkv", "mp4", "webm", "mp3", "m4a", "opus", "ogg", "wav"]:
                    files = list(output_dir.glob(f"*.{ext}"))
                    if files:
                        original_file = files[0]
                        logger.info(
                            f"Found media file with different name: {original_file}"
                        )
                        break

            # Find subtitles file
            subtitles_file = None
            for ext in ["srt", "vtt"]:
                subs = list(output_dir.glob(f"*.{ext}"))
                if subs:
                    subtitles_file = subs[0]
                    break

            if not original_file:
                all_files = list(output_dir.iterdir())
                logger.error(
                    f"No media file found. Directory contents: {[f.name for f in all_files]}"
                )
                return DownloadResult(
                    success=False,
                    error="Download completed but no media file found",
                    timings=timings,
                )

            return DownloadResult(
                success=True,
                original_file=original_file,
                metadata_file=metadata_file,
                subtitles_file=subtitles_file,
                metadata=metadata,
                title=metadata.get("title"),
                duration=metadata.get("duration"),
                timings=timings,
            )

        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return DownloadResult(success=False, error=str(e), timings=timings)

    async def download(
        self,
        url: str,
        output_dir: Path,
        sound_name: str,
        retry_after_update: bool = True,
    ) -> DownloadResult:
        """
        Download media from URL using yt-dlp.

        If download fails and retry_after_update is True, will update yt-dlp
        and try again (this often fixes issues with changed site APIs).
        """
        result = await self._do_download(url, output_dir, sound_name)

        if not result.success and retry_after_update:
            logger.info("Download failed, updating yt-dlp and retrying...")

            # Update yt-dlp
            start_time = time.monotonic()
            update_success, update_msg = await self.update_ytdlp()
            update_time = time.monotonic() - start_time

            if update_success:
                # Retry download
                result = await self._do_download(url, output_dir, sound_name)
                # Add update timing to the beginning
                result.timings.insert(
                    0, StepTiming(step="yt-dlp update", duration_seconds=update_time)
                )
            else:
                # Update failed, return original error with note
                result.error = (
                    f"{result.error} (yt-dlp update also failed: {update_msg})"
                )

        return result

    async def download_temp(self, url: str) -> DownloadResult:
        """
        Download media to a temporary directory for quick playback.

        Returns the result with the temp file path.
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="soundbot_"))
        return await self.download(url, temp_dir, "quickplay", retry_after_update=True)

    async def get_video_info(self, url: str) -> Optional[dict[str, Any]]:
        """Get video info without downloading."""
        try:
            cmd = _get_ytdlp_command() + [url, "--dump-json", "--no-download"]
            logger.debug(f"Getting video info, command: {' '.join(cmd)}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_get_clean_env(),
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return json.loads(stdout.decode())
            else:
                if stderr:
                    logger.error(f"Failed to get video info: {stderr.decode()}")
                return None
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None


# Singleton instance
ytdlp_service = YtdlpService()
