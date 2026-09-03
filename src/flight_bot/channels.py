from __future__ import annotations

import asyncio

import discord
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .config import Settings
from .service import FlightService


class MultiNotifier:
    def __init__(self):
        self.telegram_app: Application | None = None
        self.discord_client: discord.Client | None = None

    async def send(self, platform: str, recipient_id: str, text: str) -> None:
        if platform == "telegram" and self.telegram_app:
            await self.telegram_app.bot.send_message(chat_id=int(recipient_id), text=text)
            return
        if platform == "discord" and self.discord_client:
            channel = self.discord_client.get_channel(int(recipient_id)) or await self.discord_client.fetch_channel(int(recipient_id))
            await channel.send(text)
            return
        # Kakao proactive push requires a separate BizMessage/AlimTalk provider.
        print(f"[kakao-pending] recipient={recipient_id} {text}")


async def build_telegram(settings: Settings, service: FlightService, notifier: MultiNotifier):
    if not settings.telegram_bot_token:
        return None
    app = Application.builder().token(settings.telegram_bot_token).build()

    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_chat or not update.effective_message:
            return
        chat_id = str(update.effective_chat.id)
        if settings.telegram_chat_ids and chat_id not in settings.telegram_chat_ids:
            return
        text = update.effective_message.text or ""
        result = await service.command("telegram", chat_id, text)
        await update.effective_message.reply_text(result)

    app.add_handler(CommandHandler("start", handle))
    app.add_handler(CommandHandler("help", handle))
    app.add_handler(CommandHandler("flight", handle))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    notifier.telegram_app = app
    return app


class DiscordBot(discord.Client):
    def __init__(self, settings: Settings, service: FlightService, notifier: MultiNotifier):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.service = service
        self.notifier = notifier

    async def on_ready(self):
        self.notifier.discord_client = self
        print(f"Discord connected: {self.user}")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        channel_id = str(message.channel.id)
        if self.settings.discord_channel_ids and channel_id not in self.settings.discord_channel_ids:
            return
        text = message.content.strip()
        if not (text.startswith("/flight") or text in {"/help", "help", "도움말"}):
            return
        result = await self.service.command("discord", channel_id, text)
        await message.channel.send(result)


async def start_discord(settings: Settings, service: FlightService, notifier: MultiNotifier):
    if not settings.discord_bot_token:
        return None
    client = DiscordBot(settings, service, notifier)
    asyncio.create_task(client.start(settings.discord_bot_token))
    return client
