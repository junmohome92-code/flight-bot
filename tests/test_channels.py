import pytest

from flight_bot.channels import MultiNotifier, NotificationUnavailableError


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "discord", "kakao", "unknown"])
async def test_unavailable_notification_channel_fails_closed(platform):
    notifier = MultiNotifier()
    with pytest.raises(NotificationUnavailableError):
        await notifier.send(platform, "1", "test")
