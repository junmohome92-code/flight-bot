import pytest

from flight_bot.channels import MultiNotifier


class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


@pytest.mark.asyncio
async def test_telegram_summary_is_one_message_with_two_column_detail_buttons():
    notifier = MultiNotifier()
    notifier.telegram_app = FakeApp()

    await notifier.send_summary("telegram", "123", "daily", [1, 2, 3])

    assert len(notifier.telegram_app.bot.calls) == 1
    call = notifier.telegram_app.bot.calls[0]
    assert call["chat_id"] == 123
    assert call["text"] == "daily"
    markup = call["reply_markup"]
    assert len(markup.inline_keyboard) == 2
    assert [button.callback_data for button in markup.inline_keyboard[0]] == ["slotcheck:1", "slotcheck:2"]
    assert [button.callback_data for button in markup.inline_keyboard[1]] == ["slotcheck:3"]
