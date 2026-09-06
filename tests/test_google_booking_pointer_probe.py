import importlib.util
import sys
from pathlib import Path

from flight_bot.google_ui_contract import (
    MIN_RETURN_ADJUSTMENT,
    choose_lowest_candidate,
    departure_capture_ready,
    flight_card_is_specific,
    parse_krw_prices,
)


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "google_booking_pointer_probe.py"
_SPEC = importlib.util.spec_from_file_location("google_booking_pointer_probe_for_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
phase_candidates = _MODULE.phase_candidates


def candidate(price: int, row: str, seen: float = 1000.0, ident: str = "x", phase: str = "departure") -> dict:
    return {"id": ident, "price": price, "rowText": row, "seenAtMs": seen, "phase": phase}


def departure_row(price: int = 311_811) -> str:
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
    assert parse_krw_prices("311811 South Korean won") == [311811]
    assert parse_krw_prices("₩311,811") == [311811]


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
    Cheapest from ₩311,811
    Top departing flights
    11:40 PM – 1:10 AM+1
    EASTAR JET
    2 hr 30 min
    CJJ–TPE
    Nonstop
    ₩311,811 round trip
    """
    assert flight_card_is_specific(text, "CJJ", "TPE") is False


def test_advertised_cheapest_blocks_expensive_fallback():
    expensive = candidate(
        418_500,
        "10:30 AM – 12:20 PM\nAero K Airlines\n2 hr 50 min\nCJJ–TPE\nNonstop\n₩418,500",
    )
    assert choose_lowest_candidate(
        [expensive], origin="CJJ", destination="TPE", advertised_price=311_811
    ) is None


def test_disappeared_cheapest_snapshot_beats_stable_expensive_row():
    cheap = candidate(311_811, departure_row(311_811), seen=435.0, ident="cheap")
    expensive = candidate(
        418_500,
        "10:30 AM – 12:20 PM\nAero K Airlines\n2 hr 50 min\nCJJ–TPE\nNonstop\n₩418,500",
        seen=800.0,
        ident="expensive",
    )
    chosen = choose_lowest_candidate(
        [expensive, cheap], origin="CJJ", destination="TPE", advertised_price=311_811
    )
    assert chosen is cheap


def test_loading_single_row_never_becomes_ready():
    assert departure_capture_ready(
        candidate_count=1,
        elapsed_ms=5000,
        advertised_stable_ms=3000,
        candidate_low_stable_ms=3000,
        loading=True,
        capture_window_ms=1500,
        advertised_price=418500,
        candidate_lowest=418500,
    ) is False


def test_loading_multiple_rows_need_both_minimums_stable():
    assert departure_capture_ready(
        candidate_count=4,
        elapsed_ms=3500,
        advertised_stable_ms=900,
        candidate_low_stable_ms=900,
        loading=True,
        capture_window_ms=3000,
        advertised_price=311811,
        candidate_lowest=311811,
    ) is True
    assert departure_capture_ready(
        candidate_count=4,
        elapsed_ms=3500,
        advertised_stable_ms=900,
        candidate_low_stable_ms=100,
        loading=True,
        capture_window_ms=3000,
        advertised_price=311811,
        candidate_lowest=311811,
    ) is False


def test_advertised_lower_than_captured_minimum_never_ready():
    assert departure_capture_ready(
        candidate_count=5,
        elapsed_ms=5000,
        advertised_stable_ms=2000,
        candidate_low_stable_ms=2000,
        loading=False,
        capture_window_ms=1500,
        advertised_price=311811,
        candidate_lowest=384361,
    ) is False


def test_finished_loading_allows_one_thin_route_after_settle():
    assert departure_capture_ready(
        candidate_count=1,
        elapsed_ms=2000,
        advertised_stable_ms=800,
        candidate_low_stable_ms=800,
        loading=False,
        capture_window_ms=1500,
        advertised_price=311811,
        candidate_lowest=311811,
    ) is True


def test_departure_phase_filters_pre_selected_best_rows():
    state = {
        "cheapestRequestedAtMs": 1000.0,
        "cheapestSelectedAtMs": 1300.0,
        "candidates": [
            candidate(418500, departure_row(418500), seen=800.0, ident="best-old"),
            candidate(311811, departure_row(311811), seen=1250.0, ident="cheapest-transition"),
        ],
    }
    assert [item["id"] for item in phase_candidates(state, "departure")] == ["cheapest-transition"]


def test_return_phase_keeps_only_rows_near_or_after_returning_marker():
    state = {
        "returningMarkerAtMs": 3000.0,
        "candidates": [
            candidate(0, return_row(0), seen=2000.0, ident="pre-nav", phase="returning"),
            candidate(0, return_row(0), seen=2850.0, ident="transition", phase="returning"),
            candidate(25000, return_row(25000), seen=3200.0, ident="return", phase="returning"),
        ],
    }
    assert [item["id"] for item in phase_candidates(state, "returning")] == ["transition", "return"]


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
    ret = candidate(0, text, ident="return-zero", phase="returning")
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
