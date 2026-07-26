"""Curated LeetCode problem lists (grind75, pareto) with an in-memory TTL cache.

The lists are public LeetCode "favorites" and are fetched through the same GraphQL
endpoint as the daily challenge — no authentication required.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

from leetbot.leetcode import ListedProblem, fetch_problem_list

logger = logging.getLogger(__name__)

# Problem lists rarely change; re-fetch at most every 6 hours.
_CACHE_TTL_SECONDS = 6 * 60 * 60

DIFFICULTIES = ("Easy", "Medium", "Hard")


@dataclass(frozen=True)
class ProblemList:
    key: str            # command-facing name, e.g. "grind75"
    favorite_slug: str  # LeetCode problem-list hash
    label: str          # human-readable name for embeds
    emoji: str
    url: str


PROBLEM_LISTS: dict[str, ProblemList] = {
    "grind75": ProblemList(
        key="grind75",
        favorite_slug="rab78cw1",
        label="Grind 75",
        emoji="💪",
        url="https://leetcode.com/problem-list/rab78cw1/",
    ),
    "pareto": ProblemList(
        key="pareto",
        favorite_slug="2yvx2ha6",
        label="Pareto Set",
        emoji="📈",
        url="https://leetcode.com/problem-list/2yvx2ha6/",
    ),
}

# key -> (fetched_at_monotonic, problems)
_cache: dict[str, tuple[float, list[ListedProblem]]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def get_problems(list_key: str, force: bool = False) -> list[ListedProblem]:
    """Return all free problems in a list, using the cache when it is still fresh.

    Falls back to a stale cache entry if a refetch fails, so a LeetCode blip does
    not take the practice commands down.
    """
    spec = PROBLEM_LISTS[list_key]

    async with _lock_for(list_key):
        cached = _cache.get(list_key)
        if not force and cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

        try:
            problems = await fetch_problem_list(spec.favorite_slug)
        except Exception as exc:
            if cached is not None:
                logger.warning(
                    "Refetch of %s failed (%s) — serving stale cache of %d problems",
                    list_key, exc, len(cached[1]),
                )
                return cached[1]
            raise

        # Paid-only problems can't be read by most users; drop them.
        free = [p for p in problems if not p.paid_only]
        _cache[list_key] = (time.monotonic(), free)
        logger.info("Cached problem list %s: %d free problems", list_key, len(free))
        return free


def difficulty_counts(problems: list[ListedProblem]) -> dict[str, int]:
    """Count problems per difficulty, preserving Easy/Medium/Hard order."""
    counts = {d: 0 for d in DIFFICULTIES}
    for p in problems:
        if p.difficulty in counts:
            counts[p.difficulty] += 1
    return counts


def available_difficulties(problems: list[ListedProblem]) -> list[str]:
    """Difficulties that actually appear in this list (the pareto list has no Hard)."""
    counts = difficulty_counts(problems)
    return [d for d in DIFFICULTIES if counts[d] > 0]


def pick_problem(
    problems: list[ListedProblem],
    difficulty: Optional[str],
    exclude_slugs: set[str],
) -> tuple[Optional[ListedProblem], bool]:
    """Pick a random problem, preferring ones the user hasn't completed.

    `difficulty` of None means "any". Returns (problem, is_repeat). When every
    candidate has already been completed, falls back to a repeat rather than
    refusing to serve anything.
    """
    pool = [p for p in problems if difficulty is None or p.difficulty == difficulty]
    if not pool:
        return None, False

    fresh = [p for p in pool if p.slug not in exclude_slugs]
    if fresh:
        return random.choice(fresh), False
    return random.choice(pool), True
