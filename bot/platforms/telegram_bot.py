from __future__ import annotations

import asyncio
import html
import io
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from bot.service import ClanBotService


class TelegramAdapter:
    def __init__(self, service: ClanBotService, token: str) -> None:
        self.service = service
        self.app = Application.builder().token(token).build()
        self.app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, self.on_message))

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        text = update.message.text or update.message.caption or ""
        lowered = text.strip().lower()
        if lowered in {
            "admin roster template",
            "/admin roster template",
            "!admin roster template",
            "admin roster download",
            "/admin roster download",
            "!admin roster download",
        }:
            payload = self.service.roster_template_json().encode("utf-8")
            stream = io.BytesIO(payload)
            stream.name = "roster.template.json"
            await update.message.reply_document(document=stream, caption="Roster template file")
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
            stream = io.BytesIO(payload)
            stream.name = "roster.export.json"
            await update.message.reply_document(document=stream, caption="Current roster export")
            return

        attachment_name: str | None = None
        attachment_text: str | None = None

        if update.message.document:
            filename = (update.message.document.file_name or "").lower()
            mime_type = (update.message.document.mime_type or "").lower()
            if filename.endswith(".json") or "json" in mime_type or filename.endswith(".txt"):
                file = await context.bot.get_file(update.message.document.file_id)
                raw = await file.download_as_bytearray()
                attachment_name = update.message.document.file_name
                attachment_text = bytes(raw).decode("utf-8", errors="ignore")

        if not text and not attachment_text:
            return

        user = update.effective_user
        response = self.service.handle_message_event(
            source="telegram",
            text=text,
            user_id=str(user.id) if user else None,
            username=(user.username or user.full_name) if user else None,
            message_id=str(update.message.message_id),
            attachment_name=attachment_name,
            attachment_text=attachment_text,
        )
        formatted = self._format_response_html(response)
        try:
            await update.message.reply_text(formatted, parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text(response)

    @classmethod
    def _format_response_html(cls, text: str) -> str:
        lines: list[str] = []
        first_content = True
        previous_blank = False

        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                if not previous_blank:
                    lines.append("")
                previous_blank = True
                continue

            previous_blank = False

            if cls._is_separator_line(stripped):
                continue

            if first_content:
                lines.append(cls._format_heading_html(stripped))
                first_content = False
                continue

            if cls._is_section_heading(stripped):
                lines.append(cls._format_heading_html(stripped))
                continue

            if stripped.startswith("- "):
                lines.append(cls._format_list_item(stripped[2:]))
                continue

            if stripped.startswith("! "):
                lines.append(f"⚠️ {cls._format_inline_html(stripped[2:])}")
                continue

            if stripped.startswith("  ") and ":" in stripped:
                lines.append(f"    {cls._format_key_value_html(stripped)}")
                continue

            lines.append(cls._format_key_value_html(stripped))

        return "\n".join(lines)

    @staticmethod
    def _is_separator_line(text: str) -> bool:
        return bool(text) and all(ch in "-━" for ch in text)

    @staticmethod
    def _is_section_heading(text: str) -> bool:
        if text.startswith("**") and text.endswith("**"):
            return False
        if text.startswith(("•", "-", "!")):
            return False
        if "`" in text or ":" in text:
            return False
        return len(text) <= 32

    @classmethod
    def _format_list_item(cls, text: str) -> str:
        return f"• {cls._format_key_value_html(text)}"

    @classmethod
    def _format_heading_html(cls, text: str) -> str:
        inline = cls._format_inline_html(text)
        if inline.startswith("<b>") and inline.endswith("</b>"):
            return inline
        return f"<b>{inline}</b>"

    @classmethod
    def _format_key_value_html(cls, text: str) -> str:
        if ":" not in text:
            return cls._format_inline_html(text)

        key, value = text.split(":", 1)
        if not key.strip() or not value.strip():
            return cls._format_inline_html(text)

        return f"<b>{cls._format_inline_html(key.strip())}:</b> {cls._format_inline_html(value.strip())}"

    @staticmethod
    def _format_inline_html(text: str) -> str:
        parts = re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", text)
        rendered: list[str] = []
        for part in parts:
            if not part:
                continue
            if part.startswith("`") and part.endswith("`") and len(part) >= 2:
                rendered.append(f"<code>{html.escape(part[1:-1])}</code>")
                continue
            if part.startswith("**") and part.endswith("**") and len(part) >= 4:
                rendered.append(f"<b>{html.escape(part[2:-2])}</b>")
                continue
            rendered.append(html.escape(part))
        return "".join(rendered)

    async def start_bot(self) -> None:
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        try:
            await asyncio.Future()
        finally:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
