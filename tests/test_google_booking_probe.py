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


def test_parse_booking_price_uses_krw_only():
    assert parse_booking_price("Book with airline\n₩337,056") == 337056
    assert parse_booking_price("₩415,400\n₩337,056") == 337056
    assert parse_booking_price("USD 250") is None


def test_parse_booking_price_rejects_implausible_values():
    assert parse_booking_price("Book\n₩3,370") is None
    assert parse_booking_price("Book\n₩9,999,999") is None
