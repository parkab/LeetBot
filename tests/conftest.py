"""Set required env vars before any module imports so config.py doesn't raise."""
import os
import tempfile

# Stub env vars — override in individual tests if needed.
os.environ.setdefault("DISCORD_TOKEN", "test_discord_token")
os.environ.setdefault("DISCORD_GUILD_ID", "111111111111111111")
os.environ.setdefault("DAILY_CHANNEL_ID", "222222222222222222")
os.environ.setdefault("GEMINI_API_KEY", "test_gemini_key")
os.environ.setdefault("BOT_OWNER_ID", "333333333333333333")
os.environ.setdefault("GEMINI_MODEL", "gemini-2.0-flash")
os.environ.setdefault("DAILY_POST_HOUR_UTC", "13")
os.environ.setdefault("TIMEZONE", "America/New_York")

# Use a temp file so each test run starts clean; monkeypatch per-test as needed.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_PATH", _tmp.name)
