from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from leetbot.leetcode import DailyProblem, fetch_daily

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
