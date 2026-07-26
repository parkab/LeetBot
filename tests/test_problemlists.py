import pytest

import leetbot.problemlists as pl
from leetbot.leetcode import ListedProblem


def _p(title: str, slug: str, difficulty: str, paid: bool = False) -> ListedProblem:
    return ListedProblem(title=title, slug=slug, difficulty=difficulty, paid_only=paid)


SAMPLE = [
    _p("Two Sum", "two-sum", "Easy"),
    _p("Valid Parens", "valid-parentheses", "Easy"),
    _p("LRU Cache", "lru-cache", "Medium"),
    _p("Course Schedule", "course-schedule", "Medium"),
    _p("Median Arrays", "median-of-two-sorted-arrays", "Hard"),
]

NO_HARD = [p for p in SAMPLE if p.difficulty != "Hard"]


@pytest.fixture(autouse=True)
def clear_cache():
    pl._cache.clear()
    yield
    pl._cache.clear()


# ── Registry ──────────────────────────────────────────────────────────────────

def test_both_lists_registered():
    assert set(pl.PROBLEM_LISTS) == {"grind75", "pareto"}


def test_list_slugs_match_the_source_urls():
    assert pl.PROBLEM_LISTS["grind75"].favorite_slug == "rab78cw1"
    assert pl.PROBLEM_LISTS["pareto"].favorite_slug == "2yvx2ha6"


# ── Difficulty helpers ────────────────────────────────────────────────────────

def test_difficulty_counts():
    assert pl.difficulty_counts(SAMPLE) == {"Easy": 2, "Medium": 2, "Hard": 1}


def test_difficulty_counts_includes_zero_entries():
    """A list with no Hard problems still reports Hard: 0 rather than omitting it."""
    assert pl.difficulty_counts(NO_HARD)["Hard"] == 0


def test_available_difficulties_ordered():
    assert pl.available_difficulties(SAMPLE) == ["Easy", "Medium", "Hard"]


def test_available_difficulties_omits_empty():
    """This is what trims the Hard button off the pareto picker."""
    assert pl.available_difficulties(NO_HARD) == ["Easy", "Medium"]


# ── Problem selection ─────────────────────────────────────────────────────────

def test_pick_respects_difficulty():
    problem, _ = pl.pick_problem(SAMPLE, "Hard", set())
    assert problem.slug == "median-of-two-sorted-arrays"


def test_pick_any_difficulty():
    problem, repeat = pl.pick_problem(SAMPLE, None, set())
    assert problem in SAMPLE
    assert repeat is False


def test_pick_excludes_completed():
    for _ in range(20):
        problem, repeat = pl.pick_problem(SAMPLE, "Easy", {"two-sum"})
        assert problem.slug == "valid-parentheses"
        assert repeat is False


def test_pick_returns_none_when_difficulty_absent():
    problem, repeat = pl.pick_problem(NO_HARD, "Hard", set())
    assert problem is None
    assert repeat is False


def test_pick_falls_back_to_repeat_when_all_completed():
    done = {p.slug for p in SAMPLE if p.difficulty == "Easy"}
    problem, repeat = pl.pick_problem(SAMPLE, "Easy", done)
    assert problem is not None
    assert problem.difficulty == "Easy"
    assert repeat is True


def test_pick_empty_pool_returns_none():
    problem, repeat = pl.pick_problem([], None, set())
    assert problem is None
    assert repeat is False


# ── Caching ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_problems_caches(monkeypatch):
    calls = []

    async def fake_fetch(slug):
        calls.append(slug)
        return SAMPLE

    monkeypatch.setattr(pl, "fetch_problem_list", fake_fetch)

    first = await pl.get_problems("grind75")
    second = await pl.get_problems("grind75")

    assert first == second
    assert len(calls) == 1  # second call served from cache


@pytest.mark.asyncio
async def test_get_problems_force_refetches(monkeypatch):
    calls = []

    async def fake_fetch(slug):
        calls.append(slug)
        return SAMPLE

    monkeypatch.setattr(pl, "fetch_problem_list", fake_fetch)

    await pl.get_problems("grind75")
    await pl.get_problems("grind75", force=True)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_get_problems_filters_paid_only(monkeypatch):
    async def fake_fetch(slug):
        return SAMPLE + [_p("Premium", "premium-problem", "Medium", paid=True)]

    monkeypatch.setattr(pl, "fetch_problem_list", fake_fetch)

    problems = await pl.get_problems("grind75")
    assert all(not p.paid_only for p in problems)
    assert "premium-problem" not in {p.slug for p in problems}


@pytest.mark.asyncio
async def test_get_problems_serves_stale_cache_on_fetch_failure(monkeypatch):
    state = {"fail": False}

    async def fake_fetch(slug):
        if state["fail"]:
            raise RuntimeError("leetcode is down")
        return SAMPLE

    monkeypatch.setattr(pl, "fetch_problem_list", fake_fetch)

    await pl.get_problems("grind75")
    state["fail"] = True
    problems = await pl.get_problems("grind75", force=True)

    assert len(problems) == len(SAMPLE)  # fell back to the cached copy


@pytest.mark.asyncio
async def test_get_problems_raises_when_no_cache_to_fall_back_on(monkeypatch):
    async def fake_fetch(slug):
        raise RuntimeError("leetcode is down")

    monkeypatch.setattr(pl, "fetch_problem_list", fake_fetch)

    with pytest.raises(RuntimeError):
        await pl.get_problems("grind75")
