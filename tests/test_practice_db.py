import pytest

import leetbot.config as config
import leetbot.db as db


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch, tmp_path):
    path = str(tmp_path / "practice.db")
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_schema()
    return path


def _record(user="u1", slug="two-sum", points=100, list_name="grind75"):
    return db.record_practice_attempt(
        user_id=user, list_name=list_name, slug=slug, title="Two Sum",
        difficulty="Easy", points=points, bf_retries=0, tech_retries=0, code_retries=0,
    )


# ── Schema ────────────────────────────────────────────────────────────────────

def test_practice_tables_exist(fresh_db):
    import sqlite3

    conn = sqlite3.connect(fresh_db)
    tables = {
        r[0] for r in
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert "practice_problems" in tables
    assert "practice_attempts" in tables


# ── Problem cache ─────────────────────────────────────────────────────────────

def test_upsert_and_get_practice_problem():
    db.upsert_practice_problem(
        "two-sum", "Two Sum", "Easy",
        "https://leetcode.com/problems/two-sum/", "<p>body</p>",
    )
    row = db.get_practice_problem("two-sum")
    assert row["title"] == "Two Sum"
    assert row["difficulty"] == "Easy"
    assert row["content_html"] == "<p>body</p>"


def test_get_missing_practice_problem_returns_none():
    assert db.get_practice_problem("nope") is None


def test_upsert_preserves_existing_reference_solution():
    """Re-caching the statement must not wipe a generated reference solution."""
    db.upsert_practice_problem("two-sum", "Two Sum", "Easy", "url", "<p>a</p>")
    db.set_practice_reference_solution("two-sum", "def twoSum(): pass")

    db.upsert_practice_problem("two-sum", "Two Sum", "Easy", "url", "<p>updated</p>")

    row = db.get_practice_problem("two-sum")
    assert row["reference_solution"] == "def twoSum(): pass"
    assert row["content_html"] == "<p>updated</p>"


# ── Attempts ──────────────────────────────────────────────────────────────────

def test_record_practice_attempt_returns_true_on_insert():
    assert _record(points=80) is True


def test_get_practice_attempt():
    _record(points=80)
    row = db.get_practice_attempt("u1", "two-sum")
    assert row["points"] == 80
    assert row["list_name"] == "grind75"


def test_higher_score_overwrites():
    _record(points=60)
    assert _record(points=90) is True
    assert db.get_practice_attempt("u1", "two-sum")["points"] == 90


def test_lower_score_is_ignored():
    _record(points=90)
    assert _record(points=40) is False
    assert db.get_practice_attempt("u1", "two-sum")["points"] == 90


def test_equal_score_is_not_an_improvement():
    _record(points=70)
    assert _record(points=70) is False


def test_same_problem_from_other_list_still_one_row():
    """Two Sum is in both lists — it must not be scored twice."""
    _record(points=50, list_name="grind75")
    _record(points=80, list_name="pareto")

    rows = db.get_practice_leaderboard()
    assert len(rows) == 1
    assert rows[0]["problems_solved"] == 1
    assert rows[0]["total_points"] == 80


# ── Completed slugs ───────────────────────────────────────────────────────────

def test_completed_slugs_empty_for_new_user():
    assert db.get_completed_practice_slugs("nobody") == set()


def test_completed_slugs_returns_only_that_user():
    _record(user="u1", slug="two-sum")
    _record(user="u1", slug="lru-cache")
    _record(user="u2", slug="valid-parentheses")

    assert db.get_completed_practice_slugs("u1") == {"two-sum", "lru-cache"}
    assert db.get_completed_practice_slugs("u2") == {"valid-parentheses"}


def test_delete_practice_attempts():
    _record(user="u1", slug="two-sum")
    _record(user="u1", slug="lru-cache")

    assert db.delete_practice_attempts("u1") == 2
    assert db.get_completed_practice_slugs("u1") == set()


# ── Leaderboard / stats ───────────────────────────────────────────────────────

def test_practice_leaderboard_orders_by_points():
    _record(user="u1", slug="two-sum", points=50)
    _record(user="u2", slug="two-sum", points=95)
    _record(user="u3", slug="two-sum", points=70)

    rows = db.get_practice_leaderboard()
    assert [r["user_id"] for r in rows] == ["u2", "u3", "u1"]


def test_practice_leaderboard_sums_across_problems():
    _record(user="u1", slug="two-sum", points=50)
    _record(user="u1", slug="lru-cache", points=45)

    rows = db.get_practice_leaderboard()
    assert rows[0]["total_points"] == 95
    assert rows[0]["problems_solved"] == 2


def test_practice_leaderboard_empty():
    assert db.get_practice_leaderboard() == []


def test_practice_stats():
    _record(user="u1", slug="two-sum", points=100)
    _record(user="u1", slug="lru-cache", points=50)

    stats = db.get_practice_stats("u1")
    assert stats["problems_solved"] == 2
    assert stats["total_points"] == 150
    assert stats["avg_points"] == 75


def test_practice_stats_for_unknown_user_is_zeroed():
    stats = db.get_practice_stats("nobody")
    assert stats["problems_solved"] == 0
    assert stats["total_points"] == 0


def test_practice_attempts_do_not_touch_daily_tables():
    """Practice scoring must stay out of the daily leaderboard."""
    _record(user="u1", points=100)
    assert db.get_daily_leaderboard("2026-01-01") == []
    assert db.get_alltime_leaderboard() == []
