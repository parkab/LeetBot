import asyncio
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import leetbot.db as db
from leetbot.utils.time import today_key

logger = logging.getLogger(__name__)

MEDALS = ["🥇", "🥈", "🥉"]


def _member_name(guild: Optional[discord.Guild], user_id: str) -> str:
    if guild:
        member = guild.get_member(int(user_id))
        if member:
            return member.display_name
    return f"<@{user_id}>"


class LeaderboardCog(commands.Cog, name="LeaderboardCog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    leaderboard_group = app_commands.Group(
        name="leaderboard", description="View daily or all-time leaderboards."
    )

    @leaderboard_group.command(name="daily", description="Top 10 solvers for today.")
    async def leaderboard_daily(self, interaction: discord.Interaction) -> None:
        day_key = today_key()
        rows = await asyncio.to_thread(db.get_daily_leaderboard, day_key)

        embed = discord.Embed(
            title=f"🏆 Daily Leaderboard — {day_key}",
            color=0xC9A84C,
        )
        if not rows:
            embed.description = "No completions yet today. Be the first!"
        else:
            lines: list[str] = []
            for i, row in enumerate(rows):
                medal = MEDALS[i] if i < 3 else f"**{i + 1}.**"
                name = _member_name(interaction.guild, row["user_id"])
                lines.append(f"{medal} {name} — **{row['points']} pts**")
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed)

    @leaderboard_group.command(name="alltime", description="All-time top 10 by total points.")
    async def leaderboard_alltime(self, interaction: discord.Interaction) -> None:
        rows = await asyncio.to_thread(db.get_alltime_leaderboard)

        embed = discord.Embed(title="🏆 All-Time Leaderboard", color=0xC9A84C)
        if not rows:
            embed.description = "No attempts recorded yet."
        else:
            lines: list[str] = []
            for i, row in enumerate(rows):
                medal = MEDALS[i] if i < 3 else f"**{i + 1}.**"
                name = _member_name(interaction.guild, row["user_id"])
                lines.append(
                    f"{medal} {name} — **{row['total_points']} pts** ({row['days_played']} days)"
                )
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed)

    @leaderboard_group.command(
        name="practice", description="Top 10 by points from /grind75 and /paretoset."
    )
    async def leaderboard_practice(self, interaction: discord.Interaction) -> None:
        rows = await asyncio.to_thread(db.get_practice_leaderboard)

        embed = discord.Embed(title="🎯 Practice Leaderboard", color=0xC9A84C)
        if not rows:
            embed.description = (
                "No practice problems completed yet. Try `/grind75` or `/paretoset`!"
            )
        else:
            lines: list[str] = []
            for i, row in enumerate(rows):
                medal = MEDALS[i] if i < 3 else f"**{i + 1}.**"
                name = _member_name(interaction.guild, row["user_id"])
                solved = row["problems_solved"]
                plural = "problem" if solved == 1 else "problems"
                lines.append(
                    f"{medal} {name} — **{row['total_points']} pts** ({solved} {plural})"
                )
            embed.description = "\n".join(lines)
        embed.set_footer(text="Personal best per problem — repeats only count if you improve.")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stats", description="View your or another user's stats.")
    @app_commands.describe(user="User to look up (defaults to you).")
    async def stats(
        self, interaction: discord.Interaction, user: Optional[discord.Member] = None
    ) -> None:
        target = user or interaction.user
        row = await asyncio.to_thread(db.get_user_stats, str(target.id))
        practice = await asyncio.to_thread(db.get_practice_stats, str(target.id))

        embed = discord.Embed(
            title=f"📊 Stats — {target.display_name}",
            color=0x7289DA,
        )

        daily_played = row["days_played"] if row else 0
        practice_solved = practice["problems_solved"] if practice else 0

        if daily_played == 0 and practice_solved == 0:
            embed.description = f"{target.display_name} hasn't completed any problems yet."
            await interaction.response.send_message(embed=embed)
            return

        if daily_played > 0:
            embed.add_field(
                name="📅 Daily",
                value=(
                    f"{row['days_played']} days • **{row['total_points']} pts**\n"
                    f"avg {row['avg_points']:.1f}"
                ),
                inline=True,
            )
        if practice_solved > 0:
            embed.add_field(
                name="🎯 Practice",
                value=(
                    f"{practice['problems_solved']} solved • **{practice['total_points']} pts**\n"
                    f"avg {practice['avg_points']:.1f}"
                ),
                inline=True,
            )

        combined = (row["total_points"] if row else 0) + (practice["total_points"] if practice else 0)
        embed.add_field(name="Combined Points", value=str(combined), inline=True)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
