import asyncio
import logging
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, cast, override

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.core.utils import parse_timestamp
from soundbot.discord.cards import build_info_card, post_clip_and_card
from soundbot.models.sounds import RandomMode, Sound
from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.sounds import sound_service
from soundbot.services.voice import voice_service
from soundbot.services.ytdlp import ytdlp_service

logger = logging.getLogger(__name__)

# Upload validation for /add file uploads
AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".flac",
    ".aac",
    ".opus",
    ".webm",
    ".mp4",
    ".mkv",
}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB


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

    async def _clear_guild_commands(self):
        """Clear any stale guild-specific command registrations."""
        for guild in self.guilds:
            self.tree.clear_commands(guild=guild)
            _ = await self.tree.sync(guild=guild)
            logger.info(f"Cleared guild commands for {guild.id}")

    async def on_ready(self):
        assert self.user is not None  # Always set when on_ready is called
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")
        prefixes = settings.twitch_command_prefixes or ["!"]
        logger.info(f"Command prefixes: {prefixes}")

        # Clear stale guild-specific commands (from old test_guild_ids usage)
        if not self.test_guild_ids:
            await self._clear_guild_commands()

    @override
    async def setup_hook(self) -> None:
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
                _ = await self.tree.sync(guild=guild)
                logger.info(f"Synced commands to guild {guild_id}")
        else:
            _ = await self.tree.sync()
            logger.info("Synced commands globally")

    @override
    async def close(self) -> None:
        """Called when the bot is shutting down."""
        logger.info("Bot shutting down, disconnecting from all voice channels...")
        await voice_service.disconnect_all()
        await super().close()


class SoundCommands(commands.Cog):
    """Slash commands for sound management (CRUD)."""

    def __init__(self, bot: SoundBot):
        super().__init__()
        self.bot = bot

    @app_commands.command(name="add")
    @app_commands.describe(
        name="Name for the sound (used to play it)",
        url="URL to download from (YouTube, etc.)",
        file="Audio/video file to upload (instead of a URL)",
        start="Start time (e.g. '90' or '1:30')",
        end="End time (e.g. '120' or '2:00')",
        overwrite="Overwrite existing sound if it exists (default: False)",
    )
    async def add_sound(
        self,
        interaction: Interaction,
        name: str,
        url: Optional[str] = None,
        file: Optional[discord.Attachment] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        overwrite: bool = False,
    ):
        """Add a new sound from a URL or an uploaded file."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        # Exactly one source: url or file
        if (url is None) == (file is None):
            _ = await interaction.response.send_message(
                "❌ Provide exactly one of `url` or `file`.", ephemeral=True
            )
            return

        # Parse timestamps (supports both "90" and "1:30" formats)
        start_seconds = parse_timestamp(start) if start else None
        end_seconds = parse_timestamp(end) if end else None

        if start is not None and start_seconds is None:
            _ = await interaction.response.send_message(
                f"❌ Invalid start time: '{start}'. Use seconds (90) or MM:SS (1:30).",
                ephemeral=True,
            )
            return
        if end is not None and end_seconds is None:
            _ = await interaction.response.send_message(
                f"❌ Invalid end time: '{end}'. Use seconds (90) or MM:SS (1:30).",
                ephemeral=True,
            )
            return

        if file is not None:
            # Validate it looks like an audio/video file
            ext = Path(file.filename).suffix.lower()
            if ext not in AUDIO_EXTENSIONS:
                _ = await interaction.response.send_message(
                    f"❌ File doesn't appear to be audio. Supported formats: {', '.join(sorted(AUDIO_EXTENSIONS))}",
                    ephemeral=True,
                )
                return
            if file.size > MAX_UPLOAD_BYTES:
                _ = await interaction.response.send_message(
                    "❌ File too large. Maximum size is 25MB.", ephemeral=True
                )
                return

        _ = await interaction.response.defer(thinking=True)

        if file is not None:
            logger.info(
                f"User {interaction.user} ({interaction.user.id}) adding sound '{name}' from uploaded file {file.filename}"
            )
            file_data = await file.read()
            result = await sound_service.add_sound_from_file(
                name=name,
                file_data=file_data,
                original_filename=file.filename,
                start=start_seconds,
                end=end_seconds,
                overwrite=overwrite,
                added_by=str(interaction.user),
            )
        else:
            assert url is not None  # Guaranteed by the exactly-one check above
            logger.info(
                f"User {interaction.user} ({interaction.user.id}) adding sound '{name}' from {url}"
            )
            result = await sound_service.add_sound(
                name=name,
                url=url,
                start=start_seconds,
                end=end_seconds,
                overwrite=overwrite,
            )

        emoji = "✅" if result.success else "❌"
        _ = await interaction.followup.send(f"{emoji} {result.full_message()}")

    @app_commands.command(name="delete")
    @app_commands.describe(name="Name of the sound to delete")
    async def delete_sound(self, interaction: Interaction, name: str):
        """Delete a sound."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        result = await sound_service.delete_sound(name)
        emoji = "✅" if result.success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @app_commands.command(name="redownload")
    @app_commands.describe(name="Name of the sound to re-download")
    async def redownload_sound(self, interaction: Interaction, name: str):
        """Re-download a sound from its original source URL."""
        _ = await interaction.response.defer(thinking=True)

        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        result = await sound_service.redownload_sound(name)

        emoji = "✅" if result.success else "❌"
        _ = await interaction.followup.send(f"{emoji} {result.full_message()}")

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
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @app_commands.command(name="trim")
    @app_commands.describe(
        name="Name of the sound",
        start="New start time (e.g. '90' or '1:30')",
        end="New end time (e.g. '120' or '2:00')",
    )
    async def trim_sound(
        self,
        interaction: Interaction,
        name: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ):
        """Set new start/end times for a sound."""
        _ = await interaction.response.defer(thinking=True)

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        # Parse timestamps (supports both "90" and "1:30" formats)
        start_seconds = parse_timestamp(start) if start else None
        end_seconds = parse_timestamp(end) if end else None

        if start is not None and start_seconds is None:
            _ = await interaction.followup.send(
                f"❌ Invalid start time format: '{start}'. Use seconds (90) or MM:SS (1:30)."
            )
            return
        if end is not None and end_seconds is None:
            _ = await interaction.followup.send(
                f"❌ Invalid end time format: '{end}'. Use seconds (90) or MM:SS (1:30)."
            )
            return

        result = await sound_service.edit_timestamps(
            name=name,
            start=start_seconds,
            end=end_seconds,
        )

        emoji = "✅" if result.success else "❌"
        _ = await interaction.followup.send(f"{emoji} {result.full_message()}")

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
        _ = await interaction.response.defer(thinking=True)

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        result = await sound_service.edit_timestamps(
            name=name,
            adjust_start=start_offset,
            adjust_end=end_offset,
        )

        emoji = "✅" if result.success else "❌"
        _ = await interaction.followup.send(f"{emoji} {result.full_message()}")

    @app_commands.command(name="volume")
    @app_commands.describe(
        name="Name of the sound",
        adjustment="Direction: 'down', 'up', or 'reset'",
        amount="Number of notches to adjust (default: 1)",
    )
    @app_commands.choices(
        adjustment=[
            app_commands.Choice(name="down (quieter)", value="down"),
            app_commands.Choice(name="up (louder)", value="up"),
            app_commands.Choice(name="reset (normal)", value="reset"),
        ]
    )
    async def volume_sound(
        self,
        interaction: Interaction,
        name: str,
        adjustment: str,
        amount: int = 1,
    ):
        """Adjust volume for a sound. Each notch is a noticeable change."""
        _ = await interaction.response.defer(thinking=True)

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        # Get current sound to calculate new volume
        sound = sound_service.get_sound(name)
        if not sound:
            _ = await interaction.followup.send(f"❌ Sound '{name}' not found")
            return

        # Calculate new volume_adjust
        if adjustment == "reset":
            new_volume = 0
        elif adjustment == "down":
            new_volume = sound.volume_adjust - abs(amount)
        elif adjustment == "up":
            new_volume = sound.volume_adjust + abs(amount)
        else:
            _ = await interaction.followup.send(f"❌ Unknown adjustment: {adjustment}")
            return

        result = await sound_service.set_volume(name=name, volume_adjust=new_volume)

        emoji = "✅" if result.success else "❌"
        _ = await interaction.followup.send(f"{emoji} {result.full_message()}")

    @app_commands.command(name="clip")
    @app_commands.describe(name="Name of the sound")
    async def clip_sound(self, interaction: Interaction, name: str):
        """Post a video clip of a sound (plays inline in Discord)."""
        # Import here (like web/dependencies does for the bot) to keep the
        # web helpers out of the discord module import graph at import time.
        from soundbot.services.clips import (
            ClipError,
            ensure_clip,
            resolve_clip_source,
        )
        from soundbot.web.clipsign import build_clip_share_url

        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        resolved = sound_service.resolve_sound_name(name)
        if not resolved:
            _ = await interaction.response.send_message(
                f"❌ Sound '{name}' not found", ephemeral=True
            )
            return
        canonical_name, sound = resolved

        if not settings.session_secret:
            _ = await interaction.response.send_message(
                "❌ Clip links are not configured (SESSION_SECRET is unset)",
                ephemeral=True,
            )
            return

        # Quick pre-check (a stat + at most one probe) so the no-video case
        # can respond ephemerally — ephemerality is locked in at defer time.
        sound_dir = sound_service.sounds_dir / sound.directory
        if await resolve_clip_source(sound, sound_dir) is None:
            _ = await interaction.response.send_message(
                f"❌ Sound '{canonical_name}' has no video", ephemeral=True
            )
            return

        # A first-time transcode can exceed the 3-second interaction limit
        # (backfill may not have reached this sound yet) — defer + followup.
        _ = await interaction.response.defer(thinking=True)

        try:
            result = await ensure_clip(sound, sound_service.sounds_dir)
        except ClipError as e:
            logger.error(f"/clip generation failed for '{canonical_name}': {e}")
            _ = await interaction.followup.send(
                f"❌ Failed to generate a clip for '{canonical_name}'"
            )
            return

        if result is None:
            _ = await interaction.followup.send(
                f"❌ Sound '{canonical_name}' has no video"
            )
            return

        # A bare direct .mp4 link as message content is what makes Discord
        # render the native inline video player — no embed object.
        url = build_clip_share_url(canonical_name)
        _ = await interaction.followup.send(url)

    @app_commands.command(name="info")
    @app_commands.describe(name="Name of the sound or group")
    async def sound_info(self, interaction: Interaction, name: str):
        """Get information about a sound or group."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)

        # If it's a group, show group info
        group_members = sound_service.resolve_group(name)
        if group_members is not None:
            embed = discord.Embed(
                title=f"🎲 Group: {name}",
                description=", ".join(group_members) if group_members else "(empty)",
                color=discord.Color.purple(),
            )
            _ = embed.add_field(name="Members", value=str(len(group_members)), inline=True)
            _ = await interaction.response.send_message(embed=embed)
            return

        sound = sound_service.get_sound(name)
        if not sound:
            _ = await interaction.response.send_message(
                f"❌ Sound or group '{name}' not found"
            )
            return

        metadata = sound_service.read_metadata(sound)
        embed = build_info_card(name, sound, metadata)

        _ = await interaction.response.send_message(embed=embed)

    @app_commands.command(name="sounds")
    async def sounds(self, interaction: Interaction):
        """Browse sounds on the web UI."""
        # Direct to web UI
        embed = discord.Embed(
            title="🔊 Browse Sounds",
            description="Visit the web interface to browse, search, and preview all sounds:",
            color=discord.Color.blue(),
            url=f"https://{settings.web_ui_url}",
        )
        _ = embed.add_field(
            name="Web UI",
            value=f"[{settings.web_ui_url}](https://{settings.web_ui_url})",
            inline=False,
        )
        _ = embed.add_field(
            name="Tip",
            value="Use `/search <query>` to search from Discord or `/list` to see all sounds",
            inline=False,
        )
        _ = await interaction.response.send_message(embed=embed)

    @app_commands.command(name="search")
    @app_commands.describe(query="Search term")
    async def search_sounds(
        self,
        interaction: Interaction,
        query: str,
    ):
        """Search for sounds."""
        query = strip_command_prefix(query)
        results = sound_service.search_sounds(query)
        if not results:
            _ = await interaction.response.send_message(
                f"❌ No sounds matching '{query}'"
            )
            return

        names = [name for name, _ in results]

        # Paginate if too many
        chunks = [names[i : i + 50] for i in range(0, len(names), 50)]

        embed = discord.Embed(
            title=f"🔊 Sounds matching '{query}' ({len(names)} total)",
            description=", ".join(chunks[0]),
            color=discord.Color.blue(),
        )

        if len(chunks) > 1:
            _ = embed.set_footer(text=f"Showing first 50 of {len(names)}")

        _ = await interaction.response.send_message(embed=embed)

    @app_commands.command(name="list")
    async def list_sounds(self, interaction: Interaction):
        """List all sounds (may send multiple messages)."""
        names = sorted(sound_service.list_sounds().keys())
        if not names:
            _ = await interaction.response.send_message(
                "No sounds yet! Use /add to add some."
            )
            return

        # Split into chunks of 50 sounds per message
        chunks = [names[i : i + 50] for i in range(0, len(names), 50)]

        # Send first chunk as response
        embed = discord.Embed(
            title=f"🔊 All Sounds ({len(names)} total)",
            description=", ".join(chunks[0]),
            color=discord.Color.blue(),
        )

        if len(chunks) > 1:
            _ = embed.set_footer(text=f"Page 1 of {len(chunks)}")

        _ = await interaction.response.send_message(embed=embed)

        # Send remaining chunks as follow-up messages
        for i, chunk in enumerate(chunks[1:], start=2):
            embed = discord.Embed(
                title="🔊 All Sounds (continued)",
                description=", ".join(chunk),
                color=discord.Color.blue(),
            )
            _ = embed.set_footer(text=f"Page {i} of {len(chunks)}")
            _ = await interaction.followup.send(embed=embed)

    alias_group = app_commands.Group(name="alias", description="Manage sound aliases")

    @alias_group.command(name="add")
    @app_commands.describe(sound="Name of the sound", alias="Alias to add")
    async def alias_add(self, interaction: Interaction, sound: str, alias: str):
        """Add an alias for a sound."""
        sound = strip_command_prefix(sound)
        alias = strip_command_prefix(alias)
        result = sound_service.add_alias(sound, alias)
        emoji = "✅" if result.success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @alias_group.command(name="remove")
    @app_commands.describe(sound="Name of the sound", alias="Alias to remove")
    async def alias_remove(self, interaction: Interaction, sound: str, alias: str):
        """Remove an alias from a sound."""
        sound = strip_command_prefix(sound)
        alias = strip_command_prefix(alias)
        result = sound_service.remove_alias(sound, alias)
        emoji = "✅" if result.success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @alias_group.command(name="list")
    @app_commands.describe(sound="Name of the sound")
    async def alias_list(self, interaction: Interaction, sound: str):
        """List aliases for a sound."""
        sound = strip_command_prefix(sound)
        resolved = sound_service.resolve_sound_name(sound)
        if not resolved:
            _ = await interaction.response.send_message(f"❌ Sound '{sound}' not found")
            return
        canonical_name, sound_obj = resolved
        if not sound_obj.aliases:
            _ = await interaction.response.send_message(
                f"🔊 '{canonical_name}' has no aliases"
            )
        else:
            aliases = ", ".join(sound_obj.aliases)
            _ = await interaction.response.send_message(
                f"🔊 '{canonical_name}' aliases: {aliases}"
            )

    group_cmd = app_commands.Group(name="group", description="Manage sound groups")

    @group_cmd.command(name="create")
    @app_commands.describe(name="Name for the group")
    async def group_create(self, interaction: Interaction, name: str):
        """Create a new sound group."""
        name = strip_command_prefix(name)
        result = sound_service.create_group(name)
        emoji = "✅" if result.success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @group_cmd.command(name="delete")
    @app_commands.describe(name="Name of the group")
    async def group_delete(self, interaction: Interaction, name: str):
        """Delete a sound group."""
        name = strip_command_prefix(name)
        result = sound_service.delete_group(name)
        emoji = "✅" if result.success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @group_cmd.command(name="add")
    @app_commands.describe(group="Name of the group", sound="Sound to add")
    async def group_add(self, interaction: Interaction, group: str, sound: str):
        """Add a sound to a group."""
        group = strip_command_prefix(group)
        sound = strip_command_prefix(sound)
        result = sound_service.add_to_group(group, sound)
        emoji = "✅" if result.success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @group_cmd.command(name="remove")
    @app_commands.describe(group="Name of the group", sound="Sound to remove")
    async def group_remove(self, interaction: Interaction, group: str, sound: str):
        """Remove a sound from a group."""
        group = strip_command_prefix(group)
        sound = strip_command_prefix(sound)
        result = sound_service.remove_from_group(group, sound)
        emoji = "✅" if result.success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @group_cmd.command(name="random")
    @app_commands.describe(
        name="Name of the group",
        mode="How members enter /random",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(
                name="together (default: one slot for the whole group)",
                value="together",
            ),
            app_commands.Choice(
                name="separate (each member competes individually)",
                value="separate",
            ),
        ]
    )
    async def group_random(
        self,
        interaction: Interaction,
        name: str,
        mode: app_commands.Choice[str],
    ):
        """Set how a group's members enter /random."""
        name = strip_command_prefix(name)
        # discord.py guarantees mode.value matches one of our Choice values
        result = sound_service.set_group_random_mode(
            name, cast(RandomMode, mode.value)
        )
        emoji = "✅" if result.success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {result.message}")

    @group_cmd.command(name="list")
    @app_commands.describe(name="Group name (omit to list all groups)")
    async def group_list(self, interaction: Interaction, name: Optional[str] = None):
        """List all groups or members of a specific group."""
        if name:
            name = strip_command_prefix(name)
            members = sound_service.resolve_group(name)
            if members is None:
                _ = await interaction.response.send_message(f"❌ Group '{name}' not found")
            elif not members:
                _ = await interaction.response.send_message(
                    f"🎲 Group '{name}' is empty"
                )
            else:
                _ = await interaction.response.send_message(
                    f"🎲 Group '{name}': {', '.join(members)}"
                )
        else:
            groups = sound_service.list_groups()
            if not groups:
                _ = await interaction.response.send_message("No groups yet")
            else:
                lines = [f"**{name}** ({len(group.members)})" for name, group in groups.items()]
                _ = await interaction.response.send_message(
                    f"🎲 Groups: {', '.join(lines)}"
                )

    @app_commands.command(name="random")
    @app_commands.describe(group="Optional group to pick from")
    async def random_sound(
        self, interaction: Interaction, group: Optional[str] = None
    ):
        """Play a random sound (max 2 minutes).

        Without a group, treats each random_mode="together" group as one slot (so a
        group of 100 taunts doesn't dominate). With a group, picks a random
        eligible member of that group.
        """
        MAX_DURATION = 120.0

        def is_eligible(name: str) -> bool:
            sound = sound_service.get_sound(name)
            if not sound:
                return False
            duration = None
            if sound.timestamps.start is not None or sound.timestamps.end is not None:
                start = sound.timestamps.start or 0
                end = sound.timestamps.end or sound.source_duration
                if end:
                    duration = end - start
            elif sound.source_duration:
                duration = sound.source_duration
            return duration is None or duration <= MAX_DURATION

        # If a group is specified, pick from just that group
        if group is not None:
            group = strip_command_prefix(group)
            members = sound_service.resolve_group(group)
            if members is None:
                _ = await interaction.response.send_message(
                    f"❌ Group '{group}' not found"
                )
                return
            eligible_members = [n for n in members if is_eligible(n)]
            if not eligible_members:
                _ = await interaction.response.send_message(
                    f"❌ No sounds under 2 minutes in group '{group}'"
                )
                return
            name = random.choice(eligible_members)
        else:
            all_sounds = sound_service.list_sounds()
            if not all_sounds:
                _ = await interaction.response.send_message("❌ No sounds available")
                return

            # Members of random_mode="together" groups are excluded from the
            # individual pool — they're represented by the group's single slot.
            group_owned: set[str] = set()
            together_groups: list[tuple[str, list[str]]] = []
            for group_name, group_data in sound_service.list_groups().items():
                if group_data.random_mode != "together":
                    continue
                eligible_members = [n for n in group_data.members if is_eligible(n)]
                if not eligible_members:
                    # Empty groups (or all-too-long) get no slot. Still mark
                    # members as owned so they don't appear in the individual
                    # pool — otherwise switching to random_mode="together" on a
                    # group with only long sounds wouldn't change /random.
                    group_owned.update(group_data.members)
                    continue
                together_groups.append((group_name, eligible_members))
                group_owned.update(group_data.members)

            individual_eligible = [
                n for n in all_sounds if n not in group_owned and is_eligible(n)
            ]

            # Total candidate slots: individuals + one per together-group
            if not individual_eligible and not together_groups:
                _ = await interaction.response.send_message(
                    "❌ No sounds under 2 minutes available"
                )
                return

            slot_index = random.randrange(
                len(individual_eligible) + len(together_groups)
            )
            if slot_index < len(individual_eligible):
                name = individual_eligible[slot_index]
            else:
                _, group_members = together_groups[
                    slot_index - len(individual_eligible)
                ]
                name = random.choice(group_members)

        audio_path = sound_service.get_audio_path(name)
        if not audio_path:
            _ = await interaction.response.send_message(f"❌ Sound '{name}' not found")
            return

        # Get duration for display
        duration = sound_service.get_sound_duration(name)

        # Clip transcode in post_clip_and_card can exceed the 3s interaction
        # window — defer + followup (same reason as /clip).
        _ = await interaction.response.defer(thinking=True)

        # Play it
        assert interaction.guild is not None  # Commands only work in guilds
        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild
            else None
        )
        success, message = await voice_service.play_sound(
            interaction.guild, audio_path, name=name, user=member, duration=duration
        )

        if not success:
            _ = await interaction.followup.send(f"❌ {message}")
            return

        sound = sound_service.get_sound(name)
        if sound:
            sound.discord.plays += 1
            sound.discord.last_played = datetime.now()
            _ = state.save()
            await post_clip_and_card(
                interaction.followup.send, name, sound, status_text=f"🎲 {message}"
            )
        else:
            _ = await interaction.followup.send(f"🎲 {message}")

    @app_commands.command(name="play")
    @app_commands.describe(name="Name of the sound or group")
    async def play_sound(self, interaction: Interaction, name: str):
        """Play a sound (or queue it if something is playing). Accepts a group name (random member)."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        resolved = sound_service.resolve_playable(name)
        if not resolved:
            matches = sound_service.search_sounds(name)
            if len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                _ = await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
            else:
                _ = await interaction.response.send_message(
                    f"❌ Sound or group '{name}' not found"
                )
            return
        name, audio_path = resolved

        # Clip transcode in post_clip_and_card can exceed the 3s interaction
        # window — defer + followup (same reason as /clip).
        _ = await interaction.response.defer(thinking=True)

        assert interaction.guild is not None  # Commands only work in guilds
        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild
            else None
        )
        duration = sound_service.get_sound_duration(name)
        success, message = await voice_service.play_sound(
            interaction.guild,
            audio_path,
            name=name,
            user=member,
            duration=duration,
        )

        if not success:
            _ = await interaction.followup.send(f"❌ {message}")
            return

        sound = sound_service.get_sound(name)
        if sound:
            sound.discord.plays += 1
            sound.discord.last_played = datetime.now()
            _ = state.save()
            await post_clip_and_card(
                interaction.followup.send, name, sound, status_text=f"🔊 {message}"
            )
        else:
            _ = await interaction.followup.send(f"🔊 {message}")

    @app_commands.command(name="playurl")
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
        _ = await interaction.response.defer(thinking=True)

        # Download to temp directory
        download_result = await ytdlp_service.download_temp(url)
        if not download_result.success:
            _ = await interaction.followup.send(
                f"❌ Download failed: {download_result.error}"
            )
            return

        # Get temp directory for cleanup
        assert download_result.original_file is not None  # Set when success is True
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
            _ = await interaction.followup.send(
                f"❌ Audio processing failed: {audio_result.error}"
            )
            # Clean up temp directory on failure
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            return

        # Play it
        assert interaction.guild is not None  # Commands only work in guilds
        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild
            else None
        )
        title = download_result.title or "Quick play"

        # Compute playback duration from the source duration and trim window,
        # falling back to probing the output if metadata is missing.
        duration: Optional[float] = None
        if download_result.duration is not None:
            trim_start = start or 0.0
            trim_end = end if end is not None else download_result.duration
            duration = max(0.0, trim_end - trim_start)
        if duration is None:
            probe = await ffmpeg_service.probe(temp_audio)
            if probe is not None:
                duration = probe.duration

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
            _ = await interaction.followup.send(msg)

            # Schedule cleanup after playback (give it time to start playing)
            async def cleanup_temp_dir():
                # Wait for sound to finish playing (approximate based on duration)
                wait_time = duration if duration else 60
                await asyncio.sleep(wait_time + 5)  # Add 5 second buffer
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")

            _ = asyncio.create_task(cleanup_temp_dir())
        else:
            _ = await interaction.followup.send(f"❌ {message}")
            # Clean up temp directory on failure
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


class QueueCog(commands.Cog):
    """Commands for queue management."""

    def __init__(self, bot: SoundBot):
        super().__init__()
        self.bot = bot

    @app_commands.command(name="playnext")
    @app_commands.describe(name="Name of the sound or group")
    async def play_next_slash(self, interaction: Interaction, name: str):
        """Add a sound to play next in the queue. Accepts a group name (random member)."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        resolved = sound_service.resolve_playable(name)
        if not resolved:
            matches = sound_service.search_sounds(name)
            if len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                _ = await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
            else:
                _ = await interaction.response.send_message(
                    f"❌ Sound or group '{name}' not found"
                )
            return
        name, audio_path = resolved

        # Clip transcode in post_clip_and_card can exceed the 3s interaction
        # window — defer + followup (same reason as /clip).
        _ = await interaction.response.defer(thinking=True)

        assert interaction.guild is not None  # Commands only work in guilds
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

        if not success:
            _ = await interaction.followup.send(f"❌ {message}")
            return

        sound = sound_service.get_sound(name)
        if sound:
            sound.discord.plays += 1
            sound.discord.last_played = datetime.now()
            _ = state.save()
            await post_clip_and_card(
                interaction.followup.send, name, sound, status_text=f"⏭️ {message}"
            )
        else:
            _ = await interaction.followup.send(f"⏭️ {message}")

    @app_commands.command(name="playnow")
    @app_commands.describe(name="Name of the sound or group")
    async def play_now_slash(self, interaction: Interaction, name: str):
        """Play a sound immediately, pausing the current sound. Accepts a group name (random member)."""
        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        resolved = sound_service.resolve_playable(name)
        if not resolved:
            matches = sound_service.search_sounds(name)
            if len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                _ = await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
            else:
                _ = await interaction.response.send_message(
                    f"❌ Sound or group '{name}' not found"
                )
            return
        name, audio_path = resolved

        # Clip transcode in post_clip_and_card can exceed the 3s interaction
        # window — defer + followup (same reason as /clip).
        _ = await interaction.response.defer(thinking=True)

        assert interaction.guild is not None  # Commands only work in guilds
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

        if not success:
            _ = await interaction.followup.send(f"❌ {message}")
            return

        sound = sound_service.get_sound(name)
        if sound:
            sound.discord.plays += 1
            sound.discord.last_played = datetime.now()
            _ = state.save()
            await post_clip_and_card(
                interaction.followup.send, name, sound, status_text=f"🎵 {message}"
            )
        else:
            _ = await interaction.followup.send(f"🎵 {message}")

    @app_commands.command(name="queue")
    async def show_queue(self, interaction: Interaction):
        """Show the current playback queue."""
        if not interaction.guild:
            _ = await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        current = voice_service.get_current(interaction.guild.id)
        queue = voice_service.get_queue(interaction.guild.id)
        is_paused = voice_service.is_paused(interaction.guild.id)

        if not current and not queue:
            _ = await interaction.response.send_message("📭 Queue is empty")
            return

        embed = discord.Embed(title="🎵 Playback Queue", color=discord.Color.blue())

        # Current playing
        if current:
            status = "⏸️ Paused" if is_paused else "▶️ Now Playing"
            _ = embed.add_field(
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
            _ = embed.add_field(name="Up Next", value=queue_text, inline=False)
        else:
            _ = embed.add_field(name="Up Next", value="Nothing queued", inline=False)

        _ = await interaction.response.send_message(embed=embed)

    @app_commands.command(name="skip")
    async def skip_sound(self, interaction: Interaction):
        """Skip the current sound."""
        if not interaction.guild:
            _ = await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        success, message = await voice_service.skip(interaction.guild.id)
        emoji = "⏭️" if success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="stop")
    async def stop_playback(self, interaction: Interaction):
        """Stop playback and clear the queue."""
        if not interaction.guild:
            _ = await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        success, message = await voice_service.stop(interaction.guild.id)
        emoji = "⏹️" if success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="loop")
    @app_commands.describe(name="Name of the sound or group to loop")
    async def loop_sound(self, interaction: Interaction, name: str):
        """Loop a sound until stopped. Accepts a group name (picks a random member)."""
        if not interaction.guild:
            _ = await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        # Strip any command prefix from the name
        name = strip_command_prefix(name)
        resolved = sound_service.resolve_playable(name)
        if not resolved:
            _ = await interaction.response.send_message(
                f"❌ Sound or group '{name}' not found"
            )
            return
        name, audio_path = resolved

        # Get duration for display
        duration = sound_service.get_sound_duration(name)

        # Clip transcode in post_clip_and_card can exceed the 3s interaction
        # window — defer + followup (same reason as /clip).
        _ = await interaction.response.defer(thinking=True)

        # Get member for channel detection
        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild
            else None
        )

        success, message = await voice_service.loop_sound(
            interaction.guild, audio_path, name=name, user=member, duration=duration
        )

        if not success:
            _ = await interaction.followup.send(f"❌ {message}")
            return

        # Post clip + card once at loop start (not per iteration); count the
        # loop as a single play.
        sound = sound_service.get_sound(name)
        if sound:
            sound.discord.plays += 1
            sound.discord.last_played = datetime.now()
            _ = state.save()
            await post_clip_and_card(
                interaction.followup.send, name, sound, status_text=f"🔁 {message}"
            )
        else:
            _ = await interaction.followup.send(f"🔁 {message}")

    @app_commands.command(name="pause")
    async def pause_playback(self, interaction: Interaction):
        """Pause playback."""
        if not interaction.guild:
            _ = await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        success, message = await voice_service.pause(interaction.guild.id)
        emoji = "⏸️" if success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="resume")
    async def resume_playback(self, interaction: Interaction):
        """Resume playback."""
        if not interaction.guild:
            _ = await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        success, message = await voice_service.resume(interaction.guild.id)
        emoji = "▶️" if success else "❌"
        _ = await interaction.response.send_message(f"{emoji} {message}")

    @app_commands.command(name="leave")
    async def leave_channel(self, interaction: Interaction):
        """Leave the voice channel."""
        if not interaction.guild:
            _ = await interaction.response.send_message(
                "❌ This command must be used in a server"
            )
            return

        await voice_service.disconnect(interaction.guild.id)
        _ = await interaction.response.send_message("👋 Left voice channel")


class PlaybackCog(commands.Cog):
    """The !soundname play listener (the only prefix-command surface).

    Everything else is a slash command — the old text commands (!add, !stop,
    !skip, !queue, ...) were removed in favor of their slash equivalents.
    """

    def __init__(self, bot: SoundBot):
        super().__init__()
        self.bot = bot
        # Get all configured prefixes
        self.prefixes = settings.twitch_command_prefixes or ["!"]

    def _parse_sound_commands(self, content: str) -> list[str]:
        """Parse multiple sound commands from a message.

        Supports messages like "!sound1 !sound2 !sound3" returning ["sound1", "sound2", "sound3"].
        Also supports single commands like "!sound1" returning ["sound1"].
        """
        import re

        # Build regex pattern to split on any prefix
        # Escape special regex characters in prefixes
        escaped_prefixes = [re.escape(p) for p in self.prefixes]
        pattern = f"({'|'.join(escaped_prefixes)})"

        # Split by prefixes, keeping delimiters
        parts = re.split(pattern, content)

        commands = []
        i = 0
        while i < len(parts):
            part = parts[i]
            # Check if this part is a prefix
            if part in self.prefixes:
                # Next part (if exists) is the command
                if i + 1 < len(parts):
                    cmd = parts[i + 1].strip().lower()
                    # Only take the first word (sound name)
                    if cmd:
                        cmd_word = cmd.split()[0]
                        if cmd_word:
                            commands.append(cmd_word)
                    i += 2
                else:
                    i += 1
            else:
                i += 1

        return commands

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for prefix+soundname commands to play sounds."""
        if message.author.bot:
            return
        if not message.guild:
            return

        # Check if message starts with any of our prefixes
        content = message.content
        has_prefix = any(content.startswith(prefix) for prefix in self.prefixes)

        if not has_prefix:
            return

        # Parse all sound commands from the message
        sound_names = self._parse_sound_commands(content)

        if not sound_names:
            return

        # Get the member object
        member = message.guild.get_member(message.author.id)

        # Track results for response
        played_sounds: list[tuple[str, Sound]] = []
        errors: list[str] = []

        for sound_name in sound_names:
            # Try to find the sound
            audio_path = sound_service.get_audio_path(sound_name)
            resolved_name = sound_name

            if not audio_path:
                # Try group (random member)
                group_result = sound_service.resolve_group_random(sound_name)
                if group_result:
                    resolved_name = group_result[0]
                    audio_path = sound_service.get_audio_path(resolved_name)

            if not audio_path:
                # Try partial match
                matches = sound_service.search_sounds(sound_name)
                if len(matches) == 1:
                    audio_path = sound_service.get_audio_path(matches[0][0])
                    resolved_name = matches[0][0]
                elif len(matches) > 1:
                    names = [n for n, _ in matches[:5]]
                    errors.append(
                        f"'{sound_name}': multiple matches ({', '.join(names)})"
                    )
                    continue
                else:
                    # Not found, silently ignore (could be a command for another bot)
                    continue

            # Audio path must be set at this point
            assert audio_path is not None  # Checked above with continue statements

            # Get duration for display
            duration = sound_service.get_sound_duration(resolved_name)

            # For the first sound, use play_sound (plays immediately or queues)
            # For subsequent sounds, use queue_sound to add to queue
            if not played_sounds:
                success, result = await voice_service.play_sound(
                    message.guild,
                    audio_path,
                    name=resolved_name,
                    user=member,
                    duration=duration,
                )
            else:
                success, result = await voice_service.queue_sound(
                    message.guild,
                    audio_path,
                    resolved_name,
                    user=member,
                    duration=duration,
                )

            if success:
                # Update play count in state
                sound = sound_service.get_sound(resolved_name)
                if sound:
                    sound.discord.plays += 1
                    sound.discord.last_played = datetime.now()
                    played_sounds.append((resolved_name, sound))
            else:
                errors.append(f"'{resolved_name}': {result}")

        # Save state if we played any sounds
        if played_sounds:
            _ = state.save()

        # Post clip + info card for each played sound (clip rides alone so
        # Discord auto-embeds the inline video player; card follows).
        for played_name, played_sound in played_sounds:
            await post_clip_and_card(message.channel.send, played_name, played_sound)

        if errors:
            _ = await message.channel.send(f"❌ Errors: {'; '.join(errors)}")


class UserSettingsCog(commands.Cog):
    """Commands for user settings like entrance/exit sounds."""

    def __init__(self, bot: SoundBot):
        super().__init__()
        self.bot = bot

    @app_commands.command(name="entrance")
    @app_commands.describe(
        sound_name="Sound or group to play when you join voice (leave empty to see current)"
    )
    async def set_entrance(
        self,
        interaction: Interaction,
        sound_name: Optional[str] = None,
    ):
        """Set or view your entrance sound. Accepts a group name (picks a random member each time)."""
        user_id = str(interaction.user.id)

        if sound_name is None:
            # Show current entrance sound
            current = state.entrances.get(user_id)
            if current:
                _ = await interaction.response.send_message(
                    f"🚪 Your entrance sound is **{current}**"
                )
            else:
                _ = await interaction.response.send_message(
                    "🚪 You don't have an entrance sound set. Use `/entrance <sound_name>` to set one."
                )
            return

        # Validate sound or group exists
        sound_name = strip_command_prefix(sound_name).lower()
        if sound_name in state.groups:
            pass
        elif sound_service.get_sound(sound_name):
            pass
        else:
            matches = sound_service.search_sounds(sound_name)
            if len(matches) == 1:
                sound_name = matches[0][0]
            elif len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                _ = await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
                return
            else:
                _ = await interaction.response.send_message(
                    f"❌ Sound or group '{sound_name}' not found"
                )
                return

        state.entrances[user_id] = sound_name
        _ = state.save()

        _ = await interaction.response.send_message(
            f"✅ Set your entrance sound to **{sound_name}**"
        )

    @app_commands.command(name="exit")
    @app_commands.describe(
        sound_name="Sound or group to play when you leave voice (leave empty to see current)"
    )
    async def set_exit(
        self,
        interaction: Interaction,
        sound_name: Optional[str] = None,
    ):
        """Set or view your exit sound. Accepts a group name (picks a random member each time)."""
        user_id = str(interaction.user.id)

        if sound_name is None:
            # Show current exit sound
            current = state.exits.get(user_id)
            if current:
                _ = await interaction.response.send_message(
                    f"🚪 Your exit sound is **{current}**"
                )
            else:
                _ = await interaction.response.send_message(
                    "🚪 You don't have an exit sound set. Use `/exit <sound_name>` to set one."
                )
            return

        # Validate sound or group exists
        sound_name = strip_command_prefix(sound_name).lower()
        if sound_name in state.groups:
            pass
        elif sound_service.get_sound(sound_name):
            pass
        else:
            matches = sound_service.search_sounds(sound_name)
            if len(matches) == 1:
                sound_name = matches[0][0]
            elif len(matches) > 1:
                names = [n for n, _ in matches[:5]]
                _ = await interaction.response.send_message(
                    f"❌ Multiple matches: {', '.join(names)}"
                    + (" ..." if len(matches) > 5 else "")
                )
                return
            else:
                _ = await interaction.response.send_message(
                    f"❌ Sound or group '{sound_name}' not found"
                )
                return

        state.exits[user_id] = sound_name
        _ = state.save()

        _ = await interaction.response.send_message(
            f"✅ Set your exit sound to **{sound_name}**"
        )

    @app_commands.command(name="clearentrance")
    async def clear_entrance(self, interaction: Interaction):
        """Clear your entrance sound."""
        user_id = str(interaction.user.id)
        if user_id in state.entrances:
            del state.entrances[user_id]
            _ = state.save()
            _ = await interaction.response.send_message(
                "✅ Cleared your entrance sound"
            )
        else:
            _ = await interaction.response.send_message(
                "ℹ️ You don't have an entrance sound set"
            )

    @app_commands.command(name="clearexit")
    async def clear_exit(self, interaction: Interaction):
        """Clear your exit sound."""
        user_id = str(interaction.user.id)
        if user_id in state.exits:
            del state.exits[user_id]
            _ = state.save()
            _ = await interaction.response.send_message("✅ Cleared your exit sound")
        else:
            _ = await interaction.response.send_message(
                "ℹ️ You don't have an exit sound set"
            )


class VoiceEventsCog(commands.Cog):
    """Handle voice channel events for entrance/exit sounds."""

    def __init__(self, bot: SoundBot):
        super().__init__()
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
            stored_name = state.entrances.get(user_id)
            if stored_name:
                # Resolve through the full lookup chain so groups pick a random member each time
                resolved = sound_service.resolve_playable(stored_name)
                if resolved:
                    resolved_name, audio_path = resolved
                    if audio_path.exists():
                        self._mark_played(user_id)
                        duration = sound_service.get_sound_duration(resolved_name)
                        # Play in the channel they joined
                        # VocalGuildChannel includes StageChannel, but connect only accepts VoiceChannel
                        assert isinstance(joined_channel, discord.VoiceChannel)
                        voice_client = await voice_service.connect(joined_channel)
                        if voice_client:
                            _ = await voice_service.queue_sound(
                                member.guild,
                                audio_path,
                                resolved_name,
                                user=member,
                                duration=duration,
                            )
                            # Update play count
                            sound = sound_service.get_sound(resolved_name)
                            if sound:
                                sound.discord.plays += 1
                                sound.discord.last_played = datetime.now()
                                _ = state.save()

        # Handle leave
        elif left_channel:
            stored_name = state.exits.get(user_id)
            if stored_name:
                resolved = sound_service.resolve_playable(stored_name)
                if resolved:
                    resolved_name, audio_path = resolved
                    if audio_path.exists():
                        self._mark_played(user_id)
                        duration = sound_service.get_sound_duration(resolved_name)
                        # Play in the channel they left (if bot is there or others remain)
                        remaining_members = [m for m in left_channel.members if not m.bot]
                        if remaining_members:
                            # VocalGuildChannel includes StageChannel, but connect only accepts VoiceChannel
                            assert isinstance(left_channel, discord.VoiceChannel)
                            voice_client = await voice_service.connect(left_channel)
                            if voice_client:
                                _ = await voice_service.queue_sound(
                                    member.guild,
                                    audio_path,
                                    resolved_name,
                                    user=member,
                                    duration=duration,
                                )
                                # Update play count
                                sound = sound_service.get_sound(resolved_name)
                                if sound:
                                    sound.discord.plays += 1
                                    sound.discord.last_played = datetime.now()
                                    _ = state.save()


# Create the bot instance
soundbot_client = SoundBot()
