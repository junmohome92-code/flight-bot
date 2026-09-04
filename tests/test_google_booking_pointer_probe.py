from flight_bot.google_ui_contract import (
    choose_lowest_candidate,
    flight_card_is_specific,
    parse_krw_prices,
)


def candidate(price: int, row: str, seen: float = 100.0, ident: str = "x") -> dict:
    return {"id": ident, "price": price, "rowText": row, "seenAtMs": seen}


def departure_row(price: int = 335_906) -> str:
    return f"""
    11:40 PM – 1:10 AM+1
    Separate tickets booked together
    EASTAR JET
    2 hr 30 min
    CJJ–TPE
    Nonstop
    ₩{price:,}
    round trip
    """


def return_row_without_route(price: int = 340_000) -> str:
    return f"""
    2:20 PM – 5:45 PM
    EASTAR JET
    2 hr 25 min
    Nonstop
    ₩{price:,}
    round trip
    """


def test_won_aria_is_a_price_source():
    assert parse_krw_prices("335906 South Korean won") == [335906]
    assert parse_krw_prices("₩335,906") == [335906]


def test_local_departure_card_is_accepted():
    assert flight_card_is_specific(departure_row(), "CJJ", "TPE") is True


def test_search_results_container_is_rejected():
    text = """
    Flight search
    Round trip
    Filters
    All filters
    Search results
    Best
    Cheapest from ₩335,906
    Checking prices from multiple sources...
    Top departing flights
    11:40 PM – 1:10 AM+1
    EASTAR JET
    2 hr 30 min
    CJJ–TPE
    Nonstop
    ₩335,906 round trip
    """
    assert flight_card_is_specific(text, "CJJ", "TPE") is False


def test_return_card_may_omit_route_after_returning_page_is_confirmed():
    text = return_row_without_route()
    assert flight_card_is_specific(text, "TPE", "CJJ") is False
    assert flight_card_is_specific(text, "TPE", "CJJ", allow_missing_route=True) is True


def test_return_card_still_rejects_reverse_departure_route():
    text = "2:20 PM – 5:45 PM\nEASTAR JET\n2 hr 25 min\nCJJ–TPE\nNonstop\n₩340,000"
    assert flight_card_is_specific(text, "TPE", "CJJ", allow_missing_route=True) is False


def test_advertised_cheapest_blocks_expensive_stable_fallback():
    expensive = candidate(922_965, "5:20 PM – 10:25 AM+1\nKorean Air\n18 hr 5 min\nCJJ–TPE\n2 stops\n₩922,965")
    assert choose_lowest_candidate(
        [expensive], origin="CJJ", destination="TPE", advertised_price=335_906
    ) is None


def test_disappeared_cheapest_snapshot_beats_connected_expensive_row():
    # Selection is intentionally based on preserved snapshots; there is no
    # source.isConnected field or DOM liveness requirement in this policy.
    cheap = candidate(335_906, departure_row(335_906), seen=435.0, ident="cheap-disappeared")
    expensive = candidate(
        922_965,
        "5:20 PM – 10:25 AM+1\nKorean Air, Asiana Airlines\n18 hr 5 min\nCJJ–TPE\n2 stops\n₩922,965",
        seen=500.0,
        ident="expensive-stable",
    )
    chosen = choose_lowest_candidate(
        [expensive, cheap], origin="CJJ", destination="TPE", advertised_price=335_906
    )
    assert chosen is cheap


def test_unhinted_selection_still_chooses_lowest_captured_row():
    cheap = candidate(335_906, departure_row(335_906), ident="cheap")
    higher = candidate(415_400, departure_row(415_400), ident="higher")
    chosen = choose_lowest_candidate([higher, cheap], origin="CJJ", destination="TPE")
    assert chosen is cheap


def test_route_less_return_candidate_can_be_selected_in_return_phase():
    ret = candidate(340_000, return_row_without_route(), ident="return")
    chosen = choose_lowest_candidate(
        [ret],
        origin="TPE",
        destination="CJJ",
        allow_missing_route=True,
    )
    assert chosen is ret
