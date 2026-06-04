import logging

import discord
from discord.ext import commands

import leetbot.config as config
from leetbot.interview.manager import SessionManager

logger = logging.getLogger(__name__)

_COGS = [
    "leetbot.cogs.daily",
    "leetbot.cogs.leaderboard",
    "leetbot.cogs.fun",
    "leetbot.cogs.admin",
]


class LeetBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # Required for on_message interview routing
        intents.messages = True
        # members intent is privileged and not required — leaderboard falls back to <@id>
        super().__init__(command_prefix="!", intents=intents)
        self.session_manager = SessionManager()

    async def setup_hook(self) -> None:
        for cog in _COGS:
            await self.load_extension(cog)
            logger.info("Loaded cog: %s", cog)

        # Register persistent views so button callbacks survive restarts
        from leetbot.cogs.daily import DailyView, HintView
        self.add_view(DailyView())
        self.add_view(HintView())

        # Sync slash commands guild-scoped (instant, no 1-hour global propagation)
        guild = discord.Object(id=config.DISCORD_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("Slash commands synced to guild %s", config.DISCORD_GUILD_ID)

    async def on_ready(self) -> None:
        assert self.user is not None
        logger.info("LeetBot ready — logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for /solve",
            )
        )
