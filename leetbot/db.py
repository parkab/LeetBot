import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import leetbot.config as config

logger = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    # Read DB_PATH at call time so tests can monkeypatch config.DB_PATH.
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS problems (
                day_key           TEXT PRIMARY KEY,
                title             TEXT NOT NULL,
                slug              TEXT NOT NULL,
                difficulty        TEXT NOT NULL,
                url               TEXT NOT NULL,
                content_html      TEXT NOT NULL,
                posted_at         TEXT NOT NULL,
                reference_solution TEXT,
                message_id        TEXT
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT NOT NULL,
                day_key       TEXT NOT NULL,
                points        INTEGER NOT NULL,
                bf_retries    INTEGER NOT NULL DEFAULT 0,
                tech_retries  INTEGER NOT NULL DEFAULT 0,
                code_retries  INTEGER NOT NULL DEFAULT 0,
                completed_at  TEXT NOT NULL,
                UNIQUE(user_id, day_key)
            );

            CREATE INDEX IF NOT EXISTS idx_attempts_day  ON attempts(day_key);
            CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);

            -- Practice problems pulled from curated lists (grind75 / pareto).
            -- Keyed by slug and shared across users, so statements and reference
            -- solutions are fetched/generated at most once each.
            CREATE TABLE IF NOT EXISTS practice_problems (
                slug               TEXT PRIMARY KEY,
                title              TEXT NOT NULL,
                difficulty         TEXT NOT NULL,
                url                TEXT NOT NULL,
                content_html       TEXT NOT NULL,
                reference_solution TEXT,
                fetched_at         TEXT NOT NULL
            );

            -- One scored row per user per problem, regardless of which list it
            -- came from (some problems appear in both).
            CREATE TABLE IF NOT EXISTS practice_attempts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT NOT NULL,
                list_name     TEXT NOT NULL,
                slug          TEXT NOT NULL,
                title         TEXT NOT NULL,
                difficulty    TEXT NOT NULL,
                points        INTEGER NOT NULL,
                bf_retries    INTEGER NOT NULL DEFAULT 0,
                tech_retries  INTEGER NOT NULL DEFAULT 0,
                code_retries  INTEGER NOT NULL DEFAULT 0,
                completed_at  TEXT NOT NULL,
                UNIQUE(user_id, slug)
            );

            CREATE INDEX IF NOT EXISTS idx_practice_user ON practice_attempts(user_id);
            CREATE INDEX IF NOT EXISTS idx_practice_list ON practice_attempts(list_name);
        """)
    logger.info("DB schema initialized at %s", config.DB_PATH)


# ── Problems ──────────────────────────────────────────────────────────────────

def get_problem(day_key: str) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM problems WHERE day_key = ?", (day_key,)
        ).fetchone()


def upsert_problem(
    day_key: str,
    title: str,
    slug: str,
    difficulty: str,
    url: str,
    content_html: str,
    posted_at: str,
    reference_solution: Optional[str] = None,
) -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO problems
                (day_key, title, slug, difficulty, url, content_html, posted_at, reference_solution)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (day_key, title, slug, difficulty, url, content_html, posted_at, reference_solution),
        )


def set_problem_message_id(day_key: str, message_id: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE problems SET message_id = ? WHERE day_key = ?",
            (message_id, day_key),
        )


def set_reference_solution(day_key: str, reference_solution: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE problems SET reference_solution = ? WHERE day_key = ?",
            (reference_solution, day_key),
        )


# ── Attempts ──────────────────────────────────────────────────────────────────

def record_attempt(
    user_id: str,
    day_key: str,
    points: int,
    bf_retries: int,
    tech_retries: int,
    code_retries: int,
) -> None:
    completed_at = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO attempts
                (user_id, day_key, points, bf_retries, tech_retries, code_retries, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, day_key, points, bf_retries, tech_retries, code_retries, completed_at),
        )


def delete_attempt(user_id: str, day_key: str) -> bool:
    """Delete a user's attempt for a given day. Returns True if a row was deleted."""
    with _get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM attempts WHERE user_id = ? AND day_key = ?",
            (user_id, day_key),
        )
        return cursor.rowcount > 0


def get_attempt(user_id: str, day_key: str) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM attempts WHERE user_id = ? AND day_key = ?",
            (user_id, day_key),
        ).fetchone()


# ── Leaderboards ──────────────────────────────────────────────────────────────

def get_daily_leaderboard(day_key: str) -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT user_id, points, completed_at
            FROM attempts
            WHERE day_key = ?
            ORDER BY points DESC, completed_at ASC
            LIMIT 10
            """,
            (day_key,),
        ).fetchall()


def get_alltime_leaderboard() -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT user_id, SUM(points) AS total_points, COUNT(*) AS days_played
            FROM attempts
            GROUP BY user_id
            ORDER BY total_points DESC
            LIMIT 10
            """
        ).fetchall()


def get_user_stats(user_id: str) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT
                COUNT(*)        AS days_played,
                COALESCE(SUM(points), 0)  AS total_points,
                COALESCE(AVG(points), 0)  AS avg_points
            FROM attempts
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()


# ── Practice problems ─────────────────────────────────────────────────────────

def get_practice_problem(slug: str) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM practice_problems WHERE slug = ?", (slug,)
        ).fetchone()


def upsert_practice_problem(
    slug: str,
    title: str,
    difficulty: str,
    url: str,
    content_html: str,
    reference_solution: Optional[str] = None,
) -> None:
    """Cache a problem statement. Never clobbers an existing reference solution."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO practice_problems
                (slug, title, difficulty, url, content_html, reference_solution, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title              = excluded.title,
                difficulty         = excluded.difficulty,
                url                = excluded.url,
                content_html       = excluded.content_html,
                reference_solution = COALESCE(practice_problems.reference_solution,
                                              excluded.reference_solution),
                fetched_at         = excluded.fetched_at
            """,
            (slug, title, difficulty, url, content_html, reference_solution, fetched_at),
        )


def set_practice_reference_solution(slug: str, reference_solution: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE practice_problems SET reference_solution = ? WHERE slug = ?",
            (reference_solution, slug),
        )


# ── Practice attempts ─────────────────────────────────────────────────────────

def record_practice_attempt(
    user_id: str,
    list_name: str,
    slug: str,
    title: str,
    difficulty: str,
    points: int,
    bf_retries: int,
    tech_retries: int,
    code_retries: int,
) -> bool:
    """Record a practice completion. Returns True if this became the user's best score.

    Re-solving a problem only overwrites the stored row when the new score is
    strictly higher, so the practice leaderboard reflects personal bests and
    cannot be farmed down by a lazy repeat.
    """
    completed_at = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO practice_attempts
                (user_id, list_name, slug, title, difficulty, points,
                 bf_retries, tech_retries, code_retries, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, slug) DO UPDATE SET
                list_name    = excluded.list_name,
                points       = excluded.points,
                bf_retries   = excluded.bf_retries,
                tech_retries = excluded.tech_retries,
                code_retries = excluded.code_retries,
                completed_at = excluded.completed_at
            WHERE excluded.points > practice_attempts.points
            """,
            (user_id, list_name, slug, title, difficulty, points,
             bf_retries, tech_retries, code_retries, completed_at),
        )
        return cursor.rowcount > 0


def get_practice_attempt(user_id: str, slug: str) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM practice_attempts WHERE user_id = ? AND slug = ?",
            (user_id, slug),
        ).fetchone()


def get_completed_practice_slugs(user_id: str) -> set[str]:
    """Slugs the user has already completed — used to avoid serving repeats."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT slug FROM practice_attempts WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {row["slug"] for row in rows}


def delete_practice_attempts(user_id: str) -> int:
    """Wipe a user's practice history. Returns the number of rows deleted."""
    with _get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM practice_attempts WHERE user_id = ?", (user_id,)
        )
        return cursor.rowcount


def get_practice_leaderboard() -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT user_id,
                   SUM(points) AS total_points,
                   COUNT(*)    AS problems_solved
            FROM practice_attempts
            GROUP BY user_id
            ORDER BY total_points DESC, problems_solved DESC
            LIMIT 10
            """
        ).fetchall()


def get_practice_stats(user_id: str) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT
                COUNT(*)                 AS problems_solved,
                COALESCE(SUM(points), 0) AS total_points,
                COALESCE(AVG(points), 0) AS avg_points
            FROM practice_attempts
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
