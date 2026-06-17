import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

import leetbot.config as config
from leetbot.interview.gemini import rate_activity

logger = logging.getLogger(__name__)


class FunCog(commands.Cog, name="FunCog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="linear", description="A very important command.")
    async def linear(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("😄")

    @app_commands.command(name="rate", description="Tell mommy what you did today and she'll judge you.")
    @app_commands.describe(activity="What did you do?")
    async def rate(self, interaction: discord.Interaction, activity: str) -> None:
        await interaction.response.defer()
        response = await rate_activity(activity)
        embed = discord.Embed(description=response, color=0xFF69B4)
        embed.set_footer(text=f"📋 \"{activity[:100]}\"")
        await interaction.followup.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.author.id == config.BOT_OWNER_ID:
            return
        if random.randint(1, 100) == 1:
            try:
                await message.add_reaction("🤓")
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog(bot))
