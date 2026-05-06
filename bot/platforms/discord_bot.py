from __future__ import annotations

import io

import discord

from bot.service import ClanBotService


def _split_discord_message(text: str, limit: int = 2000) -> list[str]:
    daily_chunks = _split_weekly_report_by_day(text, limit=limit)
    if daily_chunks is not None:
        return daily_chunks

    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit

        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            split_at = limit
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


def _split_weekly_report_by_day(text: str, limit: int = 2000) -> list[str] | None:
    lines = text.splitlines()
    if len(lines) < 3:
        return None

    header_lines: list[str] = []
    day_blocks: list[list[str]] = []
    current_block: list[str] | None = None

    for line in lines:
        if _is_weekly_day_heading(line):
            if current_block:
                day_blocks.append(current_block)
            current_block = [line]
            continue

        if current_block is None:
            header_lines.append(line)
            continue

        current_block.append(line)

    if current_block:
        day_blocks.append(current_block)

    if not day_blocks:
        return None

    header = "\n".join(line for line in header_lines if line.strip()).strip()
    chunks: list[str] = []
    for index, block in enumerate(day_blocks):
        block_text = "\n".join(block).strip()
        if index == 0 and header:
            block_text = f"{header}\n\n{block_text}"
        if len(block_text) <= limit:
            chunks.append(block_text)
            continue
        chunks.extend(_split_long_block(block_text, limit=limit))

    return chunks


def _is_weekly_day_heading(line: str) -> bool:
    return line.startswith("**") and line.endswith("**") and any(
        marker in line for marker in ("[OK]", "[WARN]", "[OFF]")
    )


def _split_long_block(text: str, limit: int = 2000) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            split_at = limit
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


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
            for chunk in _split_discord_message(response):
                await message.channel.send(chunk)

    async def start_bot(self, token: str) -> None:
        await self.start(token)
