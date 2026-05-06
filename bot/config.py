from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    telegram_token: str
    openai_api_key: str
    openai_model: str
    database_url: str
    roster_file: str
    tournament_weekdays: set[int]
    timezone: str
    discord_channel_id: int | None
    bot_language: str


    @staticmethod
    def from_env() -> "Settings":
        load_dotenv()

        weekdays_raw = os.getenv("TOURNAMENT_WEEKDAYS", "3,4,5")
        weekdays = {
            int(day.strip())
            for day in weekdays_raw.split(",")
            if day.strip().isdigit()
        }

        return Settings(
            discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./bot.db").strip(),
            roster_file=os.getenv("ROSTER_FILE", "./roster.sample.json").strip(),
            tournament_weekdays=weekdays or {3, 4, 5},
            timezone=os.getenv("TIMEZONE", "Europe/Moscow").strip(),
            discord_channel_id=int(ch) if (ch := os.getenv("DISCORD_CHANNEL_ID", "").strip()).isdigit() else None,
            bot_language=os.getenv("BOT_LANGUAGE", "en").strip().lower() or "en",
        )
