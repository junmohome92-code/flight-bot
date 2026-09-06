from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
from google_booking_pointer_probe_v6 import phase_candidates_v6  # noqa: E402


def test_departure_boundary_uses_actual_click_not_delayed_selected_state():
    state = {
        "cheapestRequestedAtMs": 1000.0,
        "cheapestClickStartedAtMs": 1200.0,
        "cheapestSelectedAtMs": 2600.0,
        "candidates": [
            {"phase": "departure", "price": 418500, "seenAtMs": 1100.0, "rowText": "pre-click Best"},
            {"phase": "departure", "price": 311578, "seenAtMs": 1280.0, "rowText": "post-click transient Cheapest"},
            {"phase": "departure", "price": 325000, "seenAtMs": 2400.0, "rowText": "later Cheapest"},
        ],
    }

    kept = phase_candidates_v6(state, "departure")

    assert [item["price"] for item in kept] == [311578, 325000]
    # The old selected-350ms boundary would have been 2250 ms and would have
    # incorrectly discarded the 311,578 row captured just after the real click.
    assert kept[0]["seenAtMs"] < state["cheapestSelectedAtMs"] - 350.0


def test_departure_boundary_falls_back_to_requested_time_without_click_event():
    state = {
        "cheapestRequestedAtMs": 1000.0,
        "cheapestSelectedAtMs": 2100.0,
        "candidates": [
            {"phase": "departure", "price": 311578, "seenAtMs": 1050.0},
        ],
    }

    kept = phase_candidates_v6(state, "departure")
    assert [item["price"] for item in kept] == [311578]
