from __future__ import annotations

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import leetbot.config as config
import leetbot.db as db
from leetbot.interview.flow import (
    HintView,
    handle_answer,
    handle_giveup,
    is_usable_reference,
    step_embed,
)
from leetbot.interview.gemini import explain_solution, generate_reference_solution
from leetbot.interview.session import InterviewSession, Mode, State
from leetbot.leetcode import fetch_daily
from leetbot.utils.format import build_daily_embed, html_to_text
from leetbot.utils.time import today_key

if TYPE_CHECKING:
    from leetbot.bot import LeetBot

logger = logging.getLogger(__name__)


# ── Persistent views ──────────────────────────────────────────────────────────

class DailyView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎯 Start Interview",
        style=discord.ButtonStyle.primary,
        custom_id="persistent:start_interview",
    )
    async def start_interview(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        cog: Optional[DailyCog] = interaction.client.cogs.get("DailyCog")  # type: ignore[assignment]
        if cog is None:
            await interaction.response.send_message(
                "Bot is still initialising — try again in a moment.", ephemeral=True
            )
            return
        await cog._start_solve_flow(interaction, private=False)


# ── Cog ───────────────────────────────────────────────────────────────────────

class DailyCog(commands.Cog, name="DailyCog"):
    def __init__(self, bot: LeetBot) -> None:
        self.bot = bot
        self.daily_task.start()

    def cog_unload(self) -> None:
        self.daily_task.cancel()

    # ── Background loop ───────────────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def daily_task(self) -> None:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        if now_utc.hour != config.DAILY_POST_HOUR_UTC:
            return

        day_key = today_key()
        existing = await asyncio.to_thread(db.get_problem, day_key)
        if existing is not None:
            return

        channel = self.bot.get_channel(config.DAILY_CHANNEL_ID)
        if channel is None:
            logger.error("Daily channel %s not found", config.DAILY_CHANNEL_ID)
            return

        await self._post_daily(channel)

    @daily_task.before_loop
    async def _before_daily(self) -> None:
        await self.bot.wait_until_ready()

    # ── Core posting logic ────────────────────────────────────────────────────

    async def _post_daily(
        self,
        channel: discord.TextChannel,
        force: bool = False,
    ) -> Optional[discord.Message]:
        day_key = today_key()

        if not force:
            existing = await asyncio.to_thread(db.get_problem, day_key)
            if existing is not None:
                return None

        problem = None
        for attempt in range(5):
            try:
                problem = await fetch_daily()
                break
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning("LeetCode fetch attempt %d failed: %s. Retry in %ds", attempt + 1, exc, wait)
                if attempt < 4:
                    await asyncio.sleep(wait)

        if problem is None:
            logger.error("LeetCode fetch failed after 5 attempts for %s", day_key)
            try:
                owner = await self.bot.fetch_user(config.BOT_OWNER_ID)
                await channel.send(
                    f"{owner.mention} LeetCode fetch failed for `{day_key}`. Please check."
                )
            except Exception:
                pass
            return None

        content_text = html_to_text(problem.content_html, max_chars=4000)
        reference_solution = await generate_reference_solution(problem.title, content_text)

        posted_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await asyncio.to_thread(
            db.upsert_problem,
            day_key, problem.title, problem.slug, problem.difficulty,
            problem.url, problem.content_html, posted_at, reference_solution,
        )

        embed = build_daily_embed(problem, day_key)
        msg = await channel.send(embed=embed, view=DailyView())
        await asyncio.to_thread(db.set_problem_message_id, day_key, str(msg.id))
        logger.info("Posted daily challenge for %s: %s", day_key, problem.title)
        return msg

    # ── Slash commands ────────────────────────────────────────────────────────

    @app_commands.command(name="daily", description="Repost today's LeetCode challenge.")
    async def daily(self, interaction: discord.Interaction) -> None:
        day_key = today_key()
        row = await asyncio.to_thread(db.get_problem, day_key)
        if row is None:
            await interaction.response.send_message(
                f"Today's problem hasn't been posted yet (posts at {config.DAILY_POST_HOUR_UTC}:00 UTC).",
                ephemeral=True,
            )
            return

        from leetbot.leetcode import DailyProblem
        problem = DailyProblem(
            title=row["title"], slug=row["slug"], difficulty=row["difficulty"],
            url=row["url"], content_html=row["content_html"],
        )
        await interaction.response.send_message(embed=build_daily_embed(problem, day_key), view=DailyView())

    @app_commands.command(name="solve", description="Start an interview on today's problem.")
    @app_commands.describe(private="Send the interview to your DMs instead of a public thread.")
    async def solve(self, interaction: discord.Interaction, private: bool = False) -> None:
        await self._start_solve_flow(interaction, private=private)

    @app_commands.command(name="giveup", description="Skip the current step (score 0 for it) and move on.")
    async def giveup(self, interaction: discord.Interaction) -> None:
        # Route by channel first so this works for daily and practice threads alike.
        session = self.bot.session_manager.get_by_channel(interaction.channel.id)

        if session is None:
            # Fall back to the user's daily session so /giveup still works from
            # anywhere, but point them at the thread rather than replying here.
            daily_session = self.bot.session_manager.get_by_user_day(
                str(interaction.user.id), today_key()
            )
            if daily_session is not None and daily_session.channel_id:
                ch = self.bot.get_channel(daily_session.channel_id)
                where = ch.jump_url if isinstance(ch, discord.Thread) else "your DMs"
                await interaction.response.send_message(
                    f"Run `/giveup` inside your interview session — {where}.", ephemeral=True
                )
                return
            await interaction.response.send_message(
                "You don't have an active interview session here.", ephemeral=True
            )
            return

        if interaction.user.id != int(session.user_id):
            await interaction.response.send_message(
                "This isn't your interview session.", ephemeral=True
            )
            return
        if session.state == State.DONE:
            await interaction.response.send_message(
                "Your session is already complete!", ephemeral=True
            )
            return

        await interaction.response.defer()
        await handle_giveup(interaction, session, self.bot.session_manager)

    @app_commands.command(name="explain", description="Ask any question about today's solution.")
    @app_commands.describe(question="What do you want to understand? e.g. 'how does line 3 work' or 'explain the whole approach'")
    async def explain(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer()

        # Inside an interview thread, explain that problem instead of today's.
        session = self.bot.session_manager.get_by_channel(interaction.channel.id)
        if session is not None:
            from leetbot.interview.flow import ensure_reference_solution
            title = session.problem_title
            content_text = session.problem_content
            reference_solution = await ensure_reference_solution(session)
        else:
            day_key = today_key()
            row = await asyncio.to_thread(db.get_problem, day_key)
            if row is None:
                await interaction.followup.send(
                    "Today's problem hasn't been posted yet.", ephemeral=True
                )
                return
            title = row["title"]
            content_text = html_to_text(row["content_html"], max_chars=4000)
            reference_solution = row["reference_solution"] or ""

        if not is_usable_reference(reference_solution):
            await interaction.followup.send(
                "The reference solution isn't available yet — try again in a moment.", ephemeral=True
            )
            return

        answer = await explain_solution(
            question=question,
            problem_title=title,
            problem_content=content_text,
            reference_solution=reference_solution,
        )

        embed = discord.Embed(title="💬 Explanation", description=answer, color=0x7289DA)
        embed.set_footer(text=f"Q: {question[:120]}")
        await interaction.followup.send(embed=embed)

    # ── Shared solve flow ─────────────────────────────────────────────────────

    async def _start_solve_flow(
        self, interaction: discord.Interaction, private: bool
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        user_id = str(interaction.user.id)
        day_key = today_key()

        existing_attempt = await asyncio.to_thread(db.get_attempt, user_id, day_key)
        if existing_attempt is not None:
            await interaction.followup.send(
                f"You already completed today's problem with **{existing_attempt['points']} pts**! "
                "Check `/leaderboard daily` to see where you stand.",
                ephemeral=True,
            )
            return

        existing_session = self.bot.session_manager.get_by_user_day(user_id, day_key)
        if existing_session is not None:
            ch = self.bot.get_channel(existing_session.channel_id) if existing_session.channel_id else None
            link = ch.jump_url if isinstance(ch, discord.Thread) else "your DMs"
            await interaction.followup.send(
                f"You already have an active interview session — head to {link}.",
                ephemeral=True,
            )
            return

        row = await asyncio.to_thread(db.get_problem, day_key)
        if row is None:
            await interaction.followup.send(
                f"Today's problem hasn't been posted yet (posts at {config.DAILY_POST_HOUR_UTC}:00 UTC). "
                "Ask an admin to `/forcedaily`.",
                ephemeral=True,
            )
            return

        content_text = html_to_text(row["content_html"], max_chars=4000)

        # Lazily regenerate reference solution if it was missing or failed previously
        reference_solution = row["reference_solution"] or ""
        if not is_usable_reference(reference_solution):
            logger.info("Reference solution missing for %s — regenerating", day_key)
            reference_solution = await generate_reference_solution(row["title"], content_text)
            if is_usable_reference(reference_solution):
                await asyncio.to_thread(db.set_reference_solution, day_key, reference_solution)

        session = InterviewSession(
            user_id=user_id,
            day_key=day_key,
            problem_title=row["title"],
            problem_content=content_text,
            problem_url=row["url"],
            reference_solution=reference_solution,
            mode=Mode.DAILY,
            problem_slug=row["slug"],
            problem_difficulty=row["difficulty"],
        )
        self.bot.session_manager.add(session)

        if private:
            await self._start_dm_session(interaction, session)
        else:
            await self._start_thread_session(interaction, session)

    async def _start_thread_session(
        self, interaction: discord.Interaction, session: InterviewSession
    ) -> None:
        daily_channel = self.bot.get_channel(config.DAILY_CHANNEL_ID)
        if daily_channel is None:
            await interaction.followup.send("Daily channel not found — contact an admin.", ephemeral=True)
            self.bot.session_manager.remove(session)
            return

        try:
            thread = await daily_channel.create_thread(
                name=f"{interaction.user.display_name} — {session.day_key}",
                auto_archive_duration=1440,
                type=discord.ChannelType.public_thread,
            )
        except discord.HTTPException as exc:
            logger.error("Failed to create thread: %s", exc)
            await interaction.followup.send("Failed to create interview thread — try again.", ephemeral=True)
            self.bot.session_manager.remove(session)
            return

        self.bot.session_manager.register_channel(session, thread.id)

        await thread.send(
            f"👋 Hey {interaction.user.mention}! Let's tackle **[{session.problem_title}]({session.problem_url})**.\n"
            f"Type your answers here. Use 💡 **Get Hint** for a nudge, or `/giveup` to skip a step.\n​"
        )
        await thread.send(embed=step_embed(session), view=HintView())
        await interaction.followup.send(f"Your interview thread: {thread.jump_url}", ephemeral=True)
        logger.info("Started interview for user %s on %s (thread %s)", session.user_id, session.day_key, thread.id)

    async def _start_dm_session(
        self, interaction: discord.Interaction, session: InterviewSession
    ) -> None:
        try:
            dm = await interaction.user.create_dm()
        except discord.HTTPException:
            await interaction.followup.send("Couldn't open a DM. Enable DMs from server members.", ephemeral=True)
            self.bot.session_manager.remove(session)
            return

        self.bot.session_manager.register_channel(session, dm.id)
        await dm.send(
            f"👋 Let's tackle **[{session.problem_title}]({session.problem_url})**.\n"
            f"Type your answers here. Use 💡 **Get Hint** for a nudge, or `/giveup` to skip a step.\n​"
        )
        await dm.send(embed=step_embed(session), view=HintView())
        await interaction.followup.send("Check your DMs!", ephemeral=True)
        logger.info("Started private interview for user %s on %s", session.user_id, session.day_key)

    # ── Message listener ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Routes answers for BOTH daily and practice sessions — they're keyed by channel."""
        if message.author.bot:
            return

        session = self.bot.session_manager.get_by_channel(message.channel.id)
        if session is None:
            return
        if message.author.id != int(session.user_id):
            return
        if message.content.startswith("#"):
            return
        if session.state == State.DONE:
            return

        await handle_answer(message, session, self.bot.session_manager)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyCog(bot))  # type: ignore[arg-type]
