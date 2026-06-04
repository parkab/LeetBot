import asyncio
import logging

import leetbot.config as config  # noqa: F401 — validates env vars on import
import leetbot.db as db
from leetbot.bot import LeetBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    db.init_schema()

    bot = LeetBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
