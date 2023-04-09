from discord import app_commands, Interaction
from app.discord.client import client
from app.core.settings import settings


@client.tree.command(
    guilds=client.test_guilds,
)
async def play(interaction: Interaction, name: str):
    """Plays a sound"""
    await interaction.response.send_message('maybe later')


@client.tree.command(
    guilds=client.test_guilds,
)
@app_commands.describe(
    name='The first value you want to add something to',
    url='The value you want to add to the first value',
)
async def add(interaction: Interaction, name: str, url: str):
    """Adds a sound"""
    await interaction.response.send_message('maybe later')