from datetime import datetime
from zoneinfo import ZoneInfo
import leetbot.config as config


def today_key() -> str:
    """Return the current day key as 'YYYY-MM-DD' in the configured timezone."""
    tz = ZoneInfo(config.TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m-%d")
