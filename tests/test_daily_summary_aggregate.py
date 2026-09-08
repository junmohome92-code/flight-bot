from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


class PriceProvider:
    name = "fake"
    accepted_for_alerts = True

    def __init__(self, prices):
        self.prices = dict(prices)

    async def search(self, slot, *, verify_below_price=None):
        price = int(self.prices[slot.id])
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
            result_url="https://flight.naver.com/test",
            display_offers=[{"price": price, "times": [], "nonstop": True}],
            fetched_at=datetime.now(timezone.utc),
        )


class SummaryNotifier:
    def __init__(self):
        self.messages = []
        self.summaries = []

    async def send(self, platform, recipient_id, text):
        self.messages.append((platform, recipient_id, text))

    async def send_summary(self, platform, recipient_id, text, slot_ids):
        self.summaries.append((platform, recipient_id, text, list(slot_ids)))


def add_slot(db, owner_id, origin, destination, target=200000):
    return db.add_slot(
        platform="telegram",
        owner_id=owner_id,
        origin=origin,
        destination=destination,
        depart_date="2026-09-22",
        return_date="2026-09-24",
        target_price=target,
        nonstop=True,
        checked_bag=0,
    )


@pytest.mark.asyncio
async def test_daily_report_is_one_message_per_conversation_not_one_per_slot(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    one = add_slot(db, "owner-a", "CJJ", "TPE")
    two = add_slot(db, "owner-a", "ICN", "NRT")
    three = add_slot(db, "owner-a", "PUS", "FUK")
    four = add_slot(db, "owner-b", "SEL", "TYO")

    provider = PriceProvider({one.id: 330000, two.id: 300000, three.id: 250000, four.id: 410000})
    service = FlightService(Settings(_env_file=None), db, provider=provider)
    notifier = SummaryNotifier()
    service.set_notifier(notifier)

    # Seed previous observations without notifications.
    for slot_id in (one.id, two.id, three.id, four.id):
        await service.check_slot(slot_id, notify_target=False, notify_daily_summary=False)

    provider.prices.update({one.id: 318000, two.id: 305000, three.id: 250000, four.id: 400000})
    await service.check_all(notify_target=False, notify_daily_summary=True)

    assert notifier.messages == []
    assert len(notifier.summaries) == 2

    owner_a = next(item for item in notifier.summaries if item[1] == "owner-a")
    text = owner_a[2]
    assert owner_a[3] == [one.id, two.id, three.id]
    assert "활성 슬롯 3개" in text
    assert "#1 CJJ→TPE  318,000원  ▼12,000" in text
    assert "#2 ICN→NRT  305,000원  ▲5,000" in text
    assert "#3 PUS→FUK  250,000원  ─" in text

    owner_b = next(item for item in notifier.summaries if item[1] == "owner-b")
    assert owner_b[3] == [four.id]
    # Internal id is #4 here, but owner-b sees its own local slot #1.
    assert "#1 SEL→TYO" in owner_b[2]
    assert "#4 SEL→TYO" not in owner_b[2]


@pytest.mark.asyncio
async def test_paused_slots_are_omitted_from_daily_report(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    active = add_slot(db, "owner-a", "CJJ", "TPE")
    paused = add_slot(db, "owner-a", "ICN", "NRT")
    db.set_enabled(paused.id, False)
    provider = PriceProvider({active.id: 300000, paused.id: 200000})
    service = FlightService(Settings(_env_file=None), db, provider=provider)
    notifier = SummaryNotifier()
    service.set_notifier(notifier)

    await service.check_all(notify_target=False, notify_daily_summary=True)

    assert len(notifier.summaries) == 1
    assert notifier.summaries[0][3] == [active.id]
    assert "#2" not in notifier.summaries[0][2]
