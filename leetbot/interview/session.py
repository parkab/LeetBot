from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import leetbot.config as config


class State(str, Enum):
    BRUTE_FORCE = "brute_force"
    TECHNIQUE = "technique"
    CODE = "code"
    DONE = "done"


_NEXT_STATE: dict[State, State] = {
    State.BRUTE_FORCE: State.TECHNIQUE,
    State.TECHNIQUE: State.CODE,
    State.CODE: State.DONE,
}


class Mode(str, Enum):
    DAILY = "daily"
    PRACTICE = "practice"


@dataclass
class PendingPractice:
    """A practice thread that exists but has no problem yet.

    Created when /grind75 or /paretoset opens the thread, and consumed once the
    user picks a difficulty.
    """
    user_id: str
    list_name: str
    channel_id: int


@dataclass
class InterviewSession:
    user_id: str
    day_key: str
    problem_title: str
    problem_content: str   # plaintext (HTML stripped)
    problem_url: str
    reference_solution: str

    # Practice mode — set when the session came from a curated problem list.
    mode: Mode = Mode.DAILY
    list_name: Optional[str] = None        # "grind75" | "pareto"
    problem_slug: Optional[str] = None
    problem_difficulty: Optional[str] = None
    difficulty_filter: Optional[str] = None  # what the user picked; None = "any"
    is_repeat: bool = False                  # every problem at this difficulty is done

    channel_id: Optional[int] = None
    state: State = field(default=State.BRUTE_FORCE)

    # Retry counters
    bf_retries: int = 0
    tech_retries: int = 0
    code_retries: int = 0

    # Hint counters per step
    bf_hints: int = 0
    tech_hints: int = 0
    code_hints: int = 0

    # Whether each step was skipped via /giveup (score = 0 for skipped steps)
    bf_skipped: bool = False
    tech_skipped: bool = False
    code_skipped: bool = False

    # Previous answers per step — passed to Gemini for hint context
    bf_answers: list[str] = field(default_factory=list)
    tech_answers: list[str] = field(default_factory=list)
    code_answers: list[str] = field(default_factory=list)

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def session_key(self) -> str:
        """Unique per-user key. Daily sessions key by day, practice by problem,
        so a user can have a daily thread and a practice thread open at once."""
        if self.mode == Mode.PRACTICE:
            return f"practice:{self.problem_slug}"
        return self.day_key

    @property
    def is_practice(self) -> bool:
        return self.mode == Mode.PRACTICE

    def reset_progress(self) -> None:
        """Wipe all step progress — used when a practice user rerolls the problem."""
        self.state = State.BRUTE_FORCE
        self.bf_retries = self.tech_retries = self.code_retries = 0
        self.bf_hints = self.tech_hints = self.code_hints = 0
        self.bf_skipped = self.tech_skipped = self.code_skipped = False
        self.bf_answers.clear()
        self.tech_answers.clear()
        self.code_answers.clear()

    # ── Answer recording ──────────────────────────────────────────────────────

    def record_answer(self, answer: str) -> None:
        if self.state == State.BRUTE_FORCE:
            self.bf_answers.append(answer)
        elif self.state == State.TECHNIQUE:
            self.tech_answers.append(answer)
        elif self.state == State.CODE:
            self.code_answers.append(answer)

    def answers_for_current_step(self) -> list[str]:
        return {
            State.BRUTE_FORCE: self.bf_answers,
            State.TECHNIQUE: self.tech_answers,
            State.CODE: self.code_answers,
        }.get(self.state, [])

    # ── Hint tracking ─────────────────────────────────────────────────────────

    def hints_for_current_step(self) -> int:
        return {
            State.BRUTE_FORCE: self.bf_hints,
            State.TECHNIQUE: self.tech_hints,
            State.CODE: self.code_hints,
        }.get(self.state, 0)

    def increment_hint(self) -> int:
        """Increment hint count for current step and return the new count."""
        if self.state == State.BRUTE_FORCE:
            self.bf_hints += 1
            return self.bf_hints
        elif self.state == State.TECHNIQUE:
            self.tech_hints += 1
            return self.tech_hints
        elif self.state == State.CODE:
            self.code_hints += 1
            return self.code_hints
        return 0

    # ── State transitions ─────────────────────────────────────────────────────

    def retries_for_current_step(self) -> int:
        return {
            State.BRUTE_FORCE: self.bf_retries,
            State.TECHNIQUE: self.tech_retries,
            State.CODE: self.code_retries,
        }.get(self.state, 0)

    def accept(self) -> None:
        if self.state != State.DONE:
            self.state = _NEXT_STATE[self.state]

    def reject(self) -> None:
        if self.state == State.BRUTE_FORCE:
            self.bf_retries += 1
        elif self.state == State.TECHNIQUE:
            self.tech_retries += 1
        elif self.state == State.CODE:
            self.code_retries += 1

    def skip_current_step(self) -> None:
        """Mark current step as 0 pts and advance to the next state."""
        if self.state == State.BRUTE_FORCE:
            self.bf_skipped = True
        elif self.state == State.TECHNIQUE:
            self.tech_skipped = True
        elif self.state == State.CODE:
            self.code_skipped = True
        if self.state != State.DONE:
            self.state = _NEXT_STATE[self.state]

    # ── Scoring ───────────────────────────────────────────────────────────────

    def compute_score(self) -> int:
        total = 0
        if self.state in (State.TECHNIQUE, State.CODE, State.DONE):
            if not self.bf_skipped:
                total += max(config.BF_FLOOR, config.BF_MAX - config.BF_PENALTY * self.bf_retries)
        if self.state in (State.CODE, State.DONE):
            if not self.tech_skipped:
                total += max(config.TECH_FLOOR, config.TECH_MAX - config.TECH_PENALTY * self.tech_retries)
        if self.state == State.DONE:
            if not self.code_skipped:
                total += max(config.CODE_FLOOR, config.CODE_MAX - config.CODE_PENALTY * self.code_retries)
        return total

    def step_breakdown(self) -> dict[str, int]:
        bf = (
            0 if self.bf_skipped
            else max(config.BF_FLOOR, config.BF_MAX - config.BF_PENALTY * self.bf_retries)
            if self.state in (State.TECHNIQUE, State.CODE, State.DONE)
            else 0
        )
        tech = (
            0 if self.tech_skipped
            else max(config.TECH_FLOOR, config.TECH_MAX - config.TECH_PENALTY * self.tech_retries)
            if self.state in (State.CODE, State.DONE)
            else 0
        )
        code = (
            0 if self.code_skipped
            else max(config.CODE_FLOOR, config.CODE_MAX - config.CODE_PENALTY * self.code_retries)
            if self.state == State.DONE
            else 0
        )
        return {"brute_force": bf, "technique": tech, "code": code}
