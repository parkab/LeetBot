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
