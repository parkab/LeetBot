import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return val


def _optional(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


DISCORD_TOKEN: str = _require("DISCORD_TOKEN")
DISCORD_GUILD_ID: int = int(_require("DISCORD_GUILD_ID"))
DAILY_CHANNEL_ID: int = int(_require("DAILY_CHANNEL_ID"))
GEMINI_API_KEY: str = _require("GEMINI_API_KEY")
BOT_OWNER_ID: int = int(_require("BOT_OWNER_ID"))

GEMINI_MODEL: str = _optional("GEMINI_MODEL", "gemini-2.5-flash-lite")
DAILY_POST_HOUR_UTC: int = int(_optional("DAILY_POST_HOUR_UTC", "13"))
TIMEZONE: str = _optional("TIMEZONE", "America/New_York")
DB_PATH: str = _optional("DB_PATH", "leetbot.db")  # Fly sets /data/leetbot.db via env

_derp = os.environ.get("DERPSHRINES_USER_ID", "").strip()
DERPSHRINES_USER_ID: int | None = int(_derp) if _derp else None

# Point values — one source of truth
BF_MAX = 15
BF_PENALTY = 3
BF_FLOOR = 0

TECH_MAX = 25
TECH_PENALTY = 5
TECH_FLOOR = 0

CODE_MAX = 60
CODE_PENALTY = 10
CODE_FLOOR = 10
