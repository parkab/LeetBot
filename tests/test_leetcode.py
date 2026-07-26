from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from leetbot.leetcode import (
    DailyProblem,
    ListedProblem,
    fetch_daily,
    fetch_problem_list,
    fetch_question,
    normalize_difficulty,
)

_SAMPLE_PAYLOAD = {
    "data": {
        "activeDailyCodingChallengeQuestion": {
            "date": "2024-01-01",
            "link": "/problems/two-sum/",
            "question": {
                "title": "Two Sum",
                "titleSlug": "two-sum",
                "difficulty": "Easy",
                "content": "<p>Given an array of integers...</p>",
            },
        }
    }
}


def _make_mock_session(payload: dict, status: int = 200):
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=payload)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_post = MagicMock(return_value=mock_resp)

    mock_session = MagicMock()
    mock_session.post = mock_post
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return mock_session


@pytest.mark.asyncio
async def test_fetch_daily_parses_response():
    mock_session = _make_mock_session(_SAMPLE_PAYLOAD)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        problem = await fetch_daily()

    assert isinstance(problem, DailyProblem)
    assert problem.title == "Two Sum"
    assert problem.slug == "two-sum"
    assert problem.difficulty == "Easy"
    assert problem.url == "https://leetcode.com/problems/two-sum/"
    assert "<p>" in problem.content_html


@pytest.mark.asyncio
async def test_fetch_daily_constructs_full_url():
    mock_session = _make_mock_session(_SAMPLE_PAYLOAD)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        problem = await fetch_daily()

    assert problem.url.startswith("https://leetcode.com")
    assert "/problems/two-sum/" in problem.url


@pytest.mark.asyncio
async def test_fetch_daily_raises_on_graphql_error():
    error_payload = {"errors": [{"message": "rate limited"}]}
    mock_session = _make_mock_session(error_payload)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(RuntimeError, match="GraphQL error"):
            await fetch_daily()


@pytest.mark.asyncio
async def test_fetch_daily_raises_on_http_error():
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock(side_effect=Exception("403 Forbidden"))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(Exception, match="403"):
            await fetch_daily()


@pytest.mark.asyncio
async def test_fetch_daily_handles_null_content():
    payload = {
        "data": {
            "activeDailyCodingChallengeQuestion": {
                "date": "2024-01-01",
                "link": "/problems/two-sum/",
                "question": {
                    "title": "Two Sum",
                    "titleSlug": "two-sum",
                    "difficulty": "Easy",
                    "content": None,
                },
            }
        }
    }
    mock_session = _make_mock_session(payload)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        problem = await fetch_daily()

    assert problem.content_html == ""


# ── Difficulty normalisation ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [("EASY", "Easy"), ("MEDIUM", "Medium"), ("HARD", "Hard"),
     ("Easy", "Easy"), ("Medium", "Medium")],
)
def test_normalize_difficulty(raw, expected):
    """List queries return EASY, question queries return Easy — unify them."""
    assert normalize_difficulty(raw) == expected


@pytest.mark.asyncio
async def test_fetch_daily_normalizes_screaming_difficulty():
    payload = {
        "data": {
            "activeDailyCodingChallengeQuestion": {
                "date": "2024-01-01",
                "link": "/problems/two-sum/",
                "question": {
                    "title": "Two Sum", "titleSlug": "two-sum",
                    "difficulty": "EASY", "content": "<p>x</p>",
                },
            }
        }
    }
    mock_session = _make_mock_session(payload)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        problem = await fetch_daily()
    assert problem.difficulty == "Easy"


# ── fetch_question ────────────────────────────────────────────────────────────

_QUESTION_PAYLOAD = {
    "data": {
        "question": {
            "title": "Valid Parentheses",
            "titleSlug": "valid-parentheses",
            "difficulty": "Easy",
            "content": "<p>Given a string s...</p>",
        }
    }
}


@pytest.mark.asyncio
async def test_fetch_question_parses_response():
    mock_session = _make_mock_session(_QUESTION_PAYLOAD)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        problem = await fetch_question("valid-parentheses")

    assert isinstance(problem, DailyProblem)
    assert problem.title == "Valid Parentheses"
    assert problem.slug == "valid-parentheses"
    assert problem.difficulty == "Easy"
    assert problem.url == "https://leetcode.com/problems/valid-parentheses/"


@pytest.mark.asyncio
async def test_fetch_question_raises_when_missing():
    mock_session = _make_mock_session({"data": {"question": None}})
    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(RuntimeError, match="no question"):
            await fetch_question("does-not-exist")


@pytest.mark.asyncio
async def test_fetch_question_handles_null_content():
    payload = {
        "data": {
            "question": {
                "title": "X", "titleSlug": "x", "difficulty": "Hard", "content": None,
            }
        }
    }
    mock_session = _make_mock_session(payload)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        problem = await fetch_question("x")
    assert problem.content_html == ""


# ── fetch_problem_list ────────────────────────────────────────────────────────

def _list_payload(questions, has_more=False, total=None):
    return {
        "data": {
            "favoriteQuestionList": {
                "questions": questions,
                "totalLength": total if total is not None else len(questions),
                "hasMore": has_more,
            }
        }
    }


_Q1 = {"title": "Two Sum", "titleSlug": "two-sum", "difficulty": "EASY", "paidOnly": False}
_Q2 = {"title": "LRU Cache", "titleSlug": "lru-cache", "difficulty": "MEDIUM", "paidOnly": True}


@pytest.mark.asyncio
async def test_fetch_problem_list_parses_and_normalizes():
    mock_session = _make_mock_session(_list_payload([_Q1, _Q2]))
    with patch("aiohttp.ClientSession", return_value=mock_session):
        problems = await fetch_problem_list("rab78cw1")

    assert len(problems) == 2
    assert all(isinstance(p, ListedProblem) for p in problems)
    assert problems[0].difficulty == "Easy"     # normalised from EASY
    assert problems[1].difficulty == "Medium"
    assert problems[1].paid_only is True


@pytest.mark.asyncio
async def test_listed_problem_url():
    problem = ListedProblem(title="Two Sum", slug="two-sum", difficulty="Easy", paid_only=False)
    assert problem.url == "https://leetcode.com/problems/two-sum/"


@pytest.mark.asyncio
async def test_fetch_problem_list_raises_on_missing_list():
    mock_session = _make_mock_session({"data": {"favoriteQuestionList": None}})
    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(RuntimeError, match="no list"):
            await fetch_problem_list("bogus")


@pytest.mark.asyncio
async def test_fetch_problem_list_stops_when_no_more_pages():
    """hasMore=False must terminate the loop after a single request."""
    mock_session = _make_mock_session(_list_payload([_Q1], has_more=False))
    with patch("aiohttp.ClientSession", return_value=mock_session):
        problems = await fetch_problem_list("rab78cw1")

    assert len(problems) == 1
    assert mock_session.post.call_count == 1
