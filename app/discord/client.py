import logging
from typing import List

from app.core.settings import settings

import discord
from discord import Interaction, app_commands


class SoundBotClient(discord.Client):
    test_guilds: List[discord.Object] = []
    
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        for id in settings.test_guild_ids.split(','):
            self.test_guilds.append(discord.Object(id=id))

    async def on_ready(self):
        logging.debug(f'Logged on as {self.user}!')

    async def setup_hook(self):
        logging.debug('Syncing guild commands')
        for guild in self.test_guilds:
            await self.tree.sync(guild=guild)
    

intents = discord.Intents.none()
client = SoundBotClient(intents=intents)

@client.tree.command(
    guilds=client.test_guilds,
)
@app_commands.describe(
    name='Sound name'
)
async def play(interaction: Interaction, name: str):
    """Plays a sound"""
    await interaction.response.send_message('maybe later')

@client.tree.command(
    guilds=client.test_guilds,
)
@app_commands.describe(
    name='Sound name',
    url='URL to a sound - any site yt-dlp can support downloading from',
)
async def add(interaction: Interaction, name: str, url: str):
    """Adds a sound"""
    await interaction.response.send_message('maybe later')

app_commands.