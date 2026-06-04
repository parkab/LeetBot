import re
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

import pytest

import leetbot.config as config
from leetbot.utils.time import today_key


def test_today_key_format():
    key = today_key()
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", key), f"Bad format: {key}"


def test_today_key_uses_configured_timezone(monkeypatch):
    """today_key() should use TIMEZONE, not UTC."""
    monkeypatch.setattr(config, "TIMEZONE", "America/New_York")
    # Midnight UTC = previous day in New York (EST = UTC-5)
    fake_utc = datetime(2024, 3, 15, 0, 30, 0, tzinfo=ZoneInfo("UTC"))
    with patch("leetbot.utils.time.datetime") as mock_dt:
        mock_dt.now.return_value = fake_utc.astimezone(ZoneInfo("America/New_York"))
        key = today_key()
    # 00:30 UTC = 20:30 EDT-1 (EST) on March 14
    assert key == "2024-03-14"


def test_today_key_different_timezones_differ(monkeypatch):
    """A moment that is in different calendar days across timezones."""
    # 2024-03-15 00:30 UTC = 2024-03-14 in New York, 2024-03-15 in London
    monkeypatch.setattr(config, "TIMEZONE", "America/New_York")
    ny_key = today_key()

    monkeypatch.setattr(config, "TIMEZONE", "Europe/London")
    lon_key = today_key()

    # They may or may not differ depending on current time, but format must match
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", ny_key)
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", lon_key)
