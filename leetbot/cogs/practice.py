"""Practice interviews drawn from curated LeetCode problem lists.

/grind75 and /paretoset each open a thread, ask for a difficulty, then serve a
random problem the user hasn't finished yet. Grading is identical to the daily
flow — everything after problem selection runs through interview/flow.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

import leetbot.config as config
import leetbot.db as db
from leetbot.interview.flow import HintView, step_embed
from leetbot.interview.session import InterviewSession, Mode, PendingPractice
from leetbot.leetcode import DailyProblem, fetch_question
from leetbot.problemlists import (
    PROBLEM_LISTS,
    ProblemList,
    available_difficulties,
    difficulty_counts,
    get_problems,
    pick_problem,
)
from leetbot.utils.format import build_practice_embed, html_to_text
from leetbot.utils.time import today_key

if TYPE_CHECKING:
    from leetbot.bot import LeetBot

logger = logging.getLogger(__name__)

_DIFFICULTY_STYLES = {
    "Easy": discord.ButtonStyle.success,
    "Medium": discord.ButtonStyle.primary,
    "Hard": discord.ButtonStyle.danger,
}


# ── Persistent views ──────────────────────────────────────────────────────────

class DifficultyView(discord.ui.View):
    """Posted in a fresh practice thread. Only shows difficulties the list has.

    Constructed with `available=None` for persistent registration (all buttons
    present); the instance actually sent to a thread is trimmed to what that
    list contains — the pareto list has no Hard problems.
    """

    def __init__(self, available: Optional[list[str]] = None) -> None:
        super().__init__(timeout=None)
        if available is None:
            return
        keep = {f"persistent:practice_diff:{d.lower()}" for d in available}
        keep.add("persistent:practice_diff:any")
        for item in list(self.children):
            if getattr(item, "custom_id", None) not in keep:
                self.remove_item(item)

    async def _choose(self, interaction: discord.Interaction, difficulty: Optional[str]) -> None:
        cog: Optional[PracticeCog] = interaction.client.cogs.get("PracticeCog")  # type: ignore[assignment]
        if cog is None:
            await interaction.response.send_message(
                "Bot is still initialising — try again in a moment.", ephemeral=True
            )
            return
        await cog._choose_difficulty(interaction, difficulty)

    @discord.ui.button(
        label="Easy", style=discord.ButtonStyle.success,
        custom_id="persistent:practice_diff:easy",
    )
    async def easy(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, "Easy")

    @discord.ui.button(
        label="Medium", style=discord.ButtonStyle.primary,
        custom_id="persistent:practice_diff:medium",
    )
    async def medium(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, "Medium")

    @discord.ui.button(
        label="Hard", style=discord.ButtonStyle.danger,
        custom_id="persistent:practice_diff:hard",
    )
    async def hard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, "Hard")

    @discord.ui.button(
        label="🎲 Any", style=discord.ButtonStyle.secondary,
        custom_id="persistent:practice_diff:any",
    )
    async def any_difficulty(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, None)


class ProblemView(discord.ui.View):
    """Attached to the practice problem embed — lets the user reroll for another."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔁 Different Problem",
        style=discord.ButtonStyle.secondary,
        custom_id="persistent:practice_reroll",
    )
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cog: Optional[PracticeCog] = interaction.client.cogs.get("PracticeCog")  # type: ignore[assignment]
        if cog is None:
            await interaction.response.send_message(
                "Bot is still initialising — try again in a moment.", ephemeral=True
            )
            return
        await cog._reroll(interaction)


# ── Cog ───────────────────────────────────────────────────────────────────────

class PracticeCog(commands.Cog, name="PracticeCog"):
    def __init__(self, bot: LeetBot) -> None:
        self.bot = bot

    # ── Slash commands ────────────────────────────────────────────────────────

    @app_commands.command(
        name="grind75",
        description="Practice a random problem from the Grind 75 list.",
    )
    async def grind75(self, interaction: discord.Interaction) -> None:
        await self._start_practice(interaction, "grind75")

    @app_commands.command(
        name="paretoset",
        description="Practice a random problem from the Pareto problem set.",
    )
    async def paretoset(self, interaction: discord.Interaction) -> None:
        await self._start_practice(interaction, "pareto")

    # ── Thread setup ──────────────────────────────────────────────────────────

    async def _start_practice(self, interaction: discord.Interaction, list_key: str) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = PROBLEM_LISTS[list_key]
        user_id = str(interaction.user.id)

        # One practice thread at a time, so users don't litter the channel.
        existing_channel_id: Optional[int] = None
        for existing in self.bot.session_manager.sessions_for_user(user_id):
            if existing.is_practice:
                existing_channel_id = existing.channel_id
                break
        else:
            pending = self.bot.session_manager.pending_for_user(user_id)
            if pending is not None:
                existing_channel_id = pending.channel_id

        if existing_channel_id is not None:
            ch = self.bot.get_channel(existing_channel_id)
            link = ch.jump_url if isinstance(ch, discord.Thread) else "your open practice thread"
            await interaction.followup.send(
                f"You already have a practice session running — head to {link}, "
                "or finish it with `/giveup`.",
                ephemeral=True,
            )
            return

        try:
            problems = await get_problems(list_key)
        except Exception as exc:
            logger.error("Failed to fetch problem list %s: %s", list_key, exc)
            await interaction.followup.send(
                "Couldn't reach LeetCode to load that problem list — try again in a moment.",
                ephemeral=True,
            )
            return

        if not problems:
            await interaction.followup.send(
                f"The {spec.label} list came back empty — try again later.", ephemeral=True
            )
            return

        parent = self._thread_parent(interaction)
        if parent is None:
            await interaction.followup.send(
                "I can't create a thread here — run this in a normal text channel.",
                ephemeral=True,
            )
            return

        try:
            thread = await parent.create_thread(
                name=f"{interaction.user.display_name} — {spec.label}"[:100],
                auto_archive_duration=1440,
                type=discord.ChannelType.public_thread,
            )
        except discord.HTTPException as exc:
            logger.error("Failed to create practice thread: %s", exc)
            await interaction.followup.send(
                "Failed to create the practice thread — try again.", ephemeral=True
            )
            return

        self.bot.session_manager.add_pending(
            PendingPractice(user_id=user_id, list_name=list_key, channel_id=thread.id)
        )

        counts = difficulty_counts(problems)
        available = available_difficulties(problems)
        completed = await asyncio.to_thread(db.get_completed_practice_slugs, user_id)
        done_here = sum(1 for p in problems if p.slug in completed)

        lines = [f"**{d}** — {counts[d]} problems" for d in available]
        embed = discord.Embed(
            title=f"{spec.emoji} {spec.label} — pick a difficulty",
            description=(
                f"[{len(problems)} problems in this list]({spec.url}) • "
                f"you've completed **{done_here}**\n\n" + "\n".join(lines)
            ),
            color=0xC9A84C,
        )
        embed.set_footer(text="I'll pick a random problem you haven't finished yet.")

        await thread.send(
            f"👋 Hey {interaction.user.mention}! Ready to practice.",
            embed=embed,
            view=DifficultyView(available=available),
        )
        await interaction.followup.send(f"Your practice thread: {thread.jump_url}", ephemeral=True)
        logger.info("Opened %s practice thread %s for user %s", list_key, thread.id, user_id)

    def _thread_parent(self, interaction: discord.Interaction) -> Optional[discord.TextChannel]:
        """Thread in the invoking channel when possible, else the daily channel."""
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel):
            return channel
        fallback = self.bot.get_channel(config.DAILY_CHANNEL_ID)
        return fallback if isinstance(fallback, discord.TextChannel) else None

    # ── Difficulty selection ──────────────────────────────────────────────────

    async def _choose_difficulty(
        self, interaction: discord.Interaction, difficulty: Optional[str]
    ) -> None:
        pending = self.bot.session_manager.get_pending(interaction.channel.id)
        if pending is None:
            # Either the difficulty was already chosen, or the thread went stale.
            if self.bot.session_manager.get_by_channel(interaction.channel.id) is not None:
                message = (
                    "You've already picked a difficulty for this thread — "
                    "use 🔁 **Different Problem** if you want another one."
                )
            else:
                message = (
                    "This practice thread is no longer active — "
                    "run `/grind75` or `/paretoset` again."
                )
            await interaction.response.send_message(message, ephemeral=True)
            return
        if interaction.user.id != int(pending.user_id):
            await interaction.response.send_message(
                "This isn't your practice thread.", ephemeral=True
            )
            return

        await interaction.response.defer()

        session = await self._build_session(
            interaction, pending.user_id, pending.list_name, difficulty
        )
        if session is None:
            return

        self.bot.session_manager.remove_pending(interaction.channel.id)
        self.bot.session_manager.add(session)
        self.bot.session_manager.register_channel(session, interaction.channel.id)

        await self._send_problem(interaction.channel, session, interaction.followup)

    # ── Reroll ────────────────────────────────────────────────────────────────

    async def _reroll(self, interaction: discord.Interaction) -> None:
        session = self.bot.session_manager.get_by_channel(interaction.channel.id)
        if session is None or not session.is_practice:
            await interaction.response.send_message(
                "No active practice session in this thread.", ephemeral=True
            )
            return
        if interaction.user.id != int(session.user_id):
            await interaction.response.send_message(
                "This isn't your practice session.", ephemeral=True
            )
            return

        await interaction.response.defer()

        replacement = await self._build_session(
            interaction,
            session.user_id,
            session.list_name or "",
            session.difficulty_filter,
            exclude_extra={session.problem_slug} if session.problem_slug else set(),
        )
        if replacement is None:
            return

        # Swap the problem onto the existing session and wipe any progress made.
        old_key = session.session_key
        session.problem_title = replacement.problem_title
        session.problem_content = replacement.problem_content
        session.problem_url = replacement.problem_url
        session.problem_slug = replacement.problem_slug
        session.problem_difficulty = replacement.problem_difficulty
        session.reference_solution = replacement.reference_solution
        session.is_repeat = replacement.is_repeat
        session.reset_progress()
        self.bot.session_manager.rekey(session, old_key)

        logger.info(
            "User %s rerolled to %s in thread %s",
            session.user_id, session.problem_slug, interaction.channel.id,
        )
        await self._send_problem(interaction.channel, session, interaction.followup)

    # ── Problem selection / delivery ──────────────────────────────────────────

    async def _build_session(
        self,
        interaction: discord.Interaction,
        user_id: str,
        list_key: str,
        difficulty: Optional[str],
        exclude_extra: Optional[set[str]] = None,
    ) -> Optional[InterviewSession]:
        """Pick a problem and build a session for it. Reports failures to the user."""
        try:
            problems = await get_problems(list_key)
        except Exception as exc:
            logger.error("Failed to fetch problem list %s: %s", list_key, exc)
            await interaction.followup.send(
                "Couldn't reach LeetCode right now — try again in a moment."
            )
            return None

        completed = await asyncio.to_thread(db.get_completed_practice_slugs, user_id)
        exclude = completed | (exclude_extra or set())

        listed, is_repeat = pick_problem(problems, difficulty, exclude)
        if listed is None:
            label = difficulty or "any difficulty"
            await interaction.followup.send(
                f"No **{label}** problems available in that list."
            )
            return None

        try:
            problem = await self._load_problem(listed.slug, listed.title, listed.difficulty)
        except Exception as exc:
            logger.error("Failed to fetch problem %s: %s", listed.slug, exc)
            await interaction.followup.send(
                f"Couldn't load **{listed.title}** from LeetCode — press 🔁 to try another."
            )
            return None

        content_text = html_to_text(problem.content_html, max_chars=4000)
        session = InterviewSession(
            user_id=user_id,
            day_key=today_key(),
            problem_title=problem.title,
            problem_content=content_text,
            problem_url=problem.url,
            reference_solution="",  # generated lazily — see flow.ensure_reference_solution
            mode=Mode.PRACTICE,
            list_name=list_key,
            problem_slug=problem.slug,
            problem_difficulty=problem.difficulty,
            difficulty_filter=difficulty,
            is_repeat=is_repeat,
        )
        return session

    async def _load_problem(self, slug: str, title: str, difficulty: str) -> DailyProblem:
        """Return a problem statement, using the DB cache before hitting LeetCode."""
        row = await asyncio.to_thread(db.get_practice_problem, slug)
        if row is not None and row["content_html"]:
            return DailyProblem(
                title=row["title"],
                slug=row["slug"],
                difficulty=row["difficulty"],
                url=row["url"],
                content_html=row["content_html"],
            )

        problem = await fetch_question(slug)
        await asyncio.to_thread(
            db.upsert_practice_problem,
            problem.slug, problem.title, problem.difficulty,
            problem.url, problem.content_html, None,
        )
        return problem

    async def _send_problem(
        self,
        channel: discord.abc.Messageable,
        session: InterviewSession,
        followup: discord.Webhook,
    ) -> None:
        spec: ProblemList = PROBLEM_LISTS[session.list_name or "grind75"]
        embed = build_practice_embed(
            title=session.problem_title,
            url=session.problem_url,
            difficulty=session.problem_difficulty or "",
            content_text=session.problem_content,
            list_label=spec.label,
            list_url=spec.url,
            is_repeat=session.is_repeat,
        )
        await followup.send(embed=embed, view=ProblemView())
        await channel.send(embed=step_embed(session), view=HintView())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PracticeCog(bot))  # type: ignore[arg-type]
