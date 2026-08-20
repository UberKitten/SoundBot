"""Service for downloading media with yt-dlp."""

import asyncio
import json
import logging
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, override

from pydantic import BaseModel

from soundbot.core.settings import settings

logger = logging.getLogger(__name__)

# Cache the yt-dlp command and environment to avoid recalculating
_ytdlp_command: list[str] | None = None
_ytdlp_env: dict[str, str] | None = None


@contextmanager
def _skip_debugger_subprocess_patch():
    """Context manager to skip debugpy's subprocess argument patching.

    When running under VS Code's Python debugger (debugpy), it patches
    subprocess calls to inject debugging into child Python processes.
    This breaks yt-dlp because the patched command doesn't work correctly.
    """
    try:
        # Try to import pydevd's skip_subprocess_arg_patch
        from pydevd import skip_subprocess_arg_patch  # type: ignore[import-not-found]

        with skip_subprocess_arg_patch():
            yield
    except ImportError:
        # Not running under debugger, nothing to skip
        yield


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
    project_root = (
        this_file.parent.parent.parent.parent
    )  # Go up to src/, then project root

    import os

    if os.name == "nt":
        venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = project_root / ".venv" / "bin" / "python"

    if venv_python.exists():
        logger.debug(f"Using venv Python: {venv_python}")
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
        "PYTHONHOME",  # Can also break module resolution
        "PYTHONSTARTUP",  # VS Code sets this for REPL
        "PYDEVD_USE_FRAME_EVAL",  # debugpy
        "PYDEVD_LOAD_VALUES_ASYNC",  # debugpy
        "PYDEVD_DISABLE_FILE_VALIDATION",  # debugpy
        "DEBUGPY_PROCESS_SPAWN_TIMEOUT",  # debugpy
        "BUNDLED_DEBUGPY_PATH",  # VS Code debugpy
        "VSCODE_DEBUGPY_ADAPTER_ENDPOINTS",  # VS Code debugpy
    ]

    removed = []
    for var in vars_to_remove:
        if var in env:
            removed.append(var)
            del env[var]

    if removed:
        logger.debug(f"Removed debugger environment variables: {removed}")

    _ytdlp_env = env
    return _ytdlp_env.copy()


def _get_configured_cookies_file() -> Optional[Path]:
    """Return the configured cookies file only when it is currently usable."""
    if not settings.ytdlp_cookies_file:
        return None

    cookies_file = Path(settings.ytdlp_cookies_file).expanduser()
    try:
        return cookies_file.resolve() if cookies_file.is_file() else None
    except OSError:
        return None


def _youtube_provider_args() -> list[str]:
    """Build the shared YouTube POT provider extractor arguments."""
    return [
        "--extractor-args",
        "youtube:player_client=mweb",
        "--extractor-args",
        f"youtubepot-bgutilhttp:base_url={settings.ytdlp_pot_provider_url}",
    ]


def _with_cookies(args: list[str], cookies_file: Optional[Path]) -> list[str]:
    """Add a cookies file to an invocation without mutating the input list."""
    result = args.copy()
    if cookies_file is not None:
        result.extend(["--cookies", str(cookies_file)])
    return result


def _build_download_args(
    url: str,
    output_template: str,
    cookies_file: Optional[Path] = None,
) -> list[str]:
    """Build a complete yt-dlp download invocation."""
    args = _get_ytdlp_command()
    args.extend(
        [
            url,
            "--output",
            output_template,
            # Only download single video, not entire playlist
            "--no-playlist",
            # Best quality video+audio, or best audio only
            "--format",
            "bestvideo+bestaudio/best/bestaudio",
            # Write metadata to JSON
            "--write-info-json",
            # Embed metadata in file
            "--embed-metadata",
            # Don't overwrite existing files
            "--no-overwrites",
            # Output JSON info to stdout for parsing
            "--print-json",
            # Merge to mkv to preserve all streams
            "--merge-output-format",
            "mkv",
            # Use Node.js for YouTube extraction with EJS challenge solver
            "--js-runtimes",
            "node",
            "--remote-components",
            "ejs:github",
            *_youtube_provider_args(),
        ]
    )
    return _with_cookies(args, cookies_file)


def _build_video_info_args(
    url: str, cookies_file: Optional[Path] = None
) -> list[str]:
    """Build a complete yt-dlp metadata invocation."""
    args = _get_ytdlp_command()
    args.extend(
        [
            url,
            "--dump-json",
            "--no-download",
            "--js-runtimes",
            "node",
            "--remote-components",
            "ejs:github",
            *_youtube_provider_args(),
        ]
    )
    return _with_cookies(args, cookies_file)


def _redact_cookie_path(text: str, cookies_file: Optional[Path]) -> str:
    """Keep a configured cookie path out of logs and returned errors."""
    if cookies_file is None:
        return text
    return text.replace(str(cookies_file), "<cookies-file>")


def _command_for_log(args: list[str]) -> str:
    """Format an invocation without exposing the configured cookies path."""
    safe_args = args.copy()
    try:
        cookies_index = safe_args.index("--cookies") + 1
        safe_args[cookies_index] = "<cookies-file>"
    except (ValueError, IndexError):
        pass
    return " ".join(safe_args)


class StepTiming(BaseModel):
    """Timing information for a processing step."""

    step: str
    duration_seconds: float

    @override
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

    @property
    def canonical_url(self) -> Optional[str]:
        """yt-dlp's canonical webpage URL for the media, when known.

        Prefer this over the user-supplied URL when storing source_url —
        it strips share/tracking params (youtu.be/x?si=... becomes
        youtube.com/watch?v=x) and normalizes the host.
        """
        if self.metadata:
            url = self.metadata.get("webpage_url")
            if isinstance(url, str) and url:
                return url
        return None

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
        super().__init__()
        self._last_update: Optional[datetime] = None
        self._update_lock = asyncio.Lock()

    async def update_ytdlp(self) -> tuple[bool, str]:
        """Update yt-dlp to the latest version. Returns (success, message)."""
        async with self._update_lock:
            try:
                logger.info("Updating yt-dlp...")
                # yt-dlp is installed as a PyPI wheel via uv, so `yt-dlp --update`
                # is a no-op (it only self-updates the standalone binary). Use uv
                # to actually upgrade the installed package instead.
                venv_python = _get_ytdlp_command()[0]
                cmd = [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    venv_python,
                    "--upgrade",
                    "yt-dlp",
                ]
                logger.debug(f"Running: {' '.join(cmd)}")
                with _skip_debugger_subprocess_patch():
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=_get_clean_env(),
                    )
                    stdout, stderr = await proc.communicate()

                output = stdout.decode().strip()
                stderr_text = stderr.decode().strip() if stderr else ""

                if stderr_text:
                    logger.warning(f"yt-dlp update stderr: {stderr_text}")

                if proc.returncode == 0:
                    self._last_update = datetime.now()
                    logger.debug(f"yt-dlp update: {output}")
                    return True, output
                else:
                    error = stderr_text or "Unknown error"
                    logger.error(
                        f"Failed to update yt-dlp (code {proc.returncode}): {error}"
                    )
                    return False, error
            except Exception as e:
                logger.error(f"Error updating yt-dlp: {e}")
                return False, str(e)

    async def _do_download(
        self,
        url: str,
        output_dir: Path,
        sound_name: str,
        *,
        cookies_file: Optional[Path] = None,
    ) -> DownloadResult:
        """Internal download implementation."""
        timings: list[StepTiming] = []
        # Resolve to absolute path to avoid relative path issues
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # Output template - just use filename since we set cwd to output_dir
        output_template = f"{sound_name}.%(ext)s"
        metadata_file = output_dir / "metadata.json"

        # Build yt-dlp command
        args = _build_download_args(url, output_template, cookies_file)

        try:
            start_time = time.monotonic()
            auth_mode = "anonymous" if cookies_file is None else "configured cookies"
            logger.info(f"Downloading {url} to {output_dir} ({auth_mode})")
            logger.debug(f"Running: {_command_for_log(args)}")

            with _skip_debugger_subprocess_patch():
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
            stderr_text = (
                _redact_cookie_path(stderr.decode().strip(), cookies_file)
                if stderr
                else ""
            )
            if stderr_text:
                logger.info(f"yt-dlp stderr: {stderr_text}")

            if proc.returncode != 0:
                error_msg = stderr_text or "Unknown error"
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
                _ = metadata_file.write_text(
                    json.dumps(metadata, indent=2, default=str)
                )
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
            error = _redact_cookie_path(str(e), cookies_file)
            logger.error(f"Error downloading {url}: {error}")
            return DownloadResult(success=False, error=error, timings=timings)

    async def download(
        self,
        url: str,
        output_dir: Path,
        sound_name: str,
    ) -> DownloadResult:
        """
        Download media from URL using yt-dlp.

        yt-dlp is refreshed on a daily schedule (see app.update_ytdlp_periodically),
        so the common path does no update. If a download fails (e.g. a site changed
        its API and we get an HTTP 403), update yt-dlp once and retry — newer
        extractors often fix exactly this.
        """
        result = await self._do_download(url, output_dir, sound_name)

        if result.success:
            return result

        cookies_file = _get_configured_cookies_file()
        if settings.ytdlp_cookies_file and cookies_file is None:
            logger.warning(
                "Configured yt-dlp cookies file is unavailable; "
                "continuing without cookies."
            )

        # Preserve the existing update-before-retry behavior. An available
        # cookie file still gets its one retry if the update itself fails.
        logger.warning(
            f"Anonymous download failed ({result.error}); "
            "updating yt-dlp before retrying once."
        )
        start_time = time.monotonic()
        update_success, update_msg = await self.update_ytdlp()
        update_time = time.monotonic() - start_time

        if not update_success:
            logger.warning(f"yt-dlp update failed: {update_msg}")
            if cookies_file is None:
                return result

        retry = await self._do_download(
            url,
            output_dir,
            sound_name,
            cookies_file=cookies_file,
        )
        retry.timings.insert(
            0, StepTiming(step="yt-dlp update (retry)", duration_seconds=update_time)
        )
        return retry

    async def download_temp(self, url: str) -> DownloadResult:
        """
        Download media to a temporary directory for quick playback.

        Returns the result with the temp file path.
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="soundbot_"))
        return await self.download(url, temp_dir, "quickplay")

    async def _get_video_info_once(
        self, url: str, cookies_file: Optional[Path] = None
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """Run one metadata invocation and return its result and safe error."""
        try:
            cmd = _build_video_info_args(url, cookies_file)
            logger.debug(
                f"Getting video info, command: {_command_for_log(cmd)}"
            )
            with _skip_debugger_subprocess_patch():
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_get_clean_env(),
                )
                stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return json.loads(stdout.decode()), None

            error = (
                _redact_cookie_path(stderr.decode().strip(), cookies_file)
                if stderr
                else "Unknown error"
            )
            return None, error
        except Exception as e:
            return None, _redact_cookie_path(str(e), cookies_file)

    async def get_video_info(self, url: str) -> Optional[dict[str, Any]]:
        """Get video info without downloading, anonymously when possible."""
        info, error = await self._get_video_info_once(url)
        if info is not None:
            return info

        cookies_file = _get_configured_cookies_file()
        if cookies_file is None:
            if settings.ytdlp_cookies_file:
                logger.warning(
                    "Configured yt-dlp cookies file is unavailable; "
                    "not using cookies for video info."
                )
            logger.error(f"Failed to get video info: {error or 'Unknown error'}")
            return None

        logger.warning(
            "Anonymous video info request failed; retrying once with "
            "configured cookies."
        )
        info, retry_error = await self._get_video_info_once(url, cookies_file)
        if info is None:
            logger.error(
                f"Failed to get video info after cookie retry: "
                f"{retry_error or 'Unknown error'}"
            )
        return info


# Singleton instance
ytdlp_service = YtdlpService()
