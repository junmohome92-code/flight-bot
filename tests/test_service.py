import asyncio
from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


class FakeProvider:
    name = "fake"

    def __init__(self, prices, *, delay: float = 0.0, verified: bool = True):
        self.prices = list(prices)
        self.calls = []
        self.delay = delay
        self.verified = verified

    async def search(self, slot, *, verify_below_price=None):
        self.calls.append(verify_below_price)
        if self.delay:
            await asyncio.sleep(self.delay)
        price = self.prices.pop(0)
        return FlightOffer(
            provider=self.name,
            origin=slot.origin,
            destination=slot.destination,
            depart_date=slot.depart_date,
            return_date=slot.return_date,
            total_price=price,
            price_verified=self.verified,
            raw={"observed_price": price},
            fetched_at=datetime.now(timezone.utc),
        )


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send(self, platform, recipient_id, text):
        self.messages.append((platform, recipient_id, text))


def make_slot(db: Database):
    return db.add_slot(
        platform="telegram",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        target_price=350000,
        nonstop=False,
        checked_bag=0,
    )


@pytest.mark.asyncio
async def test_target_alert_latches_and_rearms(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([340000, 330000, 360000, 345000])
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    await service.check_slot(slot.id, notify_target=True)
    await service.check_slot(slot.id, notify_target=True)
    await service.check_slot(slot.id, notify_target=True)
    await service.check_slot(slot.id, notify_target=True)

    assert len(notifier.messages) == 2
    assert provider.calls == [350000, None, None, 350000]


@pytest.mark.asyncio
async def test_unverified_below_target_never_alerts_or_latches_when_required(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([330000], verified=False)
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    await service.check_slot(slot.id, notify_target=True)

    assert notifier.messages == []
    assert db.get_slot(slot.id).alert_state == "ARMED"
    assert db.get_slot(slot.id).last_observed_price == 330000


@pytest.mark.asyncio
async def test_overlapping_checks_cannot_duplicate_same_below_target_alert(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([340000, 339000], delay=0.02)
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    await asyncio.gather(
        service.check_slot(slot.id, notify_target=True),
        service.check_slot(slot.id, notify_target=True),
    )

    assert len(notifier.messages) == 1
    # The second check starts only after the first one latched ALERTED, so it
    # must not ask the provider for below-target verification again.
    assert provider.calls == [350000, None]


@pytest.mark.asyncio
async def test_target_command_rejects_missing_slot(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    service = FlightService(Settings(), db, provider=FakeProvider([]))
    result = await service.command("telegram", "1", "/flight target 1 330000")
    assert "찾을 수 없습니다" in result


@pytest.mark.asyncio
async def test_add_rejects_return_date_before_departure(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    service = FlightService(Settings(), db, provider=FakeProvider([]))
    result = await service.command(
        "telegram",
        "1",
        "/flight add CJJ TPE 2026-09-20 2026-09-18 350000",
    )
    assert "귀국일" in result
