import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://leetcode.com/graphql/"
_QUERY = """
query questionOfToday {
  activeDailyCodingChallengeQuestion {
    date
    link
    question {
      title
      titleSlug
      difficulty
      content
    }
  }
}
"""
_HEADERS = {
    "User-Agent": "LeetBot/1.0 (Discord coding-challenge bot)",
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
}


@dataclass
class DailyProblem:
    title: str
    slug: str
    difficulty: str
    url: str
    content_html: str


async def fetch_daily() -> DailyProblem:
    """Fetch today's LeetCode daily challenge. Raises on HTTP/network errors."""
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        async with session.post(GRAPHQL_URL, json={"query": _QUERY}) as resp:
            resp.raise_for_status()
            payload = await resp.json()

    if "errors" in payload:
        raise RuntimeError(f"LeetCode GraphQL error: {payload['errors']}")

    q = payload["data"]["activeDailyCodingChallengeQuestion"]
    question = q["question"]
    url = f"https://leetcode.com{q['link']}"

    logger.info("Fetched daily challenge: %s (%s)", question["title"], question["difficulty"])
    return DailyProblem(
        title=question["title"],
        slug=question["titleSlug"],
        difficulty=question["difficulty"],
        url=url,
        content_html=question["content"] or "",
    )


if __name__ == "__main__":
    import asyncio

    async def _smoke() -> None:
        problem = await fetch_daily()
        print(f"Title:      {problem.title}")
        print(f"Difficulty: {problem.difficulty}")
        print(f"URL:        {problem.url}")
        print(f"Content:    {problem.content_html[:200]}...")

    asyncio.run(_smoke())
