from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

import leetbot.config as config
from leetbot.interview.prompts import (
    REFERENCE_SOLUTION_PROMPT,
    build_explain_prompt,
    build_grade_prompt,
    build_hint_prompt,
    build_step_solution_prompt,
    build_system_prompt,
)

logger = logging.getLogger(__name__)

# Lazy-initialised so tests can patch config before the client is built.
_client = None


def _extract_retry_delay(exc: Exception) -> Optional[int]:
    """Return the suggested retry delay in seconds if exc is a 429, else None."""
    msg = str(exc)
    if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
        return None
    # The API embeds retryDelay as e.g. "Please retry in 45.09s" or retryDelay: '45s'
    import re
    match = re.search(r"retry[^\d]*(\d+)", msg, re.IGNORECASE)
    return int(match.group(1)) if match else 60  # safe default


def _get_client():
    global _client
    if _client is None:
        from google import genai  # type: ignore[import]

        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


@dataclass
class Verdict:
    verdict: str          # "accept" | "reject"
    feedback: str
    complexity_check: Optional[str]

    @property
    def accepted(self) -> bool:
        return self.verdict == "accept"


async def grade_answer(
    step: str,
    problem_title: str,
    problem_content: str,
    user_answer: str,
    reference_solution: Optional[str] = None,
) -> Verdict:
    """Send user answer to Gemini for grading. Always returns a Verdict — never raises."""
    system = build_system_prompt()
    prompt = build_grade_prompt(step, problem_title, problem_content, user_answer, reference_solution)
    client = _get_client()

    for attempt in range(2):
        extra = "\n\nIMPORTANT: Respond with valid JSON ONLY. No prose, no markdown fences." if attempt else ""
        # Embed system prompt in content — avoids systemInstruction/responseMimeType
        # which are v1beta-only fields and fail on the v1 endpoint.
        combined = f"{system}{extra}\n\n{prompt}"
        try:
            response = await client.aio.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=combined,
            )
            raw = response.text.strip()
            # Strip accidental markdown fences
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            return Verdict(
                verdict=data["verdict"],
                feedback=data["feedback"],
                complexity_check=data.get("complexity_check"),
            )
        except Exception as exc:
            retry_secs = _extract_retry_delay(exc)
            if retry_secs is not None:
                # Rate limit — no point retrying immediately; surface it to the user
                logger.warning("Gemini rate limited (429), retry in %ds: %s", retry_secs, exc)
                return Verdict(
                    verdict="rate_limited",
                    feedback=(
                        f"⏳ Gemini is rate-limited right now. "
                        f"Please try again in **{retry_secs} seconds**."
                    ),
                    complexity_check=None,
                )
            if attempt == 0:
                logger.warning("Gemini grading attempt 1 failed (%s), retrying", exc)
                continue
            logger.error("Gemini grading failed after retry: %s", exc)

    return Verdict(
        verdict="reject",
        feedback="Couldn't grade that response — try rephrasing or simplifying your answer.",
        complexity_check=None,
    )


async def get_hint(
    step: str,
    hint_number: int,
    problem_title: str,
    problem_content: str,
    previous_answers: list[str],
) -> str:
    """Return a progressively detailed hint for the current step. Never raises."""
    prompt = build_hint_prompt(step, hint_number, problem_title, problem_content, previous_answers)
    client = _get_client()
    try:
        response = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as exc:
        logger.error("Hint generation failed: %s", exc)
        return "Hint unavailable right now — try again in a moment."


async def generate_step_solution(
    step: str,
    problem_title: str,
    problem_content: str,
) -> str:
    """Generate a plain-English solution explanation for a skipped step. Never raises."""
    prompt = build_step_solution_prompt(step, problem_title, problem_content)
    client = _get_client()
    try:
        response = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as exc:
        logger.error("Step solution generation failed: %s", exc)
        return "Solution explanation unavailable — check the LeetCode editorial."


async def explain_solution(
    question: str,
    problem_title: str,
    problem_content: str,
    reference_solution: str,
) -> str:
    """Answer a free-form follow-up question about a problem and its solution. Never raises."""
    prompt = build_explain_prompt(question, problem_title, problem_content, reference_solution)
    client = _get_client()
    try:
        response = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as exc:
        logger.error("Explanation generation failed: %s", exc)
        return "Explanation unavailable right now — try again in a moment."


if __name__ == "__main__":
    import asyncio

    async def _smoke() -> None:
        print(f"Model : {config.GEMINI_MODEL}")
        print("Sending test grading request...")
        result = await grade_answer(
            step="brute_force",
            problem_title="Two Sum",
            problem_content="Given an array of integers nums and an integer target, return indices of the two numbers that add up to target.",
            user_answer="Use two nested loops to check every pair. Time: O(n^2), Space: O(1).",
        )
        print(f"Verdict  : {result.verdict}")
        print(f"Feedback : {result.feedback}")
        print(f"Complexity: {result.complexity_check}")

    asyncio.run(_smoke())


async def generate_reference_solution(problem_title: str, problem_content: str) -> str:
    """Generate and return an optimal Python reference solution via Gemini."""
    prompt = REFERENCE_SOLUTION_PROMPT.format(
        title=problem_title,
        content=problem_content[:3000],
    )
    client = _get_client()
    try:
        response = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as exc:
        logger.error("Failed to generate reference solution: %s", exc)
        return "# Reference solution unavailable"
