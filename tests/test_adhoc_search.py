from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


class FakeSearchProvider:
    name = "fake-search"
    accepted_for_alerts = True

    def __init__(self):
        self.slots = []

    async def search(self, slot, *, verify_below_price=None):
        self.slots.append(slot)
        return FlightOffer(
            provider=self.name,
            origin=slot.origin,
            destination=slot.destination,
            depart_date=slot.depart_date,
            return_date=slot.return_date,
            total_price=319620,
            observed_price_value=319620,
            result_url="https://flight.naver.com/flights/international/test",
            display_offers=[
                {
                    "price": 319620,
                    "outbound_airline": "이스타항공",
                    "return_airline": "에어로케이",
                    "outbound_flight": "ZE781",
                    "return_flight": "RF322",
                    "times": ["23:40", "01:10", "13:15", "16:40"],
                    "nonstop": True,
                }
            ],
            fetched_at=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_search_now_does_not_create_a_watch_slot(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    provider = FakeSearchProvider()
    service = FlightService(Settings(_env_file=None), db, provider=provider)

    result = await service.search_now("cjj", "tpe", "2026-09-18", "2026-09-20")

    assert "319,620KRW" in result
    assert "이스타항공 ZE781" in result
    assert "에어로케이 RF322" in result
    assert "목표가:" not in result
    assert db.list_slots() == []
    assert provider.slots[0].id == 0
    assert provider.slots[0].origin == "CJJ"
    assert provider.slots[0].destination == "TPE"


@pytest.mark.asyncio
async def test_search_command_stays_compatible_but_help_is_button_first(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    service = FlightService(Settings(_env_file=None), db, provider=FakeSearchProvider())

    result = await service.command("telegram", "1", "/flight search CJJ TPE 2026-09-18 2026-09-20")
    help_text = await service.command("telegram", "1", "/?")

    assert "319,620KRW" in result
    assert "바로 검색" in help_text
    assert "채팅방마다" in help_text
    assert "20개" in help_text
    assert "/flight search" not in help_text


@pytest.mark.asyncio
async def test_search_now_validates_round_trip_before_provider_call(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    provider = FakeSearchProvider()
    service = FlightService(Settings(_env_file=None), db, provider=provider)

    result = await service.search_now("CJJ", "TPE", "2026-09-20", "2026-09-18")

    assert "귀국일" in result
    assert provider.slots == []
