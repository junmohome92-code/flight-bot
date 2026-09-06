from flight_bot.google_ui_contract import choose_lowest_candidate, flight_card_is_specific


def compact_departure(price: int = 311_578) -> str:
    return (
        "Other departing flights\n"
        "11:40 PM – 1:10 AM\n"
        "EASTAR JET\n"
        "2 hr 30 min\n"
        "Nonstop\n"
        f"₩{price:,}\n"
        "round trip"
    )


def test_fixed_route_context_accepts_compact_card_without_route_token():
    text = compact_departure()
    assert flight_card_is_specific(
        text,
        "CJJ",
        "TPE",
        allow_missing_route=True,
    ) is True

    candidate = {
        "id": "route-token-free",
        "phase": "departure",
        "price": 311_578,
        "rowText": text,
        "seenAtMs": 1200.0,
    }
    assert choose_lowest_candidate(
        [candidate],
        origin="CJJ",
        destination="TPE",
        advertised_price=311_578,
        allow_missing_route=True,
    ) is candidate


def test_explicit_reverse_route_is_still_rejected():
    text = compact_departure() + "\nTPE-CJJ"
    assert flight_card_is_specific(
        text,
        "CJJ",
        "TPE",
        allow_missing_route=True,
    ) is False


def test_page_wide_search_container_is_still_rejected():
    text = "Flight search\nSearch results\nAll filters\n" + compact_departure()
    assert flight_card_is_specific(
        text,
        "CJJ",
        "TPE",
        allow_missing_route=True,
    ) is False
