import asyncio
import logging
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.sounds import sound_service
from soundbot.services.voice import voice_service
from soundbot.services.ytdlp import ytdlp_service

logger = logging.getLogger(__name__)


def strip_command_prefix(name: str) -> str:
    """Strip any command prefix from a sound name.

    Users can provide sound names with or without prefixes like !soundname,
    this function strips them if present.
    """
    prefixes = settings.twitch_command_prefixes or ["!"]
    for prefix in prefixes:
        if name.startswith(prefix):
            return name[len(prefix) :].strip()
    return name


class SoundBot(commands.Bot):
    """Discord bot for soundboard functionality."""

    def __init__(self):
        # Set up intents - we need voice states and message content for text commands
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.message_content = True
        intents.guilds = True

        # Use all configured prefixes
        prefixes = settings.twitch_command_prefixes or ["!"]

        super().__init__(
            command_prefix=prefixes,
            intents=intents,
            help_command=None,  # We'll make our own
        )

        self.test_guild_ids: list[int] = []
        if settings.test_guild_ids:
            for id_str in settings.test_guild_ids.split(","):
                try:
                    self.test_guild_ids.append(int(id_str.strip()))
                except ValueError:
                    pass

    @property
    def test_guilds(self) -> list[discord.Object]:
        """Get test guilds as Discord objects."""
        return [discord.Object(id=gid) for gid in self.test_guild_ids]

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")
        prefixes = settings.twitch_command_prefixes or ["!"]
        logger.info(f"Command prefixes: {prefixes}")

    async def setup_hook(self):
        """Called when the bot is starting up."""
        # Add cogs
        await self.add_cog(SoundCommands(self))
        await self.add_cog(PlaybackCog(self))
        await self.add_cog(QueueCog(self))
        await self.add_cog(UserSettingsCog(self))
        await self.add_cog(VoiceEventsCog(self))

        # Sync commands to test guilds (faster) or globally
        if self.test_guild_ids:
            for guild_id in self.test_guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"Synced commands to guild {guild_id}")
        else:
            await self.tree.sync()
            logger.info("Synced commands globally")

    async def close(self):
        """Called when the bot is shutting down."""
        logger.info("Bot shutting down, disconnecting from all voice channels...")
        await voice_service.disconnect_all()
        await super().close()


class SoundCommands(commands.Cog):
    """Slash commands for sound management (CRUD)."""

    def __init__(self, bot: SoundBot):
        self.bot = bot

    @app_commands.command(name="add")
    @app_commands.describe(
        name="Name for the sound (used to play it)",
        url="URL to download from (YouTube, etc.)",
        start="Start time in seconds (optional)",
        end="End time in seconds (optional)",
        volume="Volume multiplier, 0.1-5.0, default 1.0 (optional)",
        overwrite="Overwrite existing sound if it exists (default: False)",
    )
    async def add_sound(
        self,
        interaction: Interaction,
        name: str,
        url: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
        volume: Optional[float] = 1.0,
        overwrite: bool = False,
    ):
        """Add a new sound from a URL."""
        await interaction.response.defer(thinking=True)

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        logger.info(
            f"User {interaction.user} ({interaction.user.id}) adding sound '{name}' from {url}"
        )

        result = await sound_service.add_sound(
            name=name,
            url=url,
            start=start,
            end=end,
            volume=volume or 1.0,
            overwrite=overwrite,
        )

        emoji = "✅" if result.success else "❌"
        await interaction.followup.send(f"{emoji} {result.full_message()}")

    @app_commands.command(name="delete")
    @app_commands.describe(name="Name of the sound to delete")
    async def delete_sound(self, interaction: Interaction, name: str):
        """Delete a sound."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        result = await sound_service.delete_sound(name)
        emoji = "✅" if result.success else "❌"
        await interaction.response.send_message(f"{emoji} {result.message}")

    @app_commands.command(name="rename")
    @app_commands.describe(
        old_name="Current name of the sound",
        new_name="New name for the sound",
    )
    async def rename_sound(
        self,
        interaction: Interaction,
        old_name: str,
        new_name: str,
    ):
        """Rename a sound."""
        # Strip any command prefix from the names
        old_name = strip_command_prefix(old_name)
        new_name = strip_command_prefix(new_name)
        result = await sound_service.rename_sound(old_name, new_name)
        emoji = "✅" if result.success else "❌"
        await interaction.response.send_message(f"{emoji} {result.message}")

    @app_commands.command(name="trim")
    @app_commands.describe(
        name="Name of the sound",
        start="New start time in seconds",
        end="New end time in seconds",
    )
    async def trim_sound(
        self,
        interaction: Interaction,
        name: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ):
        """Set new start/end times for a sound."""
        await interaction.response.defer(thinking=True)

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        result = await sound_service.edit_timestamps(
            name=name,
            start=start,
            end=end,
        )

        emoji = "✅" if result.success else "❌"
        await interaction.followup.send(f"{emoji} {result.full_message()}")

    @app_commands.command(name="adjust")
    @app_commands.describe(
        name="Name of the sound",
        start_offset="Seconds to add/remove from start (negative = earlier)",
        end_offset="Seconds to add/remove from end (negative = shorter)",
    )
    async def adjust_sound(
        self,
        interaction: Interaction,
        name: str,
        start_offset: Optional[float] = None,
        end_offset: Optional[float] = None,
    ):
        """Adjust start/end times relatively."""
        await interaction.response.defer(thinking=True)

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        result = await sound_service.edit_timestamps(
            name=name,
            adjust_start=start_offset,
            adjust_end=end_offset,
        )

        emoji = "✅" if result.success else "❌"
        await interaction.followup.send(f"{emoji} {result.full_message()}")

    @app_commands.command(name="volume")
    @app_commands.describe(
        name="Name of the sound",
        level="Volume level (0.1 to 5.0, 1.0 = normal)",
    )
    async def set_volume(
        self,
        interaction: Interaction,
        name: str,
        level: float,
    ):
        """Set the volume for a sound."""
        await interaction.response.defer(thinking=True)

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        result = await sound_service.set_volume(name, level)

        emoji = "✅" if result.success else "❌"
        await interaction.followup.send(f"{emoji} {result.full_message()}")

    @app_commands.command(name="info")
    @app_commands.describe(name="Name of the sound")
    async def sound_info(self, interaction: Interaction, name: str):
        """Get information about a sound."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        sound = sound_service.get_sound(name)
        if not sound:
            await interaction.response.send_message(f"❌ Sound '{name}' not found")
            return

        embed = discord.Embed(title=f"🔊 {name}", color=discord.Color.blue())

        if sound.source_title:
            embed.add_field(name="Title", value=sound.source_title, inline=False)
        if sound.source_url:
            embed.add_field(name="Source", value=sound.source_url, inline=False)
        if sound.source_duration:
            embed.add_field(
                name="Original Duration",
                value=f"{sound.source_duration:.1f}s",
                inline=True,
            )

        # Timestamps
        ts = sound.timestamps
        if ts.start or ts.end:
            ts_str = f"{ts.start or 0:.1f}s - {ts.end or 'end'}s"
            embed.add_field(name="Trim", value=ts_str, inline=True)

        embed.add_field(name="Volume", value=f"{sound.volume:.1f}x", inline=True)
        embed.add_field(
            name="Discord Plays",
            value=str(sound.discord.plays),
            inline=True,
        )

        embed.set_footer(text=f"Created: {sound.created.strftime('%Y-%m-%d')}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="sounds")
    @app_commands.describe(search="Search term (optional)")
    async def sounds(
        self,
        interaction: Interaction,
        search: Optional[str] = None,
    ):
        """Browse sounds on the web UI or search for sounds."""
        if search:
            # Search for sounds
            results = sound_service.search_sounds(search)
            if not results:
                await interaction.response.send_message(
                    f"❌ No sounds matching '{search}'"
                )
                return

            names = [name for name, _ in results]

            # Paginate if too many
            chunks = [names[i : i + 50] for i in range(0, len(names), 50)]

            embed = discord.Embed(
                title=f"🔊 Sounds matching '{search}' ({len(names)} total)",
                description=", ".join(chunks[0]),
                color=discord.Color.blue(),
            )

            if len(chunks) > 1:
                embed.set_footer(text=f"Showing first 50 of {len(names)}")

            await interaction.response.send_message(embed=embed)
        else:
            # Direct to web UI
            embed = discord.Embed(
                title="🔊 Browse Sounds",
                description="Visit the web interface to browse, search, and preview all sounds:",
                color=discord.Color.blue(),
                url=f"https://{settings.web_ui_url}",
            )
            embed.add_field(
                name="Web UI",
                value=f"[{settings.web_ui_url}](https://{settings.web_ui_url})",
                inline=False,
            )
            embed.add_field(
                name="Tip",
                value="Use `/sounds <search>` to search from Discord",
                inline=False,
            )
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="list")
    @app_commands.describe(search="Search term (optional)")
    async def list_sounds(
        self,
        interaction: Interaction,
        search: Optional[str] = None,
    ):
        """List all sounds or search for sounds."""
        if search:
            results = sound_service.search_sounds(search)
            if not results:
                await interaction.response.send_message(
                    f"❌ No sounds matching '{search}'"
                )
                return
            names = [name for name, _ in results]
            title = f"Sounds matching '{search}'"
        else:
            names = sorted(sound_service.list_sounds().keys())
            if not names:
                await interaction.response.send_message(
                    "No sounds yet! Use /add to add some."
                )
                return
            title = "All Sounds"

        # Paginate if too many
        chunks = [names[i : i + 50] for i in range(0, len(names), 50)]

        embed = discord.Embed(
            title=f"🔊 {title} ({len(names)} total)",
            description=", ".join(chunks[0]),
            color=discord.Color.blue(),
        )

        if len(chunks) > 1:
            embed.set_footer(text=f"Showing first 50 of {len(names)}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="random")
    async def random_sound(self, interaction: Interaction):
        """Play a random sound (max 2 minutes)."""
        # Get all sounds
        all_sounds = sound_service.list_sounds()
        if not all_sounds:
            await interaction.response.send_message("❌ No sounds available")
            return

        # Filter to sounds under 2 minutes (120 seconds)
        MAX_DURATION = 120.0
        eligible = []
        for name, sound in all_sounds.items():
            # Calculate effective duration
            duration = None
            if sound.timestamps.start is not None or sound.timestamps.end is not None:
                # Use trimmed duration
                start = sound.timestamps.start or 0
                end = sound.timestamps.end or sound.source_duration
                if end:
                    duration = end - start
            elif sound.source_duration:
                # Use original duration
                duration = sound.source_duration

            # Include if under limit or duration unknown
            if duration is None or duration <= MAX_DURATION:
                eligible.append(name)

        if not eligible:
            await interaction.response.send_message(
                "❌ No sounds under 2 minutes available"
            )
            return

        # Pick random sound
        name = random.choice(eligible)
        audio_path = sound_service.get_audio_path(name)
        if not audio_path:
            await interaction.response.send_message(f"❌ Sound '{name}' not found")
            return

        # Get duration for display
        duration = sound_service.get_sound_duration(name)

        # Play it
        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild
            else None
        )
        success, message = await voice_service.play_sound(
            interaction.guild, audio_path, name=name, user=member, duration=duration
        )

        emoji = "🎲" if success else "❌"
        await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="play")
    @app_commands.describe(
        url="URL to download and play (YouTube, etc.)",
        start="Start time in seconds (optional)",
        end="End time in seconds (optional)",
    )
    async def quick_play(
        self,
        interaction: Interaction,
        url: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ):
        """Download and play audio from a URL without saving it."""
        await interaction.response.defer(thinking=True)

        # Download to temp directory
        download_result = await ytdlp_service.download_temp(url)
        if not download_result.success:
            await interaction.followup.send(
                f"❌ Download failed: {download_result.error}"
            )
            return

        # Get temp directory for cleanup
        temp_dir = download_result.original_file.parent

        # Process audio
        temp_audio = download_result.original_file.with_suffix(".ogg")
        audio_result = await ffmpeg_service.extract_and_normalize_audio(
            download_result.original_file,
            temp_audio,
            start=start,
            end=end,
        )

        if not audio_result.success:
            await interaction.followup.send(
                f"❌ Audio processing failed: {audio_result.error}"
            )
            # Clean up temp directory on failure
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            return

        # Play it
        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild
            else None
        )
        title = download_result.title or "Quick play"

        # Get duration from audio result
        duration = audio_result.duration_seconds

        success, message = await voice_service.play_sound(
            interaction.guild,
            temp_audio,
            name=title,
            user=member,
            duration=duration,
        )

        if success:
            timing_parts = []
            for t in download_result.timings:
                timing_parts.append(f"{t.step}: {t.duration_seconds:.2f}s")
            if audio_result.duration_seconds:
                timing_parts.append(f"Audio: {audio_result.duration_seconds:.2f}s")
            timing_str = " | ".join(timing_parts) if timing_parts else ""

            msg = f"🎵 {message}"
            if timing_str:
                msg += f"\n⏱️ {timing_str}"
            await interaction.followup.send(msg)

            # Schedule cleanup after playback (give it time to start playing)
            async def cleanup_temp_dir():
                # Wait for sound to finish playing (approximate based on duration)
                wait_time = audio_result.duration_seconds or 60
                await asyncio.sleep(wait_time + 5)  # Add 5 second buffer
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")

            asyncio.create_task(cleanup_temp_dir())
        else:
            await interaction.followup.send(f"❌ {message}")
            # Clean up temp directory on failure
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


class QueueCog(commands.Cog):
    """Commands for queue management."""

    def __init__(self, bot: SoundBot):
        self.bot = bot

    @app_commands.command(name="playnext")
    @app_commands.describe(name="Name of the sound")
    async def play_next_slash(self, interaction: Interaction, name: str):
        """Add a sound to play next in the queue."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        audio_path = sound_service.get_audio_path(name)
        if not audio_path:
            # Try partial match
            matches = sound_service.search_sounds(name)
            if len(matches) == 1:
                audio_path = sound_service.get_audio_path(matches[0][0])
                name = matches[0][0]
            elif len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
                return
            else:
                await interaction.response.send_message(f"❌ Sound '{name}' not found")
                return

        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild
            else None
        )
        duration = sound_service.get_sound_duration(name)
        success, message = await voice_service.queue_sound(
            interaction.guild,
            audio_path,
            name,
            user=member,
            play_next=True,
            duration=duration,
        )

        emoji = "⏭️" if success else "❌"
        await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="playnow")
    @app_commands.describe(name="Name of the sound")
    async def play_now_slash(self, interaction: Interaction, name: str):
        """Play a sound immediately, pausing the current sound."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        audio_path = sound_service.get_audio_path(name)
        if not audio_path:
            # Try partial match
            matches = sound_service.search_sounds(name)
            if len(matches) == 1:
                audio_path = sound_service.get_audio_path(matches[0][0])
                name = matches[0][0]
            elif len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
                return
            else:
                await interaction.response.send_message(f"❌ Sound '{name}' not found")
                return

        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild
            else None
        )
        duration = sound_service.get_sound_duration(name)
        success, message = await voice_service.play_now(
            interaction.guild,
            audio_path,
            name,
            user=member,
            duration=duration,
        )

        emoji = "🎵" if success else "❌"
        await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="queue")
    async def show_queue(self, interaction: Interaction):
        """Show the current playback queue."""
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        current = voice_service.get_current(interaction.guild.id)
        queue = voice_service.get_queue(interaction.guild.id)
        is_paused = voice_service.is_paused(interaction.guild.id)

        if not current and not queue:
            await interaction.response.send_message("📭 Queue is empty")
            return

        embed = discord.Embed(title="🎵 Playback Queue", color=discord.Color.blue())

        # Current playing
        if current:
            status = "⏸️ Paused" if is_paused else "▶️ Now Playing"
            embed.add_field(
                name=status,
                value=f"**{current.name}**",
                inline=False,
            )

        # Queue
        if queue:
            queue_text = "\n".join(
                f"{i + 1}. {item.name}" for i, item in enumerate(queue[:10])
            )
            if len(queue) > 10:
                queue_text += f"\n... and {len(queue) - 10} more"
            embed.add_field(name="Up Next", value=queue_text, inline=False)
        else:
            embed.add_field(name="Up Next", value="Nothing queued", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="skip")
    async def skip_sound(self, interaction: Interaction):
        """Skip the current sound."""
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        success, message = await voice_service.skip(interaction.guild.id)
        emoji = "⏭️" if success else "❌"
        await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="stop")
    async def stop_playback(self, interaction: Interaction):
        """Stop playback and clear the queue."""
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        success, message = await voice_service.stop(interaction.guild.id)
        emoji = "⏹️" if success else "❌"
        await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="pause")
    async def pause_playback(self, interaction: Interaction):
        """Pause playback."""
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        success, message = await voice_service.pause(interaction.guild.id)
        emoji = "⏸️" if success else "❌"
        await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="resume")
    async def resume_playback(self, interaction: Interaction):
        """Resume playback."""
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        success, message = await voice_service.resume(interaction.guild.id)
        emoji = "▶️" if success else "❌"
        await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="leave")
    async def leave_channel(self, interaction: Interaction):
        """Leave the voice channel."""
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        await voice_service.disconnect(interaction.guild.id)
        await interaction.response.send_message("👋 Left voice channel")


class PlaybackCog(commands.Cog):
    """Text commands for sound playback and file uploads."""

    def __init__(self, bot: SoundBot):
        self.bot = bot
        # Get all configured prefixes
        self.prefixes = settings.twitch_command_prefixes or ["!"]

    @commands.command(name="add")
    async def add_sound_file(self, ctx: commands.Context, name: str, source_url: Optional[str] = None):
        """
        Add a sound from an attached audio file.

        Usage: !add soundname [optional_source_url]
        Attach an audio file (mp3, wav, ogg, etc.) to your message.
        """
        # Check for attachment
        if not ctx.message.attachments:
            await ctx.send("❌ Please attach an audio file to your message.\nUsage: `!add soundname` with an audio file attached.")
            return

        attachment = ctx.message.attachments[0]

        # Validate it looks like an audio file
        audio_extensions = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus", ".webm", ".mp4", ".mkv"}
        ext = Path(attachment.filename).suffix.lower()
        if ext not in audio_extensions:
            await ctx.send(f"❌ File doesn't appear to be audio. Supported formats: {', '.join(sorted(audio_extensions))}")
            return

        # Size limit (e.g., 25MB)
        max_size = 25 * 1024 * 1024
        if attachment.size > max_size:
            await ctx.send(f"❌ File too large. Maximum size is 25MB.")
            return

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        # Show progress
        progress_msg = await ctx.send(f"⏳ Processing `{name}` from uploaded file...")

        try:
            # Download the attachment
            file_data = await attachment.read()

            # Add the sound
            result = await sound_service.add_sound_from_file(
                name=name,
                file_data=file_data,
                original_filename=attachment.filename,
                source_url=source_url,
                added_by=str(ctx.author),
            )

            emoji = "✅" if result.success else "❌"
            await progress_msg.edit(content=f"{emoji} {result.full_message()}")

        except Exception as e:
            logger.error(f"Error adding sound from file: {e}")
            await progress_msg.edit(content=f"❌ Error: {e}")

    @commands.command(name="stop")
    async def stop_playback(self, ctx: commands.Context):
        """Stop the currently playing sound."""
        success, _ = await voice_service.stop(ctx.guild.id)
        if success:
            await ctx.send("⏹️ Stopped playback")
        else:
            await ctx.send("❌ Nothing is playing")

    @commands.command(name="skip")
    async def skip_sound(self, ctx: commands.Context):
        """Skip the current sound."""
        success, message = await voice_service.skip(ctx.guild.id)
        emoji = "⏭️" if success else "❌"
        await ctx.send(f"{emoji} {message}")

    @commands.command(name="pause")
    async def pause_playback(self, ctx: commands.Context):
        """Pause playback."""
        success, message = await voice_service.pause(ctx.guild.id)
        emoji = "⏸️" if success else "❌"
        await ctx.send(f"{emoji} {message}")

    @commands.command(name="resume", aliases=["unpause"])
    async def resume_playback(self, ctx: commands.Context):
        """Resume playback."""
        success, message = await voice_service.resume(ctx.guild.id)
        emoji = "▶️" if success else "❌"
        await ctx.send(f"{emoji} {message}")

    @commands.command(name="queue", aliases=["q"])
    async def show_queue(self, ctx: commands.Context):
        """Show the queue."""
        current = voice_service.get_current(ctx.guild.id)
        queue = voice_service.get_queue(ctx.guild.id)

        if not current and not queue:
            await ctx.send("📭 Queue is empty")
            return

        parts = []
        if current:
            status = "⏸️" if voice_service.is_paused(ctx.guild.id) else "▶️"
            parts.append(f"{status} **{current.name}**")

        if queue:
            for i, item in enumerate(queue[:5]):
                parts.append(f"{i + 1}. {item.name}")
            if len(queue) > 5:
                parts.append(f"... +{len(queue) - 5} more")

        await ctx.send("\n".join(parts))

    @commands.command(name="leave")
    async def leave_voice(self, ctx: commands.Context):
        """Leave the voice channel."""
        await voice_service.disconnect(ctx.guild.id)
        await ctx.send("👋 Left voice channel")

    @commands.command(name="sounds")
    async def quick_list(self, ctx: commands.Context, *, search: Optional[str] = None):
        """Quick list of sounds."""
        if search:
            results = sound_service.search_sounds(search)
            names = [name for name, _ in results]
        else:
            names = sorted(sound_service.list_sounds().keys())

        if not names:
            await ctx.send("No sounds found.")
            return

        # Show first 30 in a compact format
        display = names[:30]
        msg = f"**Sounds:** {', '.join(display)}"
        if len(names) > 30:
            msg += f" (+{len(names) - 30} more)"
        await ctx.send(msg)

    @commands.command(name="next", aliases=["playnext"])
    async def play_next(self, ctx: commands.Context, *, sound_name: str):
        """Add a sound to play next in the queue."""
        # Strip any command prefix from the name
        sound_name = strip_command_prefix(sound_name)
        audio_path = sound_service.get_audio_path(sound_name)
        if not audio_path:
            # Try partial match
            matches = sound_service.search_sounds(sound_name)
            if len(matches) == 1:
                audio_path = sound_service.get_audio_path(matches[0][0])
                sound_name = matches[0][0]
            elif len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                await ctx.send(
                    f"Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
                return
            else:
                await ctx.send(f"❌ Sound '{sound_name}' not found")
                return

        member = ctx.guild.get_member(ctx.author.id)
        duration = sound_service.get_sound_duration(sound_name)
        success, message = await voice_service.queue_sound(
            ctx.guild,
            audio_path,
            sound_name,
            user=member,
            play_next=True,
            duration=duration,
        )

        if success:
            sound = sound_service.get_sound(sound_name)
            if sound:
                sound.discord.plays += 1
                sound.discord.last_played = datetime.now()
                state.save()
            await ctx.send(f"⏭️ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for prefix+soundname commands to play sounds."""
        if message.author.bot:
            return
        if not message.guild:
            return

        # Check if message starts with any of our prefixes
        content = message.content
        prefix_used = None
        for prefix in self.prefixes:
            if content.startswith(prefix):
                prefix_used = prefix
                break

        if not prefix_used:
            return

        # Extract sound name (everything after the prefix)
        sound_name = content[len(prefix_used) :].strip().lower()

        if not sound_name:
            return

        # Skip if it's a registered command
        registered_commands = [
            "add",
            "stop",
            "leave",
            "sounds",
            "help",
            "skip",
            "pause",
            "resume",
            "unpause",
            "queue",
            "q",
            "next",
            "playnext",
            "now",
            "playnow",
        ]
        if sound_name.split()[0] in registered_commands:
            return

        # Try to find and play the sound
        audio_path = sound_service.get_audio_path(sound_name)
        if not audio_path:
            # Try partial match
            matches = sound_service.search_sounds(sound_name)
            if len(matches) == 1:
                audio_path = sound_service.get_audio_path(matches[0][0])
                sound_name = matches[0][0]
            elif len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                await message.channel.send(
                    f"Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
                return
            else:
                # Not found, silently ignore (could be a command for another bot)
                return

        # Get the member object
        member = message.guild.get_member(message.author.id)

        # Get duration for display
        duration = sound_service.get_sound_duration(sound_name)

        # Play the sound
        success, result = await voice_service.play_sound(
            message.guild,
            audio_path,
            name=sound_name,
            user=member,
            duration=duration,
        )

        if success:
            # Update play count in state
            sound = sound_service.get_sound(sound_name)
            if sound:
                sound.discord.plays += 1
                sound.discord.last_played = datetime.now()
                state.save()

            await message.channel.send(f"🔊 {result}")
        else:
            await message.channel.send(f"❌ {result}")


class UserSettingsCog(commands.Cog):
    """Commands for user settings like entrance/exit sounds."""

    def __init__(self, bot: SoundBot):
        self.bot = bot

    @app_commands.command(name="entrance")
    @app_commands.describe(
        sound_name="Sound to play when you join voice (leave empty to see current)"
    )
    async def set_entrance(
        self,
        interaction: Interaction,
        sound_name: Optional[str] = None,
    ):
        """Set or view your entrance sound."""
        user_id = str(interaction.user.id)

        if sound_name is None:
            # Show current entrance sound
            current = state.entrances.get(user_id)
            if current:
                await interaction.response.send_message(
                    f"🚪 Your entrance sound is **{current}**"
                )
            else:
                await interaction.response.send_message(
                    "🚪 You don't have an entrance sound set. Use `/entrance <sound_name>` to set one."
                )
            return

        # Validate sound exists
        sound_name = sound_name.lower()
        if not sound_service.get_sound(sound_name):
            # Try partial match
            matches = sound_service.search_sounds(sound_name)
            if len(matches) == 1:
                sound_name = matches[0][0]
            elif len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
                return
            else:
                await interaction.response.send_message(
                    f"❌ Sound '{sound_name}' not found"
                )
                return

        state.entrances[user_id] = sound_name
        state.save()

        await interaction.response.send_message(
            f"✅ Set your entrance sound to **{sound_name}**"
        )

    @app_commands.command(name="exit")
    @app_commands.describe(
        sound_name="Sound to play when you leave voice (leave empty to see current)"
    )
    async def set_exit(
        self,
        interaction: Interaction,
        sound_name: Optional[str] = None,
    ):
        """Set or view your exit sound."""
        user_id = str(interaction.user.id)

        if sound_name is None:
            # Show current exit sound
            current = state.exits.get(user_id)
            if current:
                await interaction.response.send_message(
                    f"🚪 Your exit sound is **{current}**"
                )
            else:
                await interaction.response.send_message(
                    "🚪 You don't have an exit sound set. Use `/exit <sound_name>` to set one."
                )
            return

        # Validate sound exists
        sound_name = sound_name.lower()
        if not sound_service.get_sound(sound_name):
            # Try partial match
            matches = sound_service.search_sounds(sound_name)
            if len(matches) == 1:
                sound_name = matches[0][0]
            elif len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
                return
            else:
                await interaction.response.send_message(
                    f"❌ Sound '{sound_name}' not found"
                )
                return

        state.exits[user_id] = sound_name
        state.save()

        await interaction.response.send_message(
            f"✅ Set your exit sound to **{sound_name}**"
        )

    @app_commands.command(name="clearentrance")
    async def clear_entrance(self, interaction: Interaction):
        """Clear your entrance sound."""
        user_id = str(interaction.user.id)
        if user_id in state.entrances:
            del state.entrances[user_id]
            state.save()
            await interaction.response.send_message("✅ Cleared your entrance sound")
        else:
            await interaction.response.send_message(
                "ℹ️ You don't have an entrance sound set"
            )

    @app_commands.command(name="clearexit")
    async def clear_exit(self, interaction: Interaction):
        """Clear your exit sound."""
        user_id = str(interaction.user.id)
        if user_id in state.exits:
            del state.exits[user_id]
            state.save()
            await interaction.response.send_message("✅ Cleared your exit sound")
        else:
            await interaction.response.send_message(
                "ℹ️ You don't have an exit sound set"
            )


class VoiceEventsCog(commands.Cog):
    """Handle voice channel events for entrance/exit sounds."""

    def __init__(self, bot: SoundBot):
        self.bot = bot
        # Track recent plays to avoid spam
        self._recent_plays: dict[str, datetime] = {}
        self._cooldown_seconds = 5

    def _can_play(self, user_id: str) -> bool:
        """Check if enough time has passed since last entrance/exit sound."""
        last_play = self._recent_plays.get(user_id)
        if last_play is None:
            return True
        return (datetime.now() - last_play).total_seconds() >= self._cooldown_seconds

    def _mark_played(self, user_id: str) -> None:
        """Mark that we just played an entrance/exit sound for this user."""
        self._recent_plays[user_id] = datetime.now()

    async def _check_empty_channel(self, channel: discord.VoiceChannel) -> None:
        """Check if the bot should leave a voice channel due to no human members."""
        # Get the bot's voice client for this guild
        guild = channel.guild
        voice_client = guild.voice_client

        if not voice_client or voice_client.channel != channel:
            return

        # Check if there are any non-bot members in the channel
        human_members = [m for m in channel.members if not m.bot]
        if not human_members:
            logger.info(
                f"All users left voice channel {channel.name} in {guild.name}, disconnecting"
            )
            await voice_service.disconnect(guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Play entrance/exit sounds when users join/leave voice."""
        # Check if someone left a channel where the bot is - leave if no humans remain
        if before.channel and before.channel != after.channel:
            if isinstance(before.channel, discord.VoiceChannel):
                await self._check_empty_channel(before.channel)

        # Ignore bots for entrance/exit sounds
        if member.bot:
            return

        user_id = str(member.id)

        # Ignore if on cooldown
        if not self._can_play(user_id):
            return

        # Determine if this is a join, leave, or move
        joined_channel = after.channel if after.channel and not before.channel else None
        left_channel = before.channel if before.channel and not after.channel else None

        # Handle join
        if joined_channel:
            sound_name = state.entrances.get(user_id)
            if sound_name:
                audio_path = sound_service.get_audio_path(sound_name)
                if audio_path and audio_path.exists():
                    self._mark_played(user_id)
                    duration = sound_service.get_sound_duration(sound_name)
                    # Play in the channel they joined
                    voice_client = await voice_service.connect(joined_channel)
                    if voice_client:
                        await voice_service.queue_sound(
                            member.guild,
                            audio_path,
                            sound_name,
                            user=member,
                            duration=duration,
                        )
                        # Update play count
                        sound = sound_service.get_sound(sound_name)
                        if sound:
                            sound.discord.plays += 1
                            sound.discord.last_played = datetime.now()
                            state.save()

        # Handle leave
        elif left_channel:
            sound_name = state.exits.get(user_id)
            if sound_name:
                audio_path = sound_service.get_audio_path(sound_name)
                if audio_path and audio_path.exists():
                    self._mark_played(user_id)
                    duration = sound_service.get_sound_duration(sound_name)
                    # Play in the channel they left (if bot is there or others remain)
                    remaining_members = [m for m in left_channel.members if not m.bot]
                    if remaining_members:
                        voice_client = await voice_service.connect(left_channel)
                        if voice_client:
                            await voice_service.queue_sound(
                                member.guild,
                                audio_path,
                                sound_name,
                                user=member,
                                duration=duration,
                            )
                            # Update play count
                            sound = sound_service.get_sound(sound_name)
                            if sound:
                                sound.discord.plays += 1
                                sound.discord.last_played = datetime.now()
                                state.save()


# Create the bot instance
soundbot_client = SoundBot()
