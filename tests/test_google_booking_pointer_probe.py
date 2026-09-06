from flight_bot.google_ui_contract import (
    MIN_RETURN_ADJUSTMENT,
    choose_lowest_candidate,
    departure_capture_ready,
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


def return_row(price: int = 0) -> str:
    return f"""
    2:20 PM – 5:45 PM
    EASTAR JET
    2 hr 25 min
    Nonstop
    +₩{price:,}
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


def test_advertised_cheapest_blocks_expensive_fallback():
    expensive = candidate(
        922_965,
        "5:20 PM – 10:25 AM+1\nKorean Air\n18 hr 5 min\nCJJ–TPE\n2 stops\n₩922,965",
    )
    assert choose_lowest_candidate(
        [expensive], origin="CJJ", destination="TPE", advertised_price=335_906
    ) is None


def test_disappeared_cheapest_snapshot_beats_stable_expensive_row():
    cheap = candidate(335_906, departure_row(335_906), seen=435.0, ident="cheap")
    expensive = candidate(
        922_965,
        "5:20 PM – 10:25 AM+1\nKorean Air\n18 hr 5 min\nCJJ–TPE\n2 stops\n₩922,965",
        seen=500.0,
        ident="expensive",
    )
    chosen = choose_lowest_candidate(
        [expensive, cheap], origin="CJJ", destination="TPE", advertised_price=335_906
    )
    assert chosen is cheap


def test_loading_single_row_is_not_ready_even_when_price_matches():
    assert departure_capture_ready(
        candidate_count=1,
        elapsed_ms=1800,
        advertised_stable_ms=800,
        loading=True,
        capture_window_ms=1500,
    ) is False


def test_loading_multiple_rows_can_be_ready_after_capture_and_debounce():
    assert departure_capture_ready(
        candidate_count=4,
        elapsed_ms=1800,
        advertised_stable_ms=500,
        loading=True,
        capture_window_ms=1500,
    ) is True


def test_finished_loading_allows_one_row_for_thin_route():
    assert departure_capture_ready(
        candidate_count=1,
        elapsed_ms=1800,
        advertised_stable_ms=500,
        loading=False,
        capture_window_ms=1500,
    ) is True


def test_return_adjustment_can_be_zero():
    assert parse_krw_prices("+₩0", min_price=MIN_RETURN_ADJUSTMENT) == [0]
    text = return_row(0)
    assert flight_card_is_specific(
        text,
        "TPE",
        "CJJ",
        allow_missing_route=True,
        min_price=MIN_RETURN_ADJUSTMENT,
    ) is True
    ret = candidate(0, text, ident="return-zero")
    assert choose_lowest_candidate(
        [ret],
        origin="TPE",
        destination="CJJ",
        allow_missing_route=True,
        min_price=MIN_RETURN_ADJUSTMENT,
    ) is ret


def test_return_card_rejects_reverse_departure_route():
    text = "2:20 PM – 5:45 PM\nEASTAR JET\n2 hr 25 min\nCJJ–TPE\nNonstop\n+₩0"
    assert flight_card_is_specific(
        text,
        "TPE",
        "CJJ",
        allow_missing_route=True,
        min_price=MIN_RETURN_ADJUSTMENT,
    ) is False
