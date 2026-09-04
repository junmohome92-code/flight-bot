from flight_bot.models import FlightOffer


def offer(**overrides):
    data = dict(
        provider="fake",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        total_price=340000,
    )
    data.update(overrides)
    return FlightOffer(**data)


def test_observed_price_prefers_preserved_row_value():
    value = offer(total_price=345000, price_verified=True, raw={"observed_price": 335906})
    assert value.observed_price == 335906
    assert value.verified_price == 345000


def test_unverified_offer_has_no_verified_price():
    value = offer(total_price=335906, price_verified=False, raw={"observed_price": 335906})
    assert value.observed_price == 335906
    assert value.verified_price is None
