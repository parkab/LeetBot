from __future__ import annotations

from typing import Optional

from leetbot.interview.session import InterviewSession, PendingPractice


class SessionManager:
    """In-memory registry of active interview sessions.

    Keyed by (user_id, session_key) — where session_key is the day for daily
    sessions and the problem slug for practice sessions, so a user can hold a
    daily and a practice session at the same time — and by channel_id (thread or
    DM) for routing on_message events and button callbacks.

    Also tracks "pending" practice threads: a thread that has been opened but
    whose problem hasn't been chosen yet (the user is still picking a difficulty).
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], InterviewSession] = {}
        self._by_channel: dict[int, InterviewSession] = {}
        self._pending: dict[int, PendingPractice] = {}

    # ── Sessions ──────────────────────────────────────────────────────────────

    def add(self, session: InterviewSession) -> None:
        self._by_key[(session.user_id, session.session_key)] = session
        if session.channel_id is not None:
            self._by_channel[session.channel_id] = session

    def register_channel(self, session: InterviewSession, channel_id: int) -> None:
        """Call after the thread/DM channel is created to enable message routing."""
        session.channel_id = channel_id
        self._by_channel[channel_id] = session

    def rekey(self, session: InterviewSession, old_key: str) -> None:
        """Re-index a session whose session_key changed (practice reroll)."""
        self._by_key.pop((session.user_id, old_key), None)
        self._by_key[(session.user_id, session.session_key)] = session

    def get_by_user_key(self, user_id: str, session_key: str) -> Optional[InterviewSession]:
        return self._by_key.get((user_id, session_key))

    def get_by_user_day(self, user_id: str, day_key: str) -> Optional[InterviewSession]:
        """Daily sessions only — their session_key is the day key."""
        session = self._by_key.get((user_id, day_key))
        return session if session is not None and not session.is_practice else None

    def get_by_channel(self, channel_id: int) -> Optional[InterviewSession]:
        return self._by_channel.get(channel_id)

    def sessions_for_user(self, user_id: str) -> list[InterviewSession]:
        return [s for (uid, _), s in self._by_key.items() if uid == user_id]

    def remove(self, session: InterviewSession) -> None:
        self._by_key.pop((session.user_id, session.session_key), None)
        if session.channel_id is not None:
            self._by_channel.pop(session.channel_id, None)

    def active_count(self) -> int:
        return len(self._by_key)

    # ── Pending practice threads ──────────────────────────────────────────────

    def add_pending(self, pending: PendingPractice) -> None:
        self._pending[pending.channel_id] = pending

    def get_pending(self, channel_id: int) -> Optional[PendingPractice]:
        return self._pending.get(channel_id)

    def pending_for_user(self, user_id: str) -> Optional[PendingPractice]:
        for pending in self._pending.values():
            if pending.user_id == user_id:
                return pending
        return None

    def remove_pending(self, channel_id: int) -> None:
        self._pending.pop(channel_id, None)
