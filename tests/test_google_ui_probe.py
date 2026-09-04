import importlib.util
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "google_ui_probe.py"
_SPEC = importlib.util.spec_from_file_location("google_ui_probe_for_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

cheapest_price_consistent = _MODULE.cheapest_price_consistent
footer_setting = _MODULE.footer_setting
looks_like_cheapest_tab = _MODULE.looks_like_cheapest_tab
parse_price = _MODULE.parse_price
parse_prices = _MODULE.parse_prices
row_looks_like_flight_result = _MODULE.row_looks_like_flight_result


def test_parse_prices():
    assert parse_price("₩337,079 round trip") == 337079
    assert parse_price("337,079 South Korean won") == 337079
    assert parse_price("최저가 ₩338,121부터") == 338121
    assert parse_price("no price") is None
    assert parse_prices("₩337,079 / ₩420,000") == [337079, 420000]


def test_cheapest_tab_supports_english_and_korean():
    assert looks_like_cheapest_tab("Cheapest from ₩338,121")
    assert looks_like_cheapest_tab("최저가 ₩338,121부터")
    assert not looks_like_cheapest_tab("Recommended")
    assert not looks_like_cheapest_tab("추천")


def test_cheapest_price_consistency_rejects_missed_lower_row():
    assert cheapest_price_consistent(338121, 338121)
    assert cheapest_price_consistent(338121, 337000)
    assert not cheapest_price_consistent(338121, 405157)
    assert cheapest_price_consistent(None, 405157)
    assert not cheapest_price_consistent(338121, None)


def test_row_scope_requires_flight_shape():
    english_row = "6:20 PM\n9:00 PM\nT'way Air\nNonstop\n2 hr 40 min\nCJJ\nTPE\n₩337,079"
    korean_row = "오후 11:40\n오전 1:10\n이스타항공\n직항\n2시간 30분\nCJJ–TPE\n₩338,121"
    assert row_looks_like_flight_result(english_row)
    assert row_looks_like_flight_result(korean_row)
    assert not row_looks_like_flight_result("Price graph\n₩120,000")
    assert not row_looks_like_flight_result("CJJ to TPE\n₩337,079")


def test_footer_setting():
    body = "Language\nEnglish\nLocation\nSouth Korea\nCurrency\nKRW"
    assert footer_setting(body, "Language") == "English"
    assert footer_setting(body, "Location") == "South Korea"
    assert footer_setting(body, "Currency") == "KRW"
