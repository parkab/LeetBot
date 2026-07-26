"""Shared interview machinery used by both the daily and practice cogs.

Everything here is mode-agnostic: it works off an InterviewSession and branches
on `session.mode` only where daily and practice genuinely differ (which table
the score lands in, and what the completion embed says).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord

import leetbot.config as config
import leetbot.db as db
from leetbot.interview.gemini import (
    generate_reference_solution,
    generate_step_solution,
    get_hint,
    grade_answer,
)
from leetbot.interview.prompts import get_first_prompt
from leetbot.interview.session import InterviewSession, State
from leetbot.utils.format import extract_code_block

logger = logging.getLogger(__name__)

UNAVAILABLE_REF = {"# Reference solution unavailable", "# Not available", ""}

STEP_HEADER: dict[State, str] = {
    State.BRUTE_FORCE: "Step 1 of 3 — Brute Force 🔨",
    State.TECHNIQUE: "Step 2 of 3 — Optimal Technique 🧠",
    State.CODE: "Step 3 of 3 — Implementation 💻",
}

STEP_NAMES: dict[State, str] = {
    State.BRUTE_FORCE: "Brute Force",
    State.TECHNIQUE: "Optimal Technique",
    State.CODE: "Code",
}


def is_usable_reference(solution: Optional[str]) -> bool:
    return bool(solution) and solution not in UNAVAILABLE_REF


async def ensure_reference_solution(session: InterviewSession) -> str:
    """Return the session's reference solution, generating and caching it on demand.

    Practice problems don't generate a reference solution up front — that would
    burn a Gemini call on every reroll. Instead it's produced the first time it's
    actually needed (code grading, /giveup on code, or session completion) and
    cached in the DB by slug so it's free for everyone afterwards.
    """
    if is_usable_reference(session.reference_solution):
        return session.reference_solution

    if session.is_practice and session.problem_slug:
        row = await asyncio.to_thread(db.get_practice_problem, session.problem_slug)
        if row is not None and is_usable_reference(row["reference_solution"]):
            session.reference_solution = row["reference_solution"]
            return session.reference_solution

    logger.info("Generating reference solution for %s", session.problem_title)
    solution = await generate_reference_solution(session.problem_title, session.problem_content)
    session.reference_solution = solution

    if is_usable_reference(solution):
        if session.is_practice and session.problem_slug:
            await asyncio.to_thread(
                db.set_practice_reference_solution, session.problem_slug, solution
            )
        elif not session.is_practice:
            await asyncio.to_thread(db.set_reference_solution, session.day_key, solution)

    return solution


# ── Embeds ────────────────────────────────────────────────────────────────────

def step_embed(session: InterviewSession) -> discord.Embed:
    step = session.state
    penalty_info = {
        State.BRUTE_FORCE: f"−{config.BF_PENALTY} pts per retry (floor {config.BF_FLOOR})",
        State.TECHNIQUE: f"−{config.TECH_PENALTY} pts per retry (floor {config.TECH_FLOOR})",
        State.CODE: f"−{config.CODE_PENALTY} pts per retry (floor {config.CODE_FLOOR})",
    }
    hints_used = session.hints_for_current_step()
    hint_note = f" • hints used: {hints_used}" if hints_used else ""
    embed = discord.Embed(
        title=STEP_HEADER[step],
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


def _score_breakdown_lines(session: InterviewSession) -> str:
    breakdown = session.step_breakdown()
    return (
        f"Brute Force: {breakdown['brute_force']} / {config.BF_MAX}\n"
        f"Technique:   {breakdown['technique']} / {config.TECH_MAX}\n"
        f"Code:        {breakdown['code']} / {config.CODE_MAX}"
    )


# ── Persistent hint button ────────────────────────────────────────────────────

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
        hint_text = await get_hint(
            step=session.state.value,
            hint_number=hint_number,
            problem_title=session.problem_title,
            problem_content=session.problem_content,
            previous_answers=session.answers_for_current_step(),
        )

        embed = discord.Embed(
            title=f"💡 Hint #{hint_number}",
            description=hint_text,
            color=0xF0A500,
        )
        if hint_number >= 3:
            embed.set_footer(
                text="This is a detailed hint — the next level reveals the solution directly."
            )
        await interaction.followup.send(embed=embed)


# ── Answer handling ───────────────────────────────────────────────────────────

async def handle_answer(
    message: discord.Message,
    session: InterviewSession,
    session_manager,
) -> None:
    step = session.state.value
    answer = extract_code_block(message.content)
    session.record_answer(answer)

    reference: Optional[str] = None
    async with message.channel.typing():
        if step == "code":
            reference = await ensure_reference_solution(session)
        verdict = await grade_answer(
            step=step,
            problem_title=session.problem_title,
            problem_content=session.problem_content,
            user_answer=answer,
            reference_solution=reference,
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
            await finish_session(message.channel, session, session_manager)
        else:
            await message.channel.send(embed=step_embed(session), view=HintView())
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
        await message.channel.send(embed=step_embed(session), view=HintView())


# ── Scoring / persistence ─────────────────────────────────────────────────────

async def _persist_score(session: InterviewSession, score: int) -> Optional[bool]:
    """Write the score to the right table. Returns is_best for practice, None for daily."""
    if session.is_practice:
        return await asyncio.to_thread(
            db.record_practice_attempt,
            session.user_id, session.list_name or "", session.problem_slug or "",
            session.problem_title, session.problem_difficulty or "", score,
            session.bf_retries, session.tech_retries, session.code_retries,
        )
    await asyncio.to_thread(
        db.record_attempt,
        session.user_id, session.day_key, score,
        session.bf_retries, session.tech_retries, session.code_retries,
    )
    return None


def _completion_footer(session: InterviewSession, is_best: Optional[bool]) -> str:
    if not session.is_practice:
        return "Use /leaderboard daily to see where you stand!"
    if is_best is False:
        return "You'd already scored higher on this one — your best score is kept."
    return "Use /leaderboard practice to see where you stand!"


async def finish_session(
    channel: discord.abc.Messageable,
    session: InterviewSession,
    session_manager,
) -> None:
    score = session.compute_score()
    reference = await ensure_reference_solution(session)
    is_best = await _persist_score(session, score)
    session_manager.remove(session)

    title = "🎉 Interview Complete!"
    if session.is_practice:
        title = f"🎉 Complete — {session.problem_title}"

    embed = discord.Embed(
        title=title,
        color=0x00B8A9,
        description=(
            f"**Total: {score} / 100 pts**\n\n"
            f"{_score_breakdown_lines(session)}\n\n"
            f"**Reference solution:**\n```python\n{reference[:1500]}\n```"
        ),
    )
    embed.set_footer(text=_completion_footer(session, is_best))
    await channel.send(embed=embed)
    logger.info(
        "User %s completed %s (%s) with %d pts",
        session.user_id, session.session_key, session.mode.value, score,
    )


# ── /giveup ───────────────────────────────────────────────────────────────────

async def handle_giveup(
    interaction: discord.Interaction,
    session: InterviewSession,
    session_manager,
) -> None:
    """Skip the current step for 0 pts, show its solution, and advance or finish."""
    skipped_step = session.state
    is_last_step = skipped_step == State.CODE

    if is_last_step:
        step_solution = await ensure_reference_solution(session)
        solution_label = "Reference solution"
    else:
        step_solution = await generate_step_solution(
            step=skipped_step.value,
            problem_title=session.problem_title,
            problem_content=session.problem_content,
        )
        solution_label = "Correct approach"

    session.skip_current_step()

    if is_last_step or session.state == State.DONE:
        score = session.compute_score()
        is_best = await _persist_score(session, score)
        session_manager.remove(session)

        solution_block = (
            f"```python\n{step_solution[:1500]}\n```" if is_last_step else step_solution
        )
        embed = discord.Embed(
            title=f"⏭️ Skipped: {STEP_NAMES[skipped_step]} — Interview Over",
            color=0xFF375F,
            description=(
                f"**{solution_label}:**\n{solution_block}\n\n"
                f"**Final score: {score} / 100 pts**\n"
                f"{_score_breakdown_lines(session)}"
            ),
        )
        embed.set_footer(text=_completion_footer(session, is_best))
        await interaction.followup.send(embed=embed)
        logger.info(
            "User %s skipped final step on %s, score %d",
            session.user_id, session.session_key, score,
        )
        return

    skip_embed = discord.Embed(
        title=f"⏭️ Skipped: {STEP_NAMES[skipped_step]} (0 pts)",
        color=0xFFA116,
        description=f"**{solution_label}:**\n{step_solution}",
    )
    skip_embed.set_footer(text="Moving on to the next step — you can still earn points!")
    await interaction.followup.send(embed=skip_embed)
    await interaction.followup.send(embed=step_embed(session), view=HintView())
    logger.info("User %s skipped %s on %s", session.user_id, skipped_step.value, session.session_key)
