from __future__ import annotations

import asyncio

import discord
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from .config import Settings
from .service import HELP, FlightService
from .telegram_ui import MAIN_KEYBOARD, handle_callback, handle_flow_text, show_slots, start_flow


class NotificationUnavailableError(RuntimeError):
    pass


class MultiNotifier:
    def __init__(self):
        self.telegram_app: Application | None = None
        self.discord_client: discord.Client | None = None

    async def send(self, platform: str, recipient_id: str, text: str) -> None:
        if platform == "telegram":
            if not self.telegram_app:
                raise NotificationUnavailableError("Telegram notifier is not connected")
            await self.telegram_app.bot.send_message(chat_id=int(recipient_id), text=text, disable_web_page_preview=True)
            return

        if platform == "discord":
            if not self.discord_client:
                raise NotificationUnavailableError("Discord notifier is not connected")
            channel = self.discord_client.get_channel(int(recipient_id))
            if channel is None:
                channel = await self.discord_client.fetch_channel(int(recipient_id))
            await channel.send(text)
            return

        if platform == "kakao":
            raise NotificationUnavailableError(
                "Kakao proactive notification is not configured (BizMessage/AlimTalk required)"
            )

        raise NotificationUnavailableError(f"Unsupported notification platform: {platform}")

    async def send_summary(self, platform: str, recipient_id: str, text: str, slot_ids: list[int]) -> None:
        """Send one compact daily report per user.

        Telegram gets two detail buttons per row. Tapping a button reuses the
        existing per-slot immediate search callback, so summary storage stays
        small and the user always sees a fresh TOP 5 result.
        """
        if platform != "telegram":
            await self.send(platform, recipient_id, text)
            return
        if not self.telegram_app:
            raise NotificationUnavailableError("Telegram notifier is not connected")
        buttons = [
            InlineKeyboardButton(f"#{slot_id} 상세", callback_data=f"slotcheck:{slot_id}")
            for slot_id in slot_ids
        ]
        rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
        markup = InlineKeyboardMarkup(rows) if rows else None
        await self.telegram_app.bot.send_message(
            chat_id=int(recipient_id),
            text=text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )


async def build_telegram(settings: Settings, service: FlightService, notifier: MultiNotifier):
    if not settings.telegram_bot_token:
        return None
    app = Application.builder().token(settings.telegram_bot_token).build()

    def allowed(update: Update) -> tuple[bool, str | None]:
        if not update.effective_chat:
            return False, None
        chat_id = str(update.effective_chat.id)
        if settings.telegram_chat_ids and chat_id not in settings.telegram_chat_ids:
            return False, chat_id
        return True, chat_id

    async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        ok, _chat_id = allowed(update)
        if not ok or not update.effective_message:
            return
        context.user_data.pop("flight_flow", None)
        await update.effective_message.reply_text(
            "✈️ 항공권 감시봇\n버튼으로 감시 등록·바로 검색·슬롯 관리를 할 수 있습니다.",
            reply_markup=MAIN_KEYBOARD,
        )

    async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        ok, _chat_id = allowed(update)
        if not ok or not update.effective_message:
            return
        await update.effective_message.reply_text(HELP, reply_markup=MAIN_KEYBOARD)

    async def flight_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        ok, chat_id = allowed(update)
        if not ok or not chat_id or not update.effective_message:
            return
        result = await service.command("telegram", chat_id, update.effective_message.text or "")
        await update.effective_message.reply_text(result, reply_markup=MAIN_KEYBOARD, disable_web_page_preview=True)

    async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        ok, chat_id = allowed(update)
        if not ok or not chat_id or not update.effective_message:
            return
        text = (update.effective_message.text or "").strip()

        if text == "➕ 감시 등록":
            await start_flow(update, context, "add")
            return
        if text == "🔎 바로 검색":
            await start_flow(update, context, "search")
            return
        if text == "📋 내 슬롯":
            await show_slots(update, service, chat_id)
            return
        if text in {"❓ 도움말", "/?", "도움말", "help"}:
            await update.effective_message.reply_text(HELP, reply_markup=MAIN_KEYBOARD)
            return
        if await handle_flow_text(update, context, service, chat_id, text):
            return

        result = await service.command("telegram", chat_id, text)
        await update.effective_message.reply_text(result, reply_markup=MAIN_KEYBOARD, disable_web_page_preview=True)

    async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        ok, chat_id = allowed(update)
        if not ok or not chat_id:
            if update.callback_query:
                await update.callback_query.answer("허용되지 않은 대화입니다.", show_alert=True)
            return
        await handle_callback(update, context, service, chat_id)

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("flight", flight_command_handler))
    # Telegram's normal command grammar does not include '?', so catch /? as text explicitly.
    app.add_handler(MessageHandler(filters.Regex(r"^/\?$"), help_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    await app.initialize()
    await app.bot.set_my_commands(
        [
            BotCommand("start", "메인 메뉴"),
            BotCommand("help", "도움말"),
            BotCommand("flight", "고급 명령어"),
        ]
    )
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
        if not (text.startswith("/flight") or text in {"/help", "/?", "help", "도움말"}):
            return
        result = await self.service.command("discord", channel_id, text)
        await message.channel.send(result)


async def start_discord(settings: Settings, service: FlightService, notifier: MultiNotifier):
    if not settings.discord_bot_token:
        return None
    client = DiscordBot(settings, service, notifier)
    asyncio.create_task(client.start(settings.discord_bot_token))
    return client
