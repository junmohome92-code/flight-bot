from __future__ import annotations

import asyncio

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


class _ConcurrentProvider:
    name = "fake-concurrent"
    accepted_for_alerts = True

    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.by_slot: dict[int, int] = {}
        self.max_by_slot: dict[int, int] = {}
        self.calls: list[int] = []

    async def search(self, slot, *, verify_below_price=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.by_slot[slot.id] = self.by_slot.get(slot.id, 0) + 1
        self.max_by_slot[slot.id] = max(self.max_by_slot.get(slot.id, 0), self.by_slot[slot.id])
        self.calls.append(slot.id)
        try:
            await asyncio.sleep(0.05)
            return FlightOffer(
                provider=self.name,
                origin=slot.origin,
                destination=slot.destination,
                depart_date=slot.depart_date,
                return_date=slot.return_date,
                total_price=400000 + slot.id,
                observed_price_value=400000 + slot.id,
                result_url=f"https://www.google.com/travel/flights/search?slot={slot.id}",
                display_offers=[{"price": 400000 + slot.id, "airline": "Test", "times": [], "nonstop": True}],
            )
        finally:
            self.by_slot[slot.id] -= 1
            self.active -= 1


def _service(tmp_path, count: int = 5):
    db = Database(str(tmp_path / "db.sqlite"), slot_limit=10)
    for index in range(count):
        db.add_slot(
            platform="telegram",
            owner_id="1",
            origin="CJJ",
            destination="TPE",
            depart_date="2026-09-18",
            return_date="2026-09-20",
            target_price=300000,
            nonstop=True,
            checked_bag=0,
        )
    provider = _ConcurrentProvider()
    settings = Settings(_env_file=None, search_concurrency=2, search_stagger_seconds=0)
    return FlightService(settings, db, provider=provider), provider


@pytest.mark.asyncio
async def test_all_slot_scan_never_exceeds_two_parallel_searches(tmp_path):
    service, provider = _service(tmp_path, count=5)

    assert await service.check_all(notify_target=False, notify_daily_summary=False) is True

    assert sorted(provider.calls) == [1, 2, 3, 4, 5]
    assert provider.max_active == 2
    assert service.active_searches == 0


@pytest.mark.asyncio
async def test_same_slot_is_serialized_even_when_global_limit_is_two(tmp_path):
    service, provider = _service(tmp_path, count=1)

    await asyncio.gather(
        service.check_slot(1),
        service.check_slot(1),
    )

    assert provider.max_by_slot[1] == 1
    assert provider.calls == [1, 1]
