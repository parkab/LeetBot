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

# Fetch a single problem's full statement by its title slug.
_QUESTION_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    title
    titleSlug
    difficulty
    content
  }
}
"""

# Fetch every question in a public "problem list" (favorite) by its list slug.
_LIST_QUERY = """
query favoriteQuestionList($favoriteSlug: String!, $limit: Int, $skip: Int, $version: String) {
  favoriteQuestionList(
    favoriteSlug: $favoriteSlug
    limit: $limit
    skip: $skip
    version: $version
  ) {
    questions {
      title
      titleSlug
      difficulty
      paidOnly
    }
    totalLength
    hasMore
  }
}
"""


@dataclass
class DailyProblem:
    """A LeetCode problem with its full statement. Used for daily and practice alike."""
    title: str
    slug: str
    difficulty: str
    url: str
    content_html: str


@dataclass
class ListedProblem:
    """A problem list entry — metadata only, no statement body."""
    title: str
    slug: str
    difficulty: str   # normalised to "Easy" | "Medium" | "Hard"
    paid_only: bool

    @property
    def url(self) -> str:
        return f"https://leetcode.com/problems/{self.slug}/"


async def _graphql(query: str, variables: dict, referer: str = "https://leetcode.com") -> dict:
    """POST a GraphQL query to LeetCode. Raises on HTTP/network/GraphQL errors."""
    headers = {**_HEADERS, "Referer": referer}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            GRAPHQL_URL, json={"query": query, "variables": variables}
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()

    if "errors" in payload:
        raise RuntimeError(f"LeetCode GraphQL error: {payload['errors']}")
    return payload["data"]


async def fetch_daily() -> DailyProblem:
    """Fetch today's LeetCode daily challenge. Raises on HTTP/network errors."""
    data = await _graphql(_QUERY, {})

    q = data["activeDailyCodingChallengeQuestion"]
    question = q["question"]
    url = f"https://leetcode.com{q['link']}"

    logger.info("Fetched daily challenge: %s (%s)", question["title"], question["difficulty"])
    return DailyProblem(
        title=question["title"],
        slug=question["titleSlug"],
        difficulty=normalize_difficulty(question["difficulty"]),
        url=url,
        content_html=question["content"] or "",
    )


_DIFFICULTY_NAMES = {"EASY": "Easy", "MEDIUM": "Medium", "HARD": "Hard"}


def normalize_difficulty(raw: str) -> str:
    """LeetCode returns 'EASY' from list queries but 'Easy' from question queries."""
    return _DIFFICULTY_NAMES.get((raw or "").upper(), (raw or "").title())


async def fetch_question(title_slug: str) -> DailyProblem:
    """Fetch a single problem's full statement by title slug. Raises on error."""
    data = await _graphql(
        _QUESTION_QUERY,
        {"titleSlug": title_slug},
        referer=f"https://leetcode.com/problems/{title_slug}/",
    )
    question = data.get("question")
    if not question:
        raise RuntimeError(f"LeetCode returned no question for slug {title_slug!r}")

    logger.info("Fetched question: %s (%s)", question["title"], question["difficulty"])
    return DailyProblem(
        title=question["title"],
        slug=question["titleSlug"],
        difficulty=normalize_difficulty(question["difficulty"]),
        url=f"https://leetcode.com/problems/{question['titleSlug']}/",
        content_html=question["content"] or "",
    )


async def fetch_problem_list(favorite_slug: str) -> list[ListedProblem]:
    """Fetch every question in a public LeetCode problem list. Raises on error."""
    problems: list[ListedProblem] = []
    skip = 0
    page_size = 100

    while True:
        data = await _graphql(
            _LIST_QUERY,
            {
                "favoriteSlug": favorite_slug,
                "limit": page_size,
                "skip": skip,
                "version": "v2",
            },
            referer=f"https://leetcode.com/problem-list/{favorite_slug}/",
        )
        node = data.get("favoriteQuestionList")
        if not node:
            raise RuntimeError(f"LeetCode returned no list for slug {favorite_slug!r}")

        for q in node["questions"]:
            problems.append(
                ListedProblem(
                    title=q["title"],
                    slug=q["titleSlug"],
                    difficulty=normalize_difficulty(q["difficulty"]),
                    paid_only=bool(q.get("paidOnly")),
                )
            )

        if not node.get("hasMore") or not node["questions"]:
            break
        skip += page_size

    logger.info("Fetched problem list %s: %d questions", favorite_slug, len(problems))
    return problems


if __name__ == "__main__":
    import asyncio

    async def _smoke() -> None:
        problem = await fetch_daily()
        print(f"Title:      {problem.title}")
        print(f"Difficulty: {problem.difficulty}")
        print(f"URL:        {problem.url}")
        print(f"Content:    {problem.content_html[:200]}...")

    asyncio.run(_smoke())
