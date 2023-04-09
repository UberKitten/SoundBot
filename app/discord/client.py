from typing import List
import discord

from discord import app_commands
import logging
from app.core.settings import settings

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
        for guild in self.test_guilds:
            await self.tree.sync(guild=guild)
    

intents = discord.Intents.none()
client = SoundBotClient(intents=intents)