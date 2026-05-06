from __future__ import annotations

import io

import discord

from bot.service import ClanBotService


class DiscordAdapter(discord.Client):
    def __init__(self, service: ClanBotService) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.service = service

    async def on_ready(self) -> None:
        print(f"Discord connected as {self.user}")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        lowered = message.content.strip().lower()
        if lowered in {
            "admin roster template",
            "/admin roster template",
            "!admin roster template",
            "admin roster download",
            "/admin roster download",
            "!admin roster download",
        }:
            payload = self.service.roster_template_json().encode("utf-8")
            file = discord.File(io.BytesIO(payload), filename="roster.template.json")
            await message.channel.send("Roster template file:", file=file)
            return

        if lowered in {
            "admin roster export",
            "/admin roster export",
            "!admin roster export",
            "admin roster dump",
            "/admin roster dump",
            "!admin roster dump",
        }:
            payload = self.service.roster_export_json().encode("utf-8")
            file = discord.File(io.BytesIO(payload), filename="roster.export.json")
            await message.channel.send("Current roster export:", file=file)
            return

        attachment_name: str | None = None
        attachment_text: str | None = None
        if message.attachments:
            candidate = message.attachments[0]
            filename = (candidate.filename or "").lower()
            content_type = (candidate.content_type or "").lower()
            if filename.endswith(".json") or "json" in content_type or filename.endswith(".txt"):
                raw = await candidate.read()
                attachment_name = candidate.filename
                attachment_text = raw.decode("utf-8", errors="ignore")

        response = self.service.handle_message_discord(
            channel_id=message.channel.id,
            text=message.content,
            user_id=str(message.author.id),
            username=message.author.display_name,
            message_id=str(message.id),
            attachment_name=attachment_name,
            attachment_text=attachment_text,
        )
        if response:
            await message.channel.send(response)

    async def start_bot(self, token: str) -> None:
        await self.start(token)
