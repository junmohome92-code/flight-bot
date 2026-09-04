import importlib.util
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "google_booking_pointer_probe.py"
_SPEC = importlib.util.spec_from_file_location("google_booking_pointer_probe_for_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

card_text_is_local = _MODULE.card_text_is_local


def test_local_flight_card_is_accepted():
    text = """
    11:40 PM – 1:10 AM+1
    Separate tickets booked together
    EASTAR JET
    2 hr 30 min
    CJJ–TPE
    Nonstop
    ₩335,906
    round trip
    """
    assert card_text_is_local(text, "CJJ", "TPE") is True


def test_search_results_container_is_rejected_even_with_one_route():
    text = """
    Flight search
    Round trip
    Filters
    All filters
    Search results
    Best
    Cheapest
    from Fetching results ₩335,906
    Checking prices from multiple sources...
    Searching nearby airports...
    Top departing flights
    Sorted by top flights
    11:40 PM – 1:10 AM+1
    EASTAR JET
    2 hr 30 min
    CJJ–TPE
    Nonstop
    ₩335,906 round trip
    """
    assert card_text_is_local(text, "CJJ", "TPE") is False


def test_wrong_direction_is_rejected():
    text = "11:40 PM – 1:10 AM+1\nEASTAR JET\n2 hr 30 min\nCJJ–TPE\nNonstop\n₩335,906"
    assert card_text_is_local(text, "TPE", "CJJ") is False
