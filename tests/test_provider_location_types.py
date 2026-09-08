from flight_bot.config import Settings
from flight_bot.models import WatchSlot
from flight_bot.providers import NaverFlightsSSEProvider


async def test_provider_uses_persisted_city_types_instead_of_reinferring(monkeypatch):
    captured = {}

    def fake_query_round_trip(origin, destination, depart_date, return_date, **kwargs):
        captured.update(kwargs)
        return (
            [
                {
                    "price": 450400,
                    "outbound_airline": "TEST",
                    "return_airline": "TEST",
                    "outbound_flight": "TA1",
                    "return_flight": "TA2",
                    "times": ["10:00", "12:00", "15:00", "17:00"],
                }
            ],
            {},
            [],
            None,
        )

    monkeypatch.setattr("flight_bot.providers.query_round_trip", fake_query_round_trip)
    provider = NaverFlightsSSEProvider(
        Settings(_env_file=None, naver_min_request_interval_seconds=0)
    )
    slot = WatchSlot(
        id=1,
        owner_platform="telegram",
        owner_id="group-a",
        origin="SEL",
        destination="TYO",
        depart_date="2026-09-22",
        return_date="2026-09-24",
        nonstop=True,
        checked_bag=0,
        enabled=True,
        target_price=500000,
        origin_type="city",
        destination_type="city",
    )

    offer = await provider.search(slot)

    assert captured["origin_type"] == "city"
    assert captured["destination_type"] == "city"
    assert offer.raw["origin_type"] == "city"
    assert offer.raw["destination_type"] == "city"
