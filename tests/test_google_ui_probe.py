import importlib.util
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "google_ui_probe.py"
_SPEC = importlib.util.spec_from_file_location("google_ui_probe_for_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

footer_setting = _MODULE.footer_setting
parse_price = _MODULE.parse_price
parse_prices = _MODULE.parse_prices
row_looks_like_flight_result = _MODULE.row_looks_like_flight_result


def test_parse_prices():
    assert parse_price("₩337,079 round trip") == 337079
    assert parse_price("337,079 South Korean won") == 337079
    assert parse_price("no price") is None
    assert parse_prices("₩337,079 / ₩420,000") == [337079, 420000]


def test_row_scope_requires_flight_shape():
    flight_row = "6:20 PM\n9:00 PM\nT'way Air\nNonstop\n2 hr 40 min\nCJJ\nTPE\n₩337,079"
    assert row_looks_like_flight_result(flight_row)
    assert not row_looks_like_flight_result("Price graph\n₩120,000")
    assert not row_looks_like_flight_result("CJJ to TPE\n₩337,079")


def test_footer_setting():
    body = "Language\nEnglish\nLocation\nSouth Korea\nCurrency\nKRW"
    assert footer_setting(body, "Language") == "English"
    assert footer_setting(body, "Location") == "South Korea"
    assert footer_setting(body, "Currency") == "KRW"
