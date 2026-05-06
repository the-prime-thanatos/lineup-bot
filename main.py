from __future__ import annotations

import asyncio

from bot.config import Settings
from bot.platforms.discord_bot import DiscordAdapter
from bot.platforms.telegram_bot import TelegramAdapter
from bot.service import ClanBotService


async def run() -> None:
    settings = Settings.from_env()
    service = ClanBotService(settings)

    tasks = []

    if settings.discord_token:
        discord_bot = DiscordAdapter(service)
        tasks.append(asyncio.create_task(discord_bot.start_bot(settings.discord_token)))
    else:
        print("DISCORD_TOKEN is empty. Discord adapter is disabled.")

    if settings.telegram_token:
        telegram_bot = TelegramAdapter(service, settings.telegram_token)
        tasks.append(asyncio.create_task(telegram_bot.start_bot()))
    else:
        print("TELEGRAM_BOT_TOKEN is empty. Telegram adapter is disabled.")

    if not tasks:
        raise RuntimeError("No adapters enabled. Fill DISCORD_TOKEN and/or TELEGRAM_BOT_TOKEN.")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(run())
