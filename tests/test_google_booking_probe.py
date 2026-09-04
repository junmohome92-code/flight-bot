import importlib.util
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "google_booking_probe.py"
_SPEC = importlib.util.spec_from_file_location("google_booking_probe_for_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

parse_booking_price = _MODULE.parse_booking_price
row_text_is_specific_flight = _MODULE.row_text_is_specific_flight
acceptance_cheapest_url = _MODULE.acceptance_cheapest_url


def test_parse_booking_price_uses_krw_only():
    assert parse_booking_price("Book with airline\n₩337,056") == 337056
    assert parse_booking_price("₩415,400\n₩337,056") == 337056
    assert parse_booking_price("USD 250") is None


def test_parse_booking_price_rejects_implausible_values():
    assert parse_booking_price("Book\n₩3,370") is None
    assert parse_booking_price("Book\n₩9,999,999") is None


def test_specific_flight_row_accepts_one_compact_result():
    text = (
        "11:40 PM – 1:10 AM+1\n"
        "Separate tickets booked together\n"
        "EASTAR JET\n"
        "2 hr 30 min\n"
        "CJJ–TPE\n"
        "Nonstop\n"
        "₩337,056\n"
        "round trip"
    )
    assert row_text_is_specific_flight(text, "CJJ", "TPE") is True


def test_specific_flight_row_rejects_results_list_container():
    text = (
        "Best Cheapest Fetching results ₩922,965\n"
        "10:30 AM – 12:20 PM Aero K Airlines 2 hr 50 min CJJ–TPE Nonstop Price unavailable\n"
        "5:20 PM – 10:25 AM+1 Korean Air, Asiana Airlines 18 hr 5 min CJJ–TPE 2 stops ₩922,965\n"
        "5:20 PM – 12:10 PM+1 Korean Air 19 hr 50 min CJJ–TPE 2 stops ₩922,965"
    )
    assert row_text_is_specific_flight(text, "CJJ", "TPE") is False


def test_specific_flight_row_requires_requested_direction():
    text = "9:10 AM – 11:20 AM EASTAR JET 2 hr 10 min TPE–CJJ Nonstop ₩337,056"
    assert row_text_is_specific_flight(text, "CJJ", "TPE") is False
    assert row_text_is_specific_flight(text, "TPE", "CJJ") is True


def test_acceptance_cheapest_url_adds_tfu_once():
    base = "https://www.google.com/travel/flights/search?tfs=abc&hl=en&gl=kr&curr=KRW"
    value = acceptance_cheapest_url(base)
    assert "tfu=EgoIABAAGAAgAigB" in value
    assert value.count("tfu=") == 1
    assert acceptance_cheapest_url(value) == value
