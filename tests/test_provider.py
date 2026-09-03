from flight_bot.config import Settings
from flight_bot.models import WatchSlot
from flight_bot.providers import GoogleFlightsPlaywrightProvider, parse_krw_price


def slot(**overrides):
    data = dict(id=1, owner_platform="test", owner_id="1", origin="CJJ", destination="TPE",
                depart_date="2026-09-18", return_date="2026-09-20", nonstop=False,
                checked_bag=0, enabled=True, target_price=350000)
    data.update(overrides)
    return WatchSlot(**data)


def test_parse_krw_price():
    assert parse_krw_price("₩337,079 round trip") == 337079
    assert parse_krw_price("337,079 South Korean won") == 337079
    assert parse_krw_price("no price") is None


def test_query_builder_is_injectable():
    seen = []
    def builder(value):
        seen.append(value)
        return "https://example.test/search?tfs=fake&curr=KRW"
    provider = GoogleFlightsPlaywrightProvider(Settings(), query_builder=builder)
    value = slot()
    assert provider.build_search_url(value).endswith("curr=KRW")
    assert seen == [value]
