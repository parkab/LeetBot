from __future__ import annotations

from typing import Optional

from leetbot.interview.session import InterviewSession


class SessionManager:
    """In-memory registry of active interview sessions.

    Keyed by (user_id, day_key) for lookups by the /giveup command, and by
    channel_id (thread or DM) for routing on_message events.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], InterviewSession] = {}
        self._by_channel: dict[int, InterviewSession] = {}

    def add(self, session: InterviewSession) -> None:
        self._by_key[(session.user_id, session.day_key)] = session
        if session.channel_id is not None:
            self._by_channel[session.channel_id] = session

    def register_channel(self, session: InterviewSession, channel_id: int) -> None:
        """Call after the thread/DM channel is created to enable message routing."""
        session.channel_id = channel_id
        self._by_channel[channel_id] = session

    def get_by_user_day(self, user_id: str, day_key: str) -> Optional[InterviewSession]:
        return self._by_key.get((user_id, day_key))

    def get_by_channel(self, channel_id: int) -> Optional[InterviewSession]:
        return self._by_channel.get(channel_id)

    def remove(self, session: InterviewSession) -> None:
        self._by_key.pop((session.user_id, session.day_key), None)
        if session.channel_id is not None:
            self._by_channel.pop(session.channel_id, None)

    def active_count(self) -> int:
        return len(self._by_key)
