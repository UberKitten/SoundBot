"""Service for Discord voice channel management and audio playback."""

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import discord

logger = logging.getLogger(__name__)


def format_duration(seconds: Optional[float]) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds is None:
        return ""

    if seconds < 60:
        return f"({seconds:.0f}s)"

    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"({minutes}:{secs:02d})"


@dataclass
class QueueItem:
    """An item in the playback queue."""

    audio_path: Path
    name: str  # Display name for the sound
    user: Optional[discord.Member] = None
    added_at: datetime = field(default_factory=datetime.now)
    seek_position: float = 0.0  # Position to seek to in seconds (for resume)
    duration: Optional[float] = None  # Duration in seconds


@dataclass
class GuildPlaybackState:
    """Playback state for a guild."""

    queue: deque[QueueItem] = field(default_factory=deque)
    current: Optional[QueueItem] = None
    current_started_at: Optional[datetime] = None  # When current item started playing
    is_paused: bool = False
    voice_client: Optional[discord.VoiceClient] = None
    play_task: Optional[asyncio.Task] = None


class VoiceService:
    """Service for managing voice connections and audio playback."""

    def __init__(self):
        # Track last activity per user per guild: {guild_id: {user_id: datetime}}
        self._user_activity: dict[int, dict[int, datetime]] = defaultdict(dict)
        # Playback state per guild
        self._states: dict[int, GuildPlaybackState] = {}
        # Activity timeout - users inactive for longer are not considered
        self._activity_timeout = timedelta(minutes=30)
        # Lock per guild for queue operations
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _get_state(self, guild_id: int) -> GuildPlaybackState:
        """Get or create playback state for a guild."""
        if guild_id not in self._states:
            self._states[guild_id] = GuildPlaybackState()
        return self._states[guild_id]

    def record_user_activity(self, guild_id: int, user_id: int):
        """Record that a user triggered a sound command."""
        self._user_activity[guild_id][user_id] = datetime.now()

    def _get_recent_users(self, guild_id: int) -> set[int]:
        """Get users who have used the soundbot recently."""
        now = datetime.now()
        recent = set()
        if guild_id in self._user_activity:
            for user_id, last_active in self._user_activity[guild_id].items():
                if now - last_active < self._activity_timeout:
                    recent.add(user_id)
        return recent

    async def find_best_channel(
        self,
        guild: discord.Guild,
        user: Optional[discord.Member] = None,
    ) -> Optional[discord.VoiceChannel]:
        """
        Find the best voice channel to join.

        Priority:
        1. The channel the requesting user is in (if any)
        2. A channel with users who recently used the soundbot
        3. The channel with the most members
        4. None if no suitable channel found
        """
        logger.debug(
            f"Finding best voice channel in {guild.name} for user: {user.name if user else 'None'}"
        )

        # Option 1: User's current channel
        if user and user.voice and user.voice.channel:
            channel = user.voice.channel
            if isinstance(channel, discord.VoiceChannel):
                logger.debug(f"Using user's current channel: {channel.name}")
                return channel

        # Get all voice channels with members (excluding bots)
        populated_channels: list[tuple[discord.VoiceChannel, int, int]] = []
        recent_users = self._get_recent_users(guild.id)

        for channel in guild.voice_channels:
            # Count non-bot members
            members = [m for m in channel.members if not m.bot]
            if not members:
                continue

            # Count how many recent soundbot users are in this channel
            recent_count = sum(1 for m in members if m.id in recent_users)
            populated_channels.append((channel, len(members), recent_count))

        if not populated_channels:
            logger.debug("No populated voice channels found")
            return None

        # Option 2: Sort by recent users first, then by member count
        populated_channels.sort(key=lambda x: (x[2], x[1]), reverse=True)

        best_channel = populated_channels[0][0]
        logger.debug(
            f"Selected channel: {best_channel.name} "
            f"(members: {populated_channels[0][1]}, recent: {populated_channels[0][2]})"
        )
        return best_channel

    async def connect(
        self,
        channel: discord.VoiceChannel,
    ) -> Optional[discord.VoiceClient]:
        """Connect to a voice channel, or move if already connected in guild."""
        guild_id = channel.guild.id
        state = self._get_state(guild_id)

        # Check if already connected in this guild
        if state.voice_client and state.voice_client.is_connected():
            if state.voice_client.channel.id == channel.id:
                logger.debug(f"Already connected to {channel.name}")
                return state.voice_client
            # Move to new channel
            logger.info(
                f"Moving from {state.voice_client.channel.name} to {channel.name}"
            )
            await state.voice_client.move_to(channel)
            return state.voice_client

        # Clean up any stale voice client
        if state.voice_client:
            logger.warning("Found stale voice client, cleaning up...")
            try:
                await state.voice_client.disconnect(force=True)
            except Exception:
                pass
            state.voice_client = None

        try:
            logger.info(
                f"Connecting to voice channel: {channel.name} (ID: {channel.id}) in guild: {channel.guild.name}"
            )
            voice_client = await channel.connect(timeout=10.0, reconnect=False)
            state.voice_client = voice_client
            logger.info(f"Successfully connected to {channel.name}")
            return voice_client
        except Exception as e:
            logger.error(
                f"Failed to connect to {channel.name}: {type(e).__name__}: {e}",
                exc_info=True,
            )
            # Clean up failed connection attempt
            if state.voice_client:
                try:
                    await state.voice_client.disconnect(force=True)
                except Exception:
                    pass
                state.voice_client = None
            return None

    async def disconnect(self, guild_id: int):
        """Disconnect from voice in a guild."""
        state = self._get_state(guild_id)
        if state.voice_client and state.voice_client.is_connected():
            await state.voice_client.disconnect()
        state.voice_client = None
        # Clear queue on disconnect
        state.queue.clear()
        state.current = None

    async def _play_next(self, guild: discord.Guild):
        """Play the next item in the queue."""
        state = self._get_state(guild.id)

        if not state.queue:
            state.current = None
            return

        # Get next item
        item = state.queue.popleft()
        state.current = item

        if not item.audio_path.exists():
            logger.error(f"Audio file not found: {item.audio_path}")
            # Try next in queue
            await self._play_next(guild)
            return

        # Find channel to play in
        channel = await self.find_best_channel(guild, item.user)
        if not channel:
            logger.error("No voice channel found to play in")
            state.current = None
            return

        # Connect to channel
        voice_client = await self.connect(channel)
        if not voice_client:
            logger.error(f"Could not connect to {channel.name}")
            state.current = None
            return

        # Record activity for the user
        if item.user:
            self.record_user_activity(guild.id, item.user.id)

        # Create a future to wait for playback completion
        loop = asyncio.get_event_loop()
        done_event = asyncio.Event()

        def after_play(error):
            if error:
                logger.error(f"Playback error: {error}")
            loop.call_soon_threadsafe(done_event.set)

        # Play the audio
        try:
            # Use FFmpeg seek if we have a position to resume from
            if item.seek_position > 0:
                logger.info(f"Resuming playback from {item.seek_position:.1f}s")
                source = discord.FFmpegOpusAudio(
                    str(item.audio_path),
                    before_options=f"-ss {item.seek_position:.3f}",
                )
            else:
                source = discord.FFmpegOpusAudio(str(item.audio_path))

            # Track when playback started
            state.current_started_at = datetime.now()
            voice_client.play(source, after=after_play)

            # Wait for playback to complete (or be stopped)
            await done_event.wait()

            # Clear start time after playback
            state.current_started_at = None

            # Play next if not paused and not stopped
            if not state.is_paused:
                await self._play_next(guild)

        except Exception as e:
            logger.error(f"Failed to play audio: {e}")
            state.current = None
            await self._play_next(guild)

    async def queue_sound(
        self,
        guild: discord.Guild,
        audio_path: Path,
        name: str,
        user: Optional[discord.Member] = None,
        play_next: bool = False,
        duration: Optional[float] = None,
    ) -> tuple[bool, str]:
        """
        Add a sound to the queue.

        If play_next is True, adds to the front of the queue.
        Returns (success, message).
        """
        if not audio_path.exists():
            return False, "Audio file not found"

        state = self._get_state(guild.id)
        item = QueueItem(audio_path=audio_path, name=name, user=user, duration=duration)

        async with self._locks[guild.id]:
            if play_next:
                state.queue.appendleft(item)
            else:
                state.queue.append(item)

            # If nothing is playing, start playing
            if state.current is None and not state.is_paused:
                # Start playback in a task so we don't block
                state.play_task = asyncio.create_task(self._play_next(guild))
                duration_str = f" {format_duration(duration)}" if duration else ""
                return True, f"Playing **{name}**{duration_str}"
            else:
                position = len(state.queue) if not play_next else 1
                duration_str = f" {format_duration(duration)}" if duration else ""
                return True, f"Queued **{name}**{duration_str} (position {position})"

    async def play_sound(
        self,
        guild: discord.Guild,
        audio_path: Path,
        name: str = "sound",
        user: Optional[discord.Member] = None,
        duration: Optional[float] = None,
    ) -> tuple[bool, str]:
        """
        Play a sound in the best available channel.
        Adds to queue if something is already playing.

        Returns (success, message).
        """
        return await self.queue_sound(guild, audio_path, name, user, duration=duration)

    async def play_now(
        self,
        guild: discord.Guild,
        audio_path: Path,
        name: str,
        user: Optional[discord.Member] = None,
        duration: Optional[float] = None,
    ) -> tuple[bool, str]:
        """
        Play a sound immediately, pausing current playback.
        After this sound finishes, resumes the previous sound from where it was stopped.

        Returns (success, message).
        """
        if not audio_path.exists():
            return False, "Audio file not found"

        state = self._get_state(guild.id)

        # If something is playing, save its current position and pause it
        if state.current and state.voice_client and state.voice_client.is_playing():
            # Calculate how far into the sound we are
            if state.current_started_at:
                elapsed = (datetime.now() - state.current_started_at).total_seconds()
                # Update seek position for resume
                state.current.seek_position += elapsed
                logger.debug(
                    f"Saving playback position: {state.current.seek_position:.1f}s"
                )
            else:
                # This shouldn't happen, but log if it does
                logger.warning(
                    "Sound is playing but current_started_at is None - cannot save position"
                )

            # Push current back to front of queue
            state.queue.appendleft(state.current)
            # Stop current (will trigger next to play)
            state.voice_client.stop()

        # Add the new sound to front of queue
        item = QueueItem(audio_path=audio_path, name=name, user=user, duration=duration)
        state.queue.appendleft(item)

        # If nothing is playing now, start playback
        if state.current is None:
            state.play_task = asyncio.create_task(self._play_next(guild))

        duration_str = f" {format_duration(duration)}" if duration else ""
        return True, f"Playing **{name}**{duration_str} now"

    async def skip(self, guild_id: int) -> tuple[bool, str]:
        """Skip the current sound and play the next one."""
        state = self._get_state(guild_id)

        if not state.current and not state.queue:
            return False, "Nothing is playing or queued"

        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.stop()  # This triggers after_play callback
            return (
                True,
                f"Skipped **{state.current.name if state.current else 'current'}**",
            )

        return False, "Nothing is currently playing"

    async def stop(self, guild_id: int) -> tuple[bool, str]:
        """Stop playback and clear the queue."""
        state = self._get_state(guild_id)

        if not state.current and not state.queue:
            return False, "Nothing is playing or queued"

        # Clear queue first
        queue_count = len(state.queue)
        state.queue.clear()
        state.is_paused = False

        # Stop current playback
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.stop()

        state.current = None

        if queue_count > 0:
            return True, f"Stopped playback and cleared {queue_count} queued sounds"
        return True, "Stopped playback"

    async def pause(self, guild_id: int) -> tuple[bool, str]:
        """Pause the current playback."""
        state = self._get_state(guild_id)

        if not state.voice_client:
            return False, "Not connected to voice"

        if state.is_paused:
            return False, "Already paused"

        if state.voice_client.is_playing():
            state.voice_client.pause()
            state.is_paused = True
            return (
                True,
                f"Paused **{state.current.name if state.current else 'playback'}**",
            )

        return False, "Nothing is playing"

    async def resume(self, guild_id: int) -> tuple[bool, str]:
        """Resume paused playback."""
        state = self._get_state(guild_id)

        if not state.voice_client:
            return False, "Not connected to voice"

        if not state.is_paused:
            return False, "Not paused"

        if state.voice_client.is_paused():
            state.voice_client.resume()
            state.is_paused = False
            return (
                True,
                f"Resumed **{state.current.name if state.current else 'playback'}**",
            )

        # If was paused but nothing playing, resume queue
        state.is_paused = False
        if state.queue:
            asyncio.create_task(self._play_next(state.voice_client.guild))
            return True, "Resumed queue playback"

        return False, "Nothing to resume"

    def get_queue(self, guild_id: int) -> list[QueueItem]:
        """Get the current queue for a guild."""
        state = self._get_state(guild_id)
        return list(state.queue)

    def get_current(self, guild_id: int) -> Optional[QueueItem]:
        """Get the currently playing item."""
        state = self._get_state(guild_id)
        return state.current

    def is_playing(self, guild_id: int) -> bool:
        """Check if audio is currently playing in a guild."""
        state = self._get_state(guild_id)
        return state.voice_client is not None and state.voice_client.is_playing()

    def is_paused(self, guild_id: int) -> bool:
        """Check if playback is paused."""
        return self._get_state(guild_id).is_paused

    async def disconnect_all(self):
        """Disconnect from all voice channels in all guilds."""
        for guild_id in list(self._states.keys()):
            try:
                await self.disconnect(guild_id)
                logger.info(f"Disconnected from guild {guild_id}")
            except Exception as e:
                logger.error(f"Error disconnecting from guild {guild_id}: {e}")


# Singleton instance
voice_service = VoiceService()
