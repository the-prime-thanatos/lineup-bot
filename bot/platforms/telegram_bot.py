from __future__ import annotations

import asyncio
import io

from telegram import Update
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
        await update.message.reply_text(response)

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
