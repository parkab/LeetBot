import asyncio
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import leetbot.config as config
import leetbot.db as db
from leetbot.utils.time import today_key

logger = logging.getLogger(__name__)


def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != config.BOT_OWNER_ID:
            await interaction.response.send_message(
                "This command is owner-only.", ephemeral=True
            )
            return False
        return True

    return app_commands.check(predicate)


class AdminCog(commands.Cog, name="AdminCog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="reload", description="Reload all cogs (owner only).")
    @is_owner()
    async def reload(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        cog_names = [
            "leetbot.cogs.daily",
            "leetbot.cogs.practice",
            "leetbot.cogs.leaderboard",
            "leetbot.cogs.fun",
            "leetbot.cogs.admin",
        ]
        failed: list[str] = []
        for name in cog_names:
            try:
                await self.bot.reload_extension(name)
            except Exception as exc:
                logger.error("Failed to reload %s: %s", name, exc)
                failed.append(name)

        if failed:
            await interaction.followup.send(f"Reload failed for: {', '.join(failed)}", ephemeral=True)
        else:
            await interaction.followup.send("All cogs reloaded.", ephemeral=True)
        logger.info("Cogs reloaded by %s", interaction.user)

    @app_commands.command(name="forcedaily", description="Manually trigger today's daily post (owner only).")
    @is_owner()
    async def forcedaily(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        daily_cog = self.bot.cogs.get("DailyCog")
        if daily_cog is None:
            await interaction.followup.send("DailyCog not loaded.", ephemeral=True)
            return
        channel = self.bot.get_channel(config.DAILY_CHANNEL_ID)
        msg = await daily_cog._post_daily(channel, force=True)
        if msg:
            await interaction.followup.send(f"Posted: {msg.jump_url}", ephemeral=True)
        else:
            await interaction.followup.send("Post failed — check logs.", ephemeral=True)


    @app_commands.command(
        name="resetattempt",
        description="Delete a user's attempt for today so they can retry (owner only).",
    )
    @app_commands.describe(
        user="The user whose attempt to wipe (defaults to you)",
        practice="Also wipe their entire /grind75 + /paretoset history",
    )
    @is_owner()
    async def resetattempt(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        practice: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        target = user or interaction.user
        day = today_key()
        deleted = await asyncio.to_thread(db.delete_attempt, str(target.id), day)

        practice_deleted = 0
        if practice:
            practice_deleted = await asyncio.to_thread(
                db.delete_practice_attempts, str(target.id)
            )

        # Also clear any in-memory sessions so they can start again immediately
        sm = getattr(self.bot, "session_manager", None)
        if sm is not None:
            for session in sm.sessions_for_user(str(target.id)):
                sm.remove(session)

        parts = [
            f"Daily attempt on `{day}`: {'cleared' if deleted else 'none found'}."
        ]
        if practice:
            parts.append(f"Practice history: {practice_deleted} row(s) deleted.")
        parts.append("In-memory sessions cleared.")

        await interaction.followup.send(
            f"{target.mention} — " + " ".join(parts), ephemeral=True
        )
        logger.info(
            "Attempt reset for user %s on %s by %s (practice=%s)",
            target.id, day, interaction.user, practice,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
