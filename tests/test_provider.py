import pytest

from flight_bot.config import Settings
from flight_bot.models import WatchSlot
from flight_bot.providers import GoogleFlightsPlaywrightProvider, parse_all_krw_prices, parse_krw_price


def slot(**overrides):
    data = dict(
        id=1,
        owner_platform="test",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        nonstop=False,
        checked_bag=0,
        enabled=True,
        target_price=350000,
    )
    data.update(overrides)
    return WatchSlot(**data)


def test_parse_krw_price():
    assert parse_krw_price("₩311,811 round trip") == 311811
    assert parse_krw_price("311,811 South Korean won") == 311811
    assert parse_krw_price("no price") is None


def test_parse_all_prices_deduplicates_symbol_and_aria_forms():
    assert parse_all_krw_prices("311,811 South Korean won / ₩311,811 / ₩415,400") == [311811, 415400]


def test_query_builder_is_injectable():
    seen = []

    def builder(value):
        seen.append(value)
        return "https://example.test/search?tfs=fake&curr=KRW"

    provider = GoogleFlightsPlaywrightProvider(Settings(), query_builder=builder)
    value = slot()
    assert provider.build_search_url(value).endswith("curr=KRW")
    assert seen == [value]


def test_legacy_provider_is_hard_disabled_for_alerts():
    provider = GoogleFlightsPlaywrightProvider(Settings(), query_builder=lambda _: "https://example.test")
    assert provider.accepted_for_alerts is False
    assert "legacy-unverified" in provider.name


@pytest.mark.asyncio
async def test_provider_close_closes_reusable_browser_session():
    class FakeSession:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    session = FakeSession()
    provider = GoogleFlightsPlaywrightProvider(
        Settings(),
        query_builder=lambda _: "https://example.test",
        browser_session=session,
    )
    await provider.close()
    assert session.closed is True
