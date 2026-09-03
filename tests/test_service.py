from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


class FakeProvider:
    name = "fake"
    def __init__(self, prices):
        self.prices = list(prices); self.calls = []
    async def search(self, slot, *, verify_below_price=None):
        self.calls.append(verify_below_price)
        price = self.prices.pop(0)
        return FlightOffer(provider=self.name, origin=slot.origin, destination=slot.destination,
                           depart_date=slot.depart_date, return_date=slot.return_date,
                           total_price=price, price_verified=True, raw={"observed_price": price},
                           fetched_at=datetime.now(timezone.utc))


class FakeNotifier:
    def __init__(self): self.messages = []
    async def send(self, platform, recipient_id, text): self.messages.append((platform, recipient_id, text))


@pytest.mark.asyncio
async def test_target_alert_latches_and_rearms(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = db.add_slot(platform="telegram", owner_id="1", origin="CJJ", destination="TPE",
                       depart_date="2026-09-18", return_date="2026-09-20", target_price=350000,
                       nonstop=False, checked_bag=0)
    provider = FakeProvider([340000, 330000, 360000, 345000])
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier(); service.set_notifier(notifier)
    await service.check_slot(slot.id, notify_target=True)
    await service.check_slot(slot.id, notify_target=True)
    await service.check_slot(slot.id, notify_target=True)
    await service.check_slot(slot.id, notify_target=True)
    assert len(notifier.messages) == 2
    assert provider.calls == [350000, None, None, 350000]
