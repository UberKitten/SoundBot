"""Export Discord channel message history to a JSON file."""

import asyncio
import json
import logging
from pathlib import Path

import discord

from soundbot.core.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Discord rate limits: ~5 requests per 5 seconds for message history
# Each request fetches 100 messages, so we delay after every batch
MESSAGES_PER_BATCH = 100
DELAY_BETWEEN_BATCHES = 1.1  # seconds - stay safely under rate limit


async def export_channel_history(
    channel_id: int,
    output_path: str,
    limit: int | None = None,
) -> None:
    """
    Export all messages from a Discord channel to a JSON file.

    Args:
        channel_id: The Discord channel ID to export from.
        output_path: Path to save the JSON file.
        limit: Maximum number of messages to fetch (None = all).
    """
    intents = discord.Intents.default()
    intents.message_content = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logger.info(f"Logged in as {client.user}")

        channel = client.get_channel(channel_id)
        if channel is None:
            logger.error(f"Channel {channel_id} not found. Make sure the bot has access.")
            await client.close()
            return

        if not isinstance(channel, discord.TextChannel):
            logger.error(f"Channel {channel_id} is not a text channel.")
            await client.close()
            return

        logger.info(f"Exporting messages from #{channel.name} in {channel.guild.name}")
        logger.info(f"Adding {DELAY_BETWEEN_BATCHES}s delay between batches to respect rate limits...")

        messages = []
        count = 0

        async for message in channel.history(limit=limit, oldest_first=True):
            count += 1

            # Proactive rate limiting: delay after each batch of 100 messages
            # Discord fetches 100 messages per API call, so this adds delay between calls
            if count % MESSAGES_PER_BATCH == 0:
                logger.info(f"Processed {count} messages...")
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)

            messages.append({
                "id": message.id,
                "author": {
                    "id": message.author.id,
                    "name": message.author.name,
                    "display_name": message.author.display_name,
                    "bot": message.author.bot,
                },
                "content": message.content,
                "created_at": message.created_at.isoformat(),
                "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            })

        # Save to file
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "channel_id": channel_id,
                    "channel_name": channel.name,
                    "guild_id": channel.guild.id,
                    "guild_name": channel.guild.name,
                    "total_messages": len(messages),
                    "messages": messages,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        logger.info(f"Exported {len(messages)} messages to {output_path}")
        await client.close()

    await client.start(settings.token)
