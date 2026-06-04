import logging

import discord
from discord import app_commands
from discord.ext import commands

import leetbot.config as config

logger = logging.getLogger(__name__)


class FunCog(commands.Cog, name="FunCog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="linear", description="A very important command.")
    async def linear(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("😄")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if config.DERPSHRINES_USER_ID and message.author.id == config.DERPSHRINES_USER_ID:
            try:
                await message.add_reaction("🤓")
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog(bot))
