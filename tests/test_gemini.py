import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import leetbot.interview.gemini as gemini_module
from leetbot.interview.gemini import Verdict, grade_answer


def _mock_response(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


def _setup_client(mocker, response_text: str) -> AsyncMock:
    mock_gen = AsyncMock(return_value=_mock_response(response_text))
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_gen
    mocker.patch.object(gemini_module, "_client", mock_client)
    return mock_gen


# ── Happy path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_grade_answer_accept(mocker):
    payload = {"verdict": "accept", "feedback": "Great explanation!", "complexity_check": "O(n) ✓"}
    _setup_client(mocker, json.dumps(payload))

    result = await grade_answer("brute_force", "Two Sum", "problem text", "linear scan O(n^2)")
    assert result.verdict == "accept"
    assert result.accepted is True
    assert "Great" in result.feedback
    assert result.complexity_check == "O(n) ✓"


@pytest.mark.asyncio
async def test_grade_answer_reject(mocker):
    payload = {"verdict": "reject", "feedback": "Complexity is off.", "complexity_check": None}
    _setup_client(mocker, json.dumps(payload))

    result = await grade_answer("technique", "Two Sum", "problem text", "brute force again")
    assert result.verdict == "reject"
    assert result.accepted is False


@pytest.mark.asyncio
async def test_grade_answer_with_markdown_fence(mocker):
    """Gemini sometimes wraps JSON in a code fence despite instructions."""
    payload = {"verdict": "accept", "feedback": "Correct!", "complexity_check": None}
    raw = f"```json\n{json.dumps(payload)}\n```"
    _setup_client(mocker, raw)

    result = await grade_answer("code", "Two Sum", "problem", "def twoSum(): pass")
    assert result.verdict == "accept"


# ── Defensive JSON handling ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_grade_answer_invalid_json_falls_back(mocker):
    """First call returns garbage, retry also returns garbage → graceful fallback."""
    mock_gen = AsyncMock(return_value=_mock_response("this is not json"))
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_gen
    mocker.patch.object(gemini_module, "_client", mock_client)

    result = await grade_answer("brute_force", "X", "content", "answer")
    assert result.verdict == "reject"
    assert "couldn't grade" in result.feedback.lower()
    assert mock_gen.call_count == 2  # original + retry


@pytest.mark.asyncio
async def test_grade_answer_valid_json_on_retry(mocker):
    """First call returns garbage, retry returns valid JSON."""
    good = {"verdict": "accept", "feedback": "Nice!", "complexity_check": None}
    mock_gen = AsyncMock(
        side_effect=[
            _mock_response("not json"),
            _mock_response(json.dumps(good)),
        ]
    )
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_gen
    mocker.patch.object(gemini_module, "_client", mock_client)

    result = await grade_answer("brute_force", "X", "content", "answer")
    assert result.verdict == "accept"
    assert mock_gen.call_count == 2


@pytest.mark.asyncio
async def test_grade_answer_missing_key_falls_back(mocker):
    """JSON is valid but missing required 'verdict' key."""
    _setup_client(mocker, json.dumps({"feedback": "oops", "complexity_check": None}))

    result = await grade_answer("technique", "X", "content", "answer")
    assert result.verdict == "reject"


# ── Verdict properties ────────────────────────────────────────────────────────

def test_verdict_accepted_true():
    v = Verdict(verdict="accept", feedback="good", complexity_check=None)
    assert v.accepted is True


def test_verdict_accepted_false():
    v = Verdict(verdict="reject", feedback="no", complexity_check=None)
    assert v.accepted is False
