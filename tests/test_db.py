import os
import tempfile

import pytest

import leetbot.config as config
import leetbot.db as db


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch, tmp_path):
    """Each test gets its own empty SQLite file."""
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_schema()
    return path


# ── Schema ────────────────────────────────────────────────────────────────────

def test_init_schema_creates_tables(tmp_path, monkeypatch):
    import sqlite3

    path = str(tmp_path / "schema_test.db")
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_schema()

    conn = sqlite3.connect(path)
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "problems" in tables
    assert "attempts" in tables
    conn.close()


def test_init_schema_idempotent():
    # Running twice should not raise
    db.init_schema()
    db.init_schema()


# ── Problems ──────────────────────────────────────────────────────────────────

def test_upsert_and_get_problem():
    db.upsert_problem(
        day_key="2024-01-01",
        title="Two Sum",
        slug="two-sum",
        difficulty="Easy",
        url="https://leetcode.com/problems/two-sum/",
        content_html="<p>Given an array...</p>",
        posted_at="2024-01-01T13:00:00+00:00",
    )
    row = db.get_problem("2024-01-01")
    assert row is not None
    assert row["title"] == "Two Sum"
    assert row["difficulty"] == "Easy"
    assert row["reference_solution"] is None


def test_get_problem_missing_returns_none():
    assert db.get_problem("9999-99-99") is None


def test_upsert_problem_with_reference_solution():
    db.upsert_problem(
        day_key="2024-01-02",
        title="Add Two Numbers",
        slug="add-two-numbers",
        difficulty="Medium",
        url="https://leetcode.com/problems/add-two-numbers/",
        content_html="<p>...</p>",
        posted_at="2024-01-02T13:00:00+00:00",
        reference_solution="def addTwoNumbers(l1, l2): ...",
    )
    row = db.get_problem("2024-01-02")
    assert row["reference_solution"] == "def addTwoNumbers(l1, l2): ..."


def test_set_problem_message_id():
    db.upsert_problem("2024-01-03", "X", "x", "Hard", "https://x.com", "<p></p>", "2024-01-03T00:00:00+00:00")
    db.set_problem_message_id("2024-01-03", "999888777666555444")
    row = db.get_problem("2024-01-03")
    assert row["message_id"] == "999888777666555444"


def test_set_reference_solution():
    db.upsert_problem("2024-01-04", "Y", "y", "Easy", "https://y.com", "<p></p>", "2024-01-04T00:00:00+00:00")
    db.set_reference_solution("2024-01-04", "def solution(): pass")
    row = db.get_problem("2024-01-04")
    assert row["reference_solution"] == "def solution(): pass"


# ── Attempts ──────────────────────────────────────────────────────────────────

def test_record_and_get_attempt():
    db.record_attempt("user123", "2024-01-01", 85, bf_retries=0, tech_retries=1, code_retries=0)
    row = db.get_attempt("user123", "2024-01-01")
    assert row is not None
    assert row["points"] == 85
    assert row["tech_retries"] == 1


def test_get_attempt_missing_returns_none():
    assert db.get_attempt("ghost", "2024-01-01") is None


def test_record_attempt_upserts_on_conflict():
    db.record_attempt("user123", "2024-01-01", 50, 2, 3, 4)
    db.record_attempt("user123", "2024-01-01", 70, 0, 1, 2)
    row = db.get_attempt("user123", "2024-01-01")
    assert row["points"] == 70  # second write wins


# ── Leaderboards ──────────────────────────────────────────────────────────────

def test_daily_leaderboard_order():
    db.record_attempt("alice", "2024-02-01", 90, 0, 0, 0)
    db.record_attempt("bob", "2024-02-01", 70, 1, 1, 1)
    db.record_attempt("carol", "2024-02-01", 90, 0, 0, 1)

    rows = db.get_daily_leaderboard("2024-02-01")
    assert len(rows) == 3
    # alice and carol both 90pts; alice should be first (earlier completed_at)
    assert rows[0]["user_id"] in ("alice", "carol")
    assert rows[2]["user_id"] == "bob"


def test_daily_leaderboard_empty():
    rows = db.get_daily_leaderboard("2024-03-01")
    assert rows == []


def test_alltime_leaderboard():
    db.record_attempt("alice", "2024-02-01", 90, 0, 0, 0)
    db.record_attempt("alice", "2024-02-02", 80, 0, 0, 0)
    db.record_attempt("bob", "2024-02-01", 100, 0, 0, 0)

    rows = db.get_alltime_leaderboard()
    assert rows[0]["user_id"] == "alice"  # 170 pts
    assert rows[0]["total_points"] == 170
    assert rows[1]["user_id"] == "bob"    # 100 pts


def test_user_stats():
    db.record_attempt("dave", "2024-02-01", 60, 1, 0, 2)
    db.record_attempt("dave", "2024-02-02", 80, 0, 0, 0)
    row = db.get_user_stats("dave")
    assert row["days_played"] == 2
    assert row["total_points"] == 140
    assert abs(row["avg_points"] - 70.0) < 0.01


def test_user_stats_no_attempts():
    row = db.get_user_stats("nobody")
    assert row["days_played"] == 0
    assert row["total_points"] == 0
