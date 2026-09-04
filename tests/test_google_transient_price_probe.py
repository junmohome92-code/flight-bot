import importlib.util
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "google_transient_price_probe.py"
_SPEC = importlib.util.spec_from_file_location("google_transient_price_probe_for_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

normalize_events = _MODULE.normalize_events
matching_candidates = _MODULE.matching_candidates


def test_transient_event_requires_flight_row_shape():
    events = [
        {
            "price": 338121,
            "phase": "cheapest-transition",
            "seenAtMs": 123.4,
            "reason": "mutation-added",
            "url": "https://example.test/flights",
            "rowText": "11:40 PM\n1:10 AM\nEastar Jet\nNonstop\n2 hr 30 min\nCJJ-TPE\n₩338,121",
        },
        {
            "price": 120000,
            "phase": "cheapest-transition",
            "rowText": "Price graph\n₩120,000",
        },
    ]

    candidates = normalize_events(events)
    assert [item.price for item in candidates] == [338121]
    assert candidates[0].phase == "cheapest-transition"


def test_matching_transient_price_uses_cheapest_advertised_gate():
    candidates = normalize_events(
        [
            {
                "price": 338121,
                "phase": "cheapest-transition",
                "rowText": "11:40 PM\n1:10 AM\nEastar Jet\nNonstop\n2 hr 30 min\nCJJ-TPE\n₩338,121",
            },
            {
                "price": 405157,
                "phase": "base-fresh",
                "rowText": "10:30 AM\n12:20 PM\nAero K\nNonstop\n2 hr 50 min\nCJJ-TPE\n₩405,157",
            },
        ]
    )

    matched = matching_candidates(
        candidates,
        338121,
        phases={"cheapest-transition"},
    )
    assert [item.price for item in matched] == [338121]

    assert not matching_candidates(
        candidates,
        338121,
        phases={"base-fresh"},
    )
