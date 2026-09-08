from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


class LifecycleProvider:
    name = "fake-lifecycle"
    accepted_for_alerts = True

    def __init__(self, prices):
        self.prices = list(prices)

    async def search(self, slot, *, verify_below_price=None):
        price = self.prices.pop(0)
        return FlightOffer(
            provider=self.name,
            origin=slot.origin,
            destination=slot.destination,
            depart_date=slot.depart_date,
            return_date=slot.return_date,
            total_price=price,
            observed_price_value=price,
            currency="KRW",
            price_verified=False,
            verification_status="naver_sse_round_trip_fare",
            display_offers=[{"price": price, "times": [], "nonstop": True}],
            fetched_at=datetime.now(timezone.utc),
        )


class LifecycleNotifier:
    def __init__(self):
        self.messages = []

    async def send(self, platform, recipient_id, text):
        self.messages.append((platform, recipient_id, text))


@pytest.mark.asyncio
async def test_registration_baseline_then_one_target_alert_then_silence(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = db.add_slot(
        platform="telegram",
        owner_id="group-a",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        target_price=350000,
        nonstop=True,
        checked_bag=0,
    )
    provider = LifecycleProvider([340000, 339000, 330000])
    service = FlightService(Settings(_env_file=None), db, provider=provider)
    notifier = LifecycleNotifier()
    service.set_notifier(notifier)

    # Registration UI uses this exact mode for the immediate baseline lookup.
    baseline = await service.check_slot(slot.id, notify_target=False, notify_daily_summary=False)
    assert "340,000" in baseline
    assert notifier.messages == []
    assert db.get_slot(slot.id).alert_state == "ARMED"

    # First scheduled target-eligible scan alerts once.
    await service.check_slot(slot.id, notify_target=True, notify_daily_summary=False)
    assert len(notifier.messages) == 1
    assert notifier.messages[0][2].startswith("🔥 목표가 도달")
    assert db.get_slot(slot.id).alert_state == "ALERTED"

    # Later 2-hour scans keep observing but do not repeat the same target alert.
    await service.check_slot(slot.id, notify_target=True, notify_daily_summary=False)
    assert len(notifier.messages) == 1
    assert db.get_slot(slot.id).last_observed_price == 330000
