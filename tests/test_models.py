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


def test_observed_and_verified_prices_are_distinct():
    value = offer(
        total_price=345000,
        observed_price_value=311811,
        booking_option_price=320000,
        verified_checkout_price=345000,
        price_verified=True,
        verification_status="external_checkout_final_total",
    )
    assert value.observed_price == 311811
    assert value.booking_option_price == 320000
    assert value.verified_price == 345000


def test_observed_price_falls_back_to_preserved_raw_value():
    value = offer(total_price=345000, price_verified=True, raw={"observed_price": 335906})
    assert value.observed_price == 335906
    assert value.verified_price == 345000


def test_unverified_offer_has_no_verified_price():
    value = offer(
        total_price=311811,
        observed_price_value=311811,
        booking_option_price=319000,
        price_verified=False,
    )
    assert value.observed_price == 311811
    assert value.verified_price is None
