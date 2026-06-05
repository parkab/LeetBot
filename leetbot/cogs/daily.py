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
from leetbot.interview.gemini import (
    explain_solution,
    generate_reference_solution,
    generate_step_solution,
    get_hint,
    grade_answer,
)
from leetbot.interview.prompts import get_first_prompt
from leetbot.interview.session import InterviewSession, State
from leetbot.leetcode import fetch_daily
from leetbot.utils.format import build_daily_embed, extract_code_block, html_to_text
from leetbot.utils.time import today_key

if TYPE_CHECKING:
    from leetbot.bot import LeetBot

logger = logging.getLogger(__name__)

_UNAVAILABLE_REF = {"# Reference solution unavailable", "# Not available", ""}


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


class HintView(discord.ui.View):
    """Attached to every step embed — lets the user request a hint for that step."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="💡 Get Hint",
        style=discord.ButtonStyle.secondary,
        custom_id="persistent:get_hint",
    )
    async def get_hint_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        session = interaction.client.session_manager.get_by_channel(interaction.channel.id)  # type: ignore[attr-defined]

        if session is None:
            await interaction.response.send_message(
                "No active session in this channel.", ephemeral=True
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

        hint_number = session.increment_hint()
        previous_answers = session.answers_for_current_step()

        hint_text = await get_hint(
            step=session.state.value,
            hint_number=hint_number,
            problem_title=session.problem_title,
            problem_content=session.problem_content,
            previous_answers=previous_answers,
        )

        embed = discord.Embed(
            title=f"💡 Hint #{hint_number}",
            description=hint_text,
            color=0xF0A500,
        )
        if hint_number >= 3:
            embed.set_footer(text="This is a detailed hint — the next level reveals the solution directly.")
        await interaction.followup.send(embed=embed)


# ── Step embed helpers ────────────────────────────────────────────────────────

_STEP_HEADER: dict[State, str] = {
    State.BRUTE_FORCE: "Step 1 of 3 — Brute Force 🔨",
    State.TECHNIQUE: "Step 2 of 3 — Optimal Technique 🧠",
    State.CODE: "Step 3 of 3 — Python Implementation 💻",
}

_RETRY_PREFIX = "❌ Not quite. "


def _step_embed(session: InterviewSession) -> discord.Embed:
    step = session.state
    penalty_info = {
        State.BRUTE_FORCE: f"−{config.BF_PENALTY} pts per retry (floor {config.BF_FLOOR})",
        State.TECHNIQUE: f"−{config.TECH_PENALTY} pts per retry (floor {config.TECH_FLOOR})",
        State.CODE: f"−{config.CODE_PENALTY} pts per retry (floor {config.CODE_FLOOR})",
    }
    hints_used = session.hints_for_current_step()
    hint_note = f" • hints used: {hints_used}" if hints_used else ""
    embed = discord.Embed(
        title=_STEP_HEADER[step],
        description=get_first_prompt(step.value),
        color=0x7289DA,
    )
    embed.set_footer(
        text=(
            f"{penalty_info[step]} • /giveup to skip this step"
            f" • current score: {session.compute_score()}{hint_note}"
        )
    )
    return embed


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
        day_key = today_key()
        session = self.bot.session_manager.get_by_user_day(str(interaction.user.id), day_key)

        if session is None:
            await interaction.response.send_message(
                "You don't have an active interview session today.", ephemeral=True
            )
            return

        await interaction.response.defer()

        skipped_step = session.state
        is_last_step = skipped_step == State.CODE

        # Generate the solution explanation for the step being skipped
        if skipped_step == State.CODE:
            step_solution = session.reference_solution
            solution_label = "Reference solution"
        else:
            step_solution = await generate_step_solution(
                step=skipped_step.value,
                problem_title=session.problem_title,
                problem_content=session.problem_content,
            )
            solution_label = "Correct approach"

        step_names = {
            State.BRUTE_FORCE: "Brute Force",
            State.TECHNIQUE: "Optimal Technique",
            State.CODE: "Code",
        }

        # Advance state (skip = 0 pts for this step)
        session.skip_current_step()

        if is_last_step or session.state == State.DONE:
            # Session over
            score = session.compute_score()
            breakdown = session.step_breakdown()
            await asyncio.to_thread(
                db.record_attempt,
                session.user_id, session.day_key, score,
                session.bf_retries, session.tech_retries, session.code_retries,
            )
            self.bot.session_manager.remove(session)

            if skipped_step == State.CODE:
                solution_block = f"```python\n{step_solution[:1500]}\n```"
            else:
                solution_block = step_solution

            embed = discord.Embed(
                title=f"⏭️ Skipped: {step_names[skipped_step]} — Interview Over",
                color=0xFF375F,
                description=(
                    f"**{solution_label}:**\n{solution_block}\n\n"
                    f"**Final score: {score} / 100 pts**\n"
                    f"Brute Force: {breakdown['brute_force']} / {config.BF_MAX}\n"
                    f"Technique:   {breakdown['technique']} / {config.TECH_MAX}\n"
                    f"Code:        {breakdown['code']} / {config.CODE_MAX}"
                ),
            )
            await interaction.followup.send(embed=embed)
            logger.info("User %s skipped final step on %s, score %d", session.user_id, day_key, score)
        else:
            # Still more steps — show solution for skipped step, then next step prompt
            solution_block = step_solution
            skip_embed = discord.Embed(
                title=f"⏭️ Skipped: {step_names[skipped_step]} (0 pts)",
                color=0xFFA116,
                description=f"**{solution_label}:**\n{solution_block}",
            )
            skip_embed.set_footer(text="Moving on to the next step — you can still earn points!")
            await interaction.followup.send(embed=skip_embed)

            ch = self.bot.get_channel(session.channel_id) if session.channel_id else interaction.channel
            if ch and ch.id != interaction.channel.id:
                await ch.send(embed=skip_embed)

            target_ch = ch or interaction.channel
            await target_ch.send(embed=_step_embed(session), view=HintView())
            logger.info("User %s skipped %s on %s", session.user_id, skipped_step.value, day_key)

    @app_commands.command(name="explain", description="Ask any question about today's solution.")
    @app_commands.describe(question="What do you want to understand? e.g. 'how does line 3 work' or 'explain the whole approach'")
    async def explain(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer()

        day_key = today_key()
        row = await asyncio.to_thread(db.get_problem, day_key)
        if row is None:
            await interaction.followup.send(
                "Today's problem hasn't been posted yet.", ephemeral=True
            )
            return

        reference_solution = row["reference_solution"] or ""
        if not reference_solution or reference_solution in _UNAVAILABLE_REF:
            await interaction.followup.send(
                "The reference solution isn't available yet — try again in a moment.", ephemeral=True
            )
            return

        content_text = html_to_text(row["content_html"], max_chars=4000)
        answer = await explain_solution(
            question=question,
            problem_title=row["title"],
            problem_content=content_text,
            reference_solution=reference_solution,
        )

        embed = discord.Embed(
            title="💬 Explanation",
            description=answer,
            color=0x7289DA,
        )
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
        if not reference_solution or reference_solution in _UNAVAILABLE_REF:
            logger.info("Reference solution missing for %s — regenerating", day_key)
            reference_solution = await generate_reference_solution(row["title"], content_text)
            if reference_solution and reference_solution not in _UNAVAILABLE_REF:
                await asyncio.to_thread(db.set_reference_solution, day_key, reference_solution)

        session = InterviewSession(
            user_id=user_id,
            day_key=day_key,
            problem_title=row["title"],
            problem_content=content_text,
            problem_url=row["url"],
            reference_solution=reference_solution,
        )
        self.bot.session_manager.add(session)

        if private:
            await self._start_dm_session(interaction, session, row)
        else:
            await self._start_thread_session(interaction, session, row)

    async def _start_thread_session(
        self,
        interaction: discord.Interaction,
        session: InterviewSession,
        row: db.sqlite3.Row,
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
        await thread.send(embed=_step_embed(session), view=HintView())
        await interaction.followup.send(f"Your interview thread: {thread.jump_url}", ephemeral=True)
        logger.info("Started interview for user %s on %s (thread %s)", session.user_id, session.day_key, thread.id)

    async def _start_dm_session(
        self,
        interaction: discord.Interaction,
        session: InterviewSession,
        row: db.sqlite3.Row,
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
        await dm.send(embed=_step_embed(session), view=HintView())
        await interaction.followup.send("Check your DMs!", ephemeral=True)
        logger.info("Started private interview for user %s on %s", session.user_id, session.day_key)

    # ── Message listener ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
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

        await self._handle_answer(message, session)

    async def _handle_answer(
        self, message: discord.Message, session: InterviewSession
    ) -> None:
        step = session.state.value
        answer = extract_code_block(message.content)
        session.record_answer(answer)

        async with message.channel.typing():
            verdict = await grade_answer(
                step=step,
                problem_title=session.problem_title,
                problem_content=session.problem_content,
                user_answer=answer,
                reference_solution=session.reference_solution if step == "code" else None,
            )

        if verdict.verdict == "rate_limited":
            await message.channel.send(embed=discord.Embed(
                description=verdict.feedback, color=0xFFA116,
            ))
            return

        if verdict.accepted:
            session.accept()
            feedback_embed = discord.Embed(
                title="✅ Correct!",
                description=verdict.feedback,
                color=0x00B8A9,
            )
            if verdict.complexity_check:
                feedback_embed.add_field(name="Complexity", value=verdict.complexity_check, inline=False)
            await message.channel.send(embed=feedback_embed)

            if session.state == State.DONE:
                await self._finish_session(message.channel, session)
            else:
                await message.channel.send(embed=_step_embed(session), view=HintView())
        else:
            session.reject()
            retries = session.retries_for_current_step()
            feedback_embed = discord.Embed(
                title="❌ Not quite",
                description=verdict.feedback,
                color=0xFFA116,
            )
            if verdict.complexity_check:
                feedback_embed.add_field(name="Complexity", value=verdict.complexity_check, inline=False)
            feedback_embed.set_footer(
                text=f"Retry #{retries} • current score: {session.compute_score()} pts • use 💡 for a hint"
            )
            await message.channel.send(embed=feedback_embed)
            await message.channel.send(embed=_step_embed(session), view=HintView())

    async def _finish_session(
        self, channel: discord.abc.Messageable, session: InterviewSession
    ) -> None:
        score = session.compute_score()
        breakdown = session.step_breakdown()

        await asyncio.to_thread(
            db.record_attempt,
            session.user_id, session.day_key, score,
            session.bf_retries, session.tech_retries, session.code_retries,
        )
        self.bot.session_manager.remove(session)

        embed = discord.Embed(
            title="🎉 Interview Complete!",
            color=0x00B8A9,
            description=(
                f"**Total: {score} / 100 pts**\n\n"
                f"Brute Force: {breakdown['brute_force']} / {config.BF_MAX}\n"
                f"Technique:   {breakdown['technique']} / {config.TECH_MAX}\n"
                f"Code:        {breakdown['code']} / {config.CODE_MAX}\n\n"
                f"**Reference solution:**\n```python\n{session.reference_solution[:1500]}\n```"
            ),
        )
        embed.set_footer(text="Use /leaderboard daily to see where you stand!")
        await channel.send(embed=embed)
        logger.info("User %s completed %s with %d pts", session.user_id, session.day_key, score)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyCog(bot))  # type: ignore[arg-type]
