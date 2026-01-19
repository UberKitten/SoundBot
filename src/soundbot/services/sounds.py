"""Service for managing sounds - download, process, store, and retrieve."""

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.models.sounds import Sound, SoundFiles, Timestamps
from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.ytdlp import ytdlp_service

logger = logging.getLogger(__name__)


def sanitize_name(name: str) -> str:
    """Sanitize a sound name for use as a directory name."""
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", "_", name)
    name = name.lower().strip("_")
    return name[:50]  # Limit length


@dataclass
class OperationResult:
    """Result of a sound operation with timing information."""

    success: bool
    message: str
    timings: dict[str, float] = field(default_factory=dict)

    def timing_summary(self) -> str:
        """Get a formatted summary of timings."""
        if not self.timings:
            return ""
        parts = [f"{step}: {secs:.2f}s" for step, secs in self.timings.items()]
        total = sum(self.timings.values())
        parts.append(f"Total: {total:.2f}s")
        return " | ".join(parts)

    def full_message(self) -> str:
        """Get message with timing information."""
        timing = self.timing_summary()
        if timing:
            return f"{self.message}\n⏱️ {timing}"
        return self.message


class SoundService:
    """Service for managing sounds."""

    @property
    def sounds_dir(self) -> Path:
        """Get the base sounds directory."""
        return Path(settings.sounds_folder)

    def get_sound_dir(self, name: str) -> Path:
        """Get the directory for a specific sound."""
        return self.sounds_dir / sanitize_name(name)

    def get_sound(self, name: str) -> Optional[Sound]:
        """Get a sound by name."""
        return state.sounds.get(name.lower())

    def list_sounds(self) -> dict[str, Sound]:
        """List all sounds."""
        return state.sounds

    def search_sounds(self, query: str) -> list[tuple[str, Sound]]:
        """Search sounds by name (partial match)."""
        query = query.lower()
        results = []
        for name, sound in state.sounds.items():
            if query in name.lower():
                results.append((name, sound))
        return sorted(results, key=lambda x: x[0])

    async def add_sound(
        self,
        name: str,
        url: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
        volume: float = 1.0,
        overwrite: bool = False,
        created: Optional[datetime] = None,
        added_by: Optional[str] = None,
    ) -> OperationResult:
        """
        Add a new sound from a URL.

        Args:
            created: Optional creation date to preserve (e.g. when importing legacy sounds).
            added_by: Username of who added this sound.

        Returns OperationResult with timing information.
        """
        timings: dict[str, float] = {}
        name_lower = name.lower()
        safe_name = sanitize_name(name)

        # Check if sound already exists
        existing_sound = state.sounds.get(name_lower)
        if existing_sound:
            if not overwrite:
                return OperationResult(
                    success=False,
                    message=f"Sound '{name}' already exists. Use /add with overwrite=True to replace it, or /trim to modify timestamps.",
                )

            # Delete the old sound before adding new one
            if existing_sound.is_legacy:
                # Delete legacy files
                if existing_sound.filename:
                    file_path = self.sounds_dir / existing_sound.filename
                    if file_path.exists():
                        file_path.unlink()
                if existing_sound.original_filename:
                    orig_path = self.sounds_dir / existing_sound.original_filename
                    if orig_path.exists():
                        orig_path.unlink()
            else:
                # Delete new format directory
                old_sound_dir = self.sounds_dir / existing_sound.directory
                if old_sound_dir.exists():
                    shutil.rmtree(old_sound_dir)

            # Preserve play counts, created date, and added_by from old sound
            old_discord_plays = existing_sound.discord.plays
            old_twitch_plays = existing_sound.twitch.plays
            old_created = existing_sound.created
            old_added_by = existing_sound.added_by
        else:
            old_discord_plays = 0
            old_twitch_plays = 0
            old_created = None
            old_added_by = None

        sound_dir = self.get_sound_dir(name)

        # Download the source (updates yt-dlp before download)
        download_result = await ytdlp_service.download(url, sound_dir, safe_name)
        for t in download_result.timings:
            timings[t.step] = t.duration_seconds

        if not download_result.success:
            # Clean up on failure
            if sound_dir.exists():
                shutil.rmtree(sound_dir)
            return OperationResult(
                success=False,
                message=f"Failed to download: {download_result.error}",
                timings=timings,
            )

        # Check what we got
        probe = await ffmpeg_service.probe(download_result.original_file)
        if not probe or not probe.has_audio:
            shutil.rmtree(sound_dir)
            return OperationResult(
                success=False,
                message="Downloaded file has no audio",
                timings=timings,
            )

        # Process audio for Discord
        audio_file = sound_dir / f"{safe_name}.ogg"
        audio_result = await ffmpeg_service.extract_and_normalize_audio(
            download_result.original_file,
            audio_file,
            start=start,
            end=end,
            volume=volume,
        )
        if audio_result.duration_seconds:
            timings["Audio processing"] = audio_result.duration_seconds

        if not audio_result.success:
            shutil.rmtree(sound_dir)
            return OperationResult(
                success=False,
                message=f"Failed to process audio: {audio_result.error}",
                timings=timings,
            )

        # If source has video, create trimmed video too
        trimmed_video_file = None
        if probe.has_video:
            video_file = sound_dir / f"{safe_name}_trimmed.mkv"
            video_result = await ffmpeg_service.trim_video(
                download_result.original_file,
                video_file,
                start=start,
                end=end,
            )
            if video_result.success:
                trimmed_video_file = video_file.name
            if video_result.duration_seconds:
                timings["Video trimming"] = video_result.duration_seconds

        # Determine the creation date to use:
        # 1. Explicit created parameter (e.g. from legacy import)
        # 2. Preserved from existing sound being overwritten
        # 3. Current time (default)
        final_created = created or old_created or datetime.now()

        # Determine who added this sound:
        # 1. Explicit added_by parameter
        # 2. Preserved from existing sound being overwritten
        final_added_by = added_by or old_added_by

        # Create sound entry
        sound = Sound(
            directory=safe_name,
            files=SoundFiles(
                original=download_result.original_file.name,
                trimmed_video=trimmed_video_file,
                trimmed_audio=audio_file.name,
                metadata="metadata.json",
                subtitles=download_result.subtitles_file.name
                if download_result.subtitles_file
                else None,
            ),
            source_url=url,
            source_title=download_result.title,
            source_duration=download_result.duration,
            timestamps=Timestamps(start=start, end=end),
            volume=volume,
            created=final_created,
            added_by=final_added_by,
        )

        # Restore play counts if overwriting
        if old_discord_plays > 0 or old_twitch_plays > 0:
            sound.discord.plays = old_discord_plays
            sound.twitch.plays = old_twitch_plays

        state.sounds[name_lower] = sound
        state.save()

        title_info = f" ({download_result.title})" if download_result.title else ""
        action = "Replaced" if overwrite else "Added"
        return OperationResult(
            success=True,
            message=f"{action} sound '{name}'{title_info}",
            timings=timings,
        )

    async def edit_timestamps(
        self,
        name: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
        adjust_start: Optional[float] = None,
        adjust_end: Optional[float] = None,
    ) -> OperationResult:
        """
        Edit the timestamps of an existing sound.

        Can set absolute start/end or adjust them relatively.
        """
        timings: dict[str, float] = {}
        name_lower = name.lower()
        sound = state.sounds.get(name_lower)

        if not sound:
            return OperationResult(success=False, message=f"Sound '{name}' not found")

        # Handle legacy sounds
        if sound.is_legacy:
            return OperationResult(
                success=False,
                message=f"Sound '{name}' is a legacy sound and cannot be edited. Re-add it with /add.",
            )

        sound_dir = self.sounds_dir / sound.directory
        original_file = sound_dir / sound.files.original

        if not original_file.exists():
            return OperationResult(
                success=False,
                message="Original file not found. The sound may need to be re-downloaded.",
            )

        # Calculate new timestamps
        new_start = sound.timestamps.start
        new_end = sound.timestamps.end

        if start is not None:
            new_start = start
        elif adjust_start is not None:
            new_start = (new_start or 0) + adjust_start
            if new_start < 0:
                new_start = 0

        if end is not None:
            new_end = end
        elif adjust_end is not None:
            if new_end is not None:
                new_end = new_end + adjust_end
            elif sound.source_duration is not None:
                new_end = sound.source_duration + adjust_end

        # Validate timestamps
        if new_start is not None and new_end is not None and new_start >= new_end:
            return OperationResult(
                success=False,
                message=f"Start time ({new_start}s) must be less than end time ({new_end}s)",
            )

        # Re-process audio
        safe_name = sanitize_name(name)
        audio_file = sound_dir / f"{safe_name}.ogg"
        audio_result = await ffmpeg_service.extract_and_normalize_audio(
            original_file,
            audio_file,
            start=new_start,
            end=new_end,
            volume=sound.volume,
        )
        if audio_result.duration_seconds:
            timings["Audio processing"] = audio_result.duration_seconds

        if not audio_result.success:
            return OperationResult(
                success=False,
                message=f"Failed to process audio: {audio_result.error}",
                timings=timings,
            )

        # Re-process video if applicable
        probe = await ffmpeg_service.probe(original_file)
        if probe and probe.has_video and sound.files.trimmed_video:
            video_file = sound_dir / sound.files.trimmed_video
            video_result = await ffmpeg_service.trim_video(
                original_file,
                video_file,
                start=new_start,
                end=new_end,
            )
            if video_result.duration_seconds:
                timings["Video trimming"] = video_result.duration_seconds

        # Update sound entry
        sound.timestamps = Timestamps(start=new_start, end=new_end)
        sound.modified = datetime.now()
        state.save()

        ts_str = f"{new_start or 0:.1f}s - {new_end or 'end'}s"
        return OperationResult(
            success=True,
            message=f"Updated timestamps for '{name}' to {ts_str}",
            timings=timings,
        )

    async def set_volume(self, name: str, volume: float) -> OperationResult:
        """
        Set the volume for a sound.

        Volume is a multiplier: 1.0 = normal, 0.5 = half, 2.0 = double.
        """
        timings: dict[str, float] = {}
        name_lower = name.lower()
        sound = state.sounds.get(name_lower)

        if not sound:
            return OperationResult(success=False, message=f"Sound '{name}' not found")

        if volume < 0.1 or volume > 5.0:
            return OperationResult(
                success=False,
                message="Volume must be between 0.1 and 5.0",
            )

        # Handle legacy sounds
        if sound.is_legacy:
            return OperationResult(
                success=False,
                message=f"Sound '{name}' is a legacy sound and cannot be edited. Re-add it with /add to enable editing.",
            )

        sound_dir = self.sounds_dir / sound.directory
        original_file = sound_dir / sound.files.original

        if not original_file.exists():
            return OperationResult(
                success=False,
                message="Original file not found. The sound may need to be re-downloaded.",
            )

        # Re-process audio with new volume
        safe_name = sanitize_name(name)
        audio_file = sound_dir / f"{safe_name}.ogg"
        audio_result = await ffmpeg_service.extract_and_normalize_audio(
            original_file,
            audio_file,
            start=sound.timestamps.start,
            end=sound.timestamps.end,
            volume=volume,
        )
        if audio_result.duration_seconds:
            timings["Audio processing"] = audio_result.duration_seconds

        if not audio_result.success:
            return OperationResult(
                success=False,
                message=f"Failed to process audio: {audio_result.error}",
                timings=timings,
            )

        sound.volume = volume
        sound.modified = datetime.now()
        state.save()

        return OperationResult(
            success=True,
            message=f"Set volume for '{name}' to {volume}x",
            timings=timings,
        )

    async def delete_sound(self, name: str) -> OperationResult:
        """Delete a sound."""
        name_lower = name.lower()
        sound = state.sounds.get(name_lower)

        if not sound:
            return OperationResult(success=False, message=f"Sound '{name}' not found")

        # Delete files based on format
        if sound.is_legacy:
            # Legacy: delete the mp3 file directly
            if sound.filename:
                file_path = self.sounds_dir / sound.filename
                if file_path.exists():
                    file_path.unlink()
            if sound.original_filename:
                orig_path = self.sounds_dir / sound.original_filename
                if orig_path.exists():
                    orig_path.unlink()
        else:
            # New format: delete the directory
            sound_dir = self.sounds_dir / sound.directory
            if sound_dir.exists():
                shutil.rmtree(sound_dir)

        # Remove from state
        del state.sounds[name_lower]
        state.save()

        return OperationResult(success=True, message=f"Deleted sound '{name}'")

    async def rename_sound(self, old_name: str, new_name: str) -> OperationResult:
        """Rename a sound."""
        old_lower = old_name.lower()
        new_lower = new_name.lower()

        sound = state.sounds.get(old_lower)
        if not sound:
            return OperationResult(
                success=False,
                message=f"Sound '{old_name}' not found",
            )

        if new_lower in state.sounds:
            return OperationResult(
                success=False,
                message=f"Sound '{new_name}' already exists",
            )

        # Move sound to new key
        del state.sounds[old_lower]
        state.sounds[new_lower] = sound
        sound.modified = datetime.now()
        state.save()

        return OperationResult(
            success=True,
            message=f"Renamed '{old_name}' to '{new_name}'",
        )

    def get_audio_path(self, name: str) -> Optional[Path]:
        """Get the path to the processed audio file for playback."""
        sound = self.get_sound(name)
        if not sound:
            return None

        # Handle legacy sounds
        if sound.is_legacy:
            if sound.filename:
                return self.sounds_dir / sound.filename
            return None

        # New format
        if sound.directory and sound.files:
            return self.sounds_dir / sound.directory / sound.files.trimmed_audio
        return None

    def get_sound_duration(self, name: str) -> Optional[float]:
        """Get the duration of a sound in seconds (accounting for trim)."""
        sound = self.get_sound(name)
        if not sound:
            return None

        # Start with source duration if available
        duration = sound.source_duration
        if duration is None:
            return None

        # Apply trim timestamps
        trim_start = sound.timestamps.start or 0.0
        trim_end = sound.timestamps.end or duration

        return trim_end - trim_start

    async def regenerate_all_audio(
        self, progress_callback: Optional[callable] = None
    ) -> tuple[int, int, list[str]]:
        """
        Regenerate all audio files for non-legacy sounds.

        Useful when the global audio_file_volume setting has changed.

        Args:
            progress_callback: Optional callback(current, total, name) for progress updates.

        Returns:
            Tuple of (success_count, failure_count, list of failed sound names).
        """
        sounds_to_process = [
            (name, sound)
            for name, sound in state.sounds.items()
            if not sound.is_legacy and sound.files
        ]

        total = len(sounds_to_process)
        success_count = 0
        failed = []

        for i, (name, sound) in enumerate(sounds_to_process):
            if progress_callback:
                progress_callback(i + 1, total, name)

            sound_dir = self.sounds_dir / sound.directory
            original_file = sound_dir / sound.files.original

            if not original_file.exists():
                logger.warning(f"Original file not found for '{name}': {original_file}")
                failed.append(name)
                continue

            # Re-process audio with current volume settings
            audio_file = sound_dir / sound.files.trimmed_audio
            audio_result = await ffmpeg_service.extract_and_normalize_audio(
                original_file,
                audio_file,
                start=sound.timestamps.start,
                end=sound.timestamps.end,
                volume=sound.volume,
            )

            if audio_result.success:
                success_count += 1
            else:
                logger.error(f"Failed to regenerate audio for '{name}': {audio_result.error}")
                failed.append(name)

        return success_count, len(failed), failed


# Singleton instance
sound_service = SoundService()
