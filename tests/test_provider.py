import pytest

from flight_bot.config import Settings
from flight_bot.models import WatchSlot
from flight_bot.providers import NaverFlightsSSEProvider, ProviderError


def slot(**overrides):
    data = dict(
        id=1,
        owner_platform="test",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        nonstop=True,
        checked_bag=0,
        enabled=True,
        target_price=350000,
    )
    data.update(overrides)
    return WatchSlot(**data)


def _row(index: int, price: int) -> dict:
    return {
        "price": price,
        "times": ["23:40", "01:10", "13:15", "16:40"],
        "outbound_flight": f"ZE{780 + index}",
        "return_flight": f"RF{320 + index}",
        "outbound_airline_code": "ZE",
        "return_airline_code": "RF",
        "outbound_airline": "이스타항공",
        "return_airline": "에어로케이",
        "nonstop": True,
    }


def test_default_provider_policy_is_naver_direct_round_trip_top_five():
    settings = Settings(_env_file=None)
    provider = NaverFlightsSSEProvider(settings)
    assert provider.name == "naver-flights-sse"
    assert provider.accepted_for_alerts is True
    assert settings.alert_nonstop_only is True
    assert settings.alert_max_offers == 5
    assert settings.require_verified_alerts is False


@pytest.mark.asyncio
async def test_provider_maps_ranked_sse_rows_to_offer(monkeypatch):
    rows = [_row(i, 319620 + i * 10000) for i in range(6)]

    def fake_query(*args, **kwargs):
        return (
            rows,
            {
                "advertised_lowest_direct": 319620,
                "sse_event_count": 20,
                "itinerary_count": 12,
                "fare_mapping_count": 6,
                "http_status": 201,
                "content_type": "text/event-stream",
            },
            "data: {}",
            {"status": {"isCompleted": True}},
        )

    monkeypatch.setattr("flight_bot.providers.query_round_trip", fake_query)
    provider = NaverFlightsSSEProvider(
        Settings(_env_file=None, alert_max_offers=5, naver_min_request_interval_seconds=0)
    )
    offer = await provider.search(slot())

    assert offer.total_price == 319620
    assert offer.observed_price == 319620
    assert offer.outbound_flight == "ZE780"
    assert offer.inbound_flight == "RF320"
    assert offer.airline == "이스타항공 + 에어로케이"
    assert offer.nonstop is True
    assert offer.verification_status == "naver_sse_round_trip_fare"
    assert len(offer.display_offers or []) == 5
    assert "flight.naver.com/flights/international" in (offer.result_url or "")
    assert offer.raw["sse_event_count"] == 20


@pytest.mark.asyncio
async def test_provider_wraps_api_failure(monkeypatch):
    def fake_query(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("flight_bot.providers.query_round_trip", fake_query)
    provider = NaverFlightsSSEProvider(
        Settings(_env_file=None, naver_min_request_interval_seconds=0)
    )
    with pytest.raises(ProviderError, match="Naver Flights SSE search failed"):
        await provider.search(slot())
