from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


class FakeProvider:
    name = "fake"
    accepted_for_alerts = True

    def __init__(self, price: int):
        self.price = price
        self.calls = 0

    async def search(self, slot, *, verify_below_price=None):
        self.calls += 1
        return FlightOffer(
            provider=self.name,
            origin=slot.origin,
            destination=slot.destination,
            depart_date=slot.depart_date,
            return_date=slot.return_date,
            total_price=self.price,
            observed_price_value=self.price,
            currency="KRW",
            price_verified=False,
            verification_status="google_flights_displayed_round_trip",
            result_url="https://www.google.com/travel/flights/search?manual-test=1",
            display_offers=[
                {
                    "price": self.price,
                    "airline": "TEST AIR",
                    "times": ["10:00 AM", "12:00 PM"],
                    "nonstop": True,
                }
            ],
            fetched_at=datetime.now(timezone.utc),
        )


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send(self, platform, recipient_id, text):
        self.messages.append(text)


def make_service(tmp_path, price=300000):
    db = Database(str(tmp_path / "db.sqlite"))
    db.add_slot(
        platform="telegram",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        target_price=350000,
        nonstop=True,
        checked_bag=0,
    )
    service = FlightService(Settings(_env_file=None), db, provider=FakeProvider(price))
    notifier = FakeNotifier()
    service.set_notifier(notifier)
    return service, db, notifier


@pytest.mark.asyncio
async def test_manual_target_scan_consumes_one_shot_latch(tmp_path):
    service, db, notifier = make_service(tmp_path)

    await service.check_all(notify_target=True, notify_daily_summary=False)
    await service.check_all(notify_target=True, notify_daily_summary=False)

    assert len(notifier.messages) == 1
    assert notifier.messages[0].startswith("🔥 목표가 도달")
    assert db.get_slot(1).alert_state == "ALERTED"


@pytest.mark.asyncio
async def test_manual_daily_summary_does_not_consume_target_latch(tmp_path):
    service, db, notifier = make_service(tmp_path)

    await service.check_all(notify_target=False, notify_daily_summary=True)

    assert len(notifier.messages) == 1
    assert notifier.messages[0].startswith("📊 정기 가격 알림")
    assert db.get_slot(1).alert_state == "ARMED"

    await service.check_all(notify_target=True, notify_daily_summary=False)
    assert len(notifier.messages) == 2
    assert notifier.messages[1].startswith("🔥 목표가 도달")
