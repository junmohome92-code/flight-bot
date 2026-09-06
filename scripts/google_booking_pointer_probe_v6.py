from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from playwright.async_api import Locator, Page

try:  # direct Windows execution from scripts/
    import google_booking_pointer_probe_v5 as v5
except ImportError:  # pytest/import from repository root
    from scripts import google_booking_pointer_probe_v5 as v5


base = v5.base
_ORIGINAL_PHASE_CANDIDATES = base.phase_candidates
_ORIGINAL_WAIT_FOR_CANDIDATE = base.wait_for_candidate


async def _arm_actual_click_boundary(control: Locator) -> None:
    """Stamp the capture state when the real pointer gesture starts.

    Capture is intentionally active before clicking Cheapest so transition rows
    cannot be missed.  The old post-filter then discarded anything more than
    350 ms before selected-state confirmation, which could throw away exactly
    those transient rows.  A pointer/mouse event boundary lets us reject rows
    from the pre-click Best view without depending on how late Google exposes
    aria-selected/aria-checked.
    """
    await control.evaluate(
        r"""el => {
            const mark = () => {
                const s = window.__flightBotCaptureV4;
                if (!s || s.cheapestClickStartedAtMs != null) return;
                s.cheapestClickStartedAtMs = performance.now();
            };
            el.addEventListener('pointerdown', mark, {capture: true, once: true});
            el.addEventListener('mousedown', mark, {capture: true, once: true});
        }"""
    )


async def _ensure_click_boundary_fallback(page: Page) -> float | None:
    """Return the click boundary, falling back fail-safe to request time."""
    try:
        raw = await page.evaluate(
            r"""() => {
                const s = window.__flightBotCaptureV4;
                if (!s) return null;
                if (s.cheapestClickStartedAtMs == null) {
                    // If the browser did not expose pointer/mouse events, keep
                    // the early-capture invariant rather than moving the
                    // boundary forward and losing a legitimate transition row.
                    s.cheapestClickStartedAtMs = s.cheapestRequestedAtMs ?? performance.now();
                }
                return s.cheapestClickStartedAtMs;
            }"""
        )
    except Exception:
        return None
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def select_cheapest_tab_v6(page: Page, timeout_ms: int) -> dict[str, Any]:
    # Keep the observer active before the real click.  Only the later candidate
    # boundary changes: it is tied to the actual pointer gesture, not to delayed
    # selected-state confirmation.
    await base.set_phase(page, "departure", cheapest_requested=True)

    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    control: Locator | None = None
    before: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline and control is None:
        control, before = await v5._visible_click_target(page)
        if control is None:
            await page.wait_for_timeout(50)
    if control is None:
        states = await v5._diagnostic_states(page)
        print(f"cheapest_controls_found={json.dumps(states, ensure_ascii=False)[:5000]}")
        raise RuntimeError("Cheapest/최저가 interactive control was not found")

    await _arm_actual_click_boundary(control)
    await control.click(timeout=5000)
    click_boundary = await _ensure_click_boundary_fallback(page)

    clicked_at = time.monotonic()
    selected: dict[str, Any] | None = None
    while time.monotonic() - clicked_at < 5.0:
        # Re-query after every transition because Google may replace the node.
        selected = await v5._selected_cheapest_state(page)
        if selected is not None:
            stamped = await v5._stamp_capture(page, selected)
            if stamped:
                selected = {**selected, **stamped}
            break
        await page.wait_for_timeout(40)

    print("cheapest_tab_found=True")
    print("cheapest_tab_clicked=True")
    if click_boundary is not None:
        print(f"cheapest_click_boundary_ms={click_boundary:.1f}")
    if selected is None:
        states = await v5._diagnostic_states(page)
        print("cheapest_tab_selected=False")
        print(f"cheapest_control_before={json.dumps(before, ensure_ascii=False)[:2500]}")
        print(f"cheapest_controls_after={json.dumps(states, ensure_ascii=False)[:5000]}")
        raise RuntimeError("Cheapest/최저가 control was clicked but no strong selected-state evidence appeared")

    print("cheapest_tab_selected=True")
    print(f"cheapest_selection_evidence={selected.get('selectedBy')}")
    print(f"cheapest_tab_role={selected.get('role') or 'none'}")
    print(f"cheapest_tab_text_before={str(before.get('text') or '')[:300]}")
    print(f"cheapest_tab_text_after={str(selected.get('text') or '')[:300]}")
    return selected


async def capture_state_v6(page: Page) -> dict:
    """Return V5 state plus the actual Cheapest click boundary."""
    value = await v5.capture_state_v5(page)
    if not isinstance(value, dict):
        return value
    if value.get("phase") != "departure":
        return value

    try:
        click_started = await page.evaluate(
            """() => window.__flightBotCaptureV4?.cheapestClickStartedAtMs ?? null"""
        )
    except Exception:
        click_started = None
    if click_started is not None:
        try:
            value["cheapestClickStartedAtMs"] = float(click_started)
        except (TypeError, ValueError):
            pass
    return value


def phase_candidates_v6(state: dict, phase: str) -> list[dict]:
    """Keep departure rows observed from the actual click gesture onward.

    The previous boundary was ``max(requested, selected - 350 ms)``.  When
    selected-state confirmation lagged the visual transition, a correctly
    preserved transient row could be captured and then discarded.  The click
    event is the semantic boundary we actually need: pre-click Best rows are
    excluded, while every post-click Cheapest transition row survives.
    """
    if phase != "departure":
        return _ORIGINAL_PHASE_CANDIDATES(state, phase)

    raw = [
        item
        for item in (state.get("candidates") or [])
        if isinstance(item, dict) and item.get("phase") == "departure"
    ]
    try:
        requested = float(state.get("cheapestRequestedAtMs") or 0.0)
    except (TypeError, ValueError):
        requested = 0.0
    try:
        click_started = float(state.get("cheapestClickStartedAtMs") or 0.0)
    except (TypeError, ValueError):
        click_started = 0.0

    boundary = click_started or requested
    if boundary <= 0:
        return raw
    return [
        item
        for item in raw
        if float(item.get("seenAtMs") or 0.0) >= boundary
    ]


def _departure_diagnostics(state: dict) -> None:
    raw = [
        item
        for item in (state.get("candidates") or [])
        if isinstance(item, dict) and item.get("phase") == "departure"
    ]
    kept = phase_candidates_v6(state, "departure")
    kept_ids = {id(item) for item in kept}
    dropped = [item for item in raw if id(item) not in kept_ids]

    def prices(items: list[dict]) -> list[int]:
        result: set[int] = set()
        for item in items:
            try:
                result.add(int(item.get("price")))
            except (TypeError, ValueError, AttributeError):
                pass
        return sorted(result)

    print(f"departure_raw_candidate_count={len(raw)}")
    print(f"departure_raw_candidate_prices={prices(raw)}")
    print(f"departure_post_click_candidate_count={len(kept)}")
    print(f"departure_post_click_candidate_prices={prices(kept)}")
    print(f"departure_pre_click_candidate_count={len(dropped)}")
    print(f"departure_pre_click_candidate_prices={prices(dropped)}")
    print(f"departure_rejected_broad={state.get('rejectedBroad', 0)}")
    print(f"departure_rejected_source={state.get('rejectedSource', 0)}")
    print(f"departure_requested_at_ms={state.get('cheapestRequestedAtMs')}")
    print(f"departure_click_started_at_ms={state.get('cheapestClickStartedAtMs')}")
    print(f"departure_selected_at_ms={state.get('cheapestSelectedAtMs')}")
    if raw:
        sample = [
            {
                "price": item.get("price"),
                "seenAtMs": item.get("seenAtMs"),
                "selectedAtSeen": item.get("cheapestSelectedAtSeen"),
                "sourceText": str(item.get("sourceText") or "")[:160],
                "rowText": str(item.get("rowText") or "")[:420],
            }
            for item in raw[:8]
        ]
        print(f"departure_raw_candidate_sample={json.dumps(sample, ensure_ascii=False)[:6000]}")


async def wait_for_candidate_v6(*args, **kwargs):
    candidate, state, policy = await _ORIGINAL_WAIT_FOR_CANDIDATE(*args, **kwargs)
    phase = kwargs.get("phase")
    if phase is None and len(args) >= 2:
        phase = args[1]
    if phase == "departure" and not candidate:
        _departure_diagnostics(state)
    return candidate, state, policy


# Keep the existing DOM observer, candidate shape rules, advertised-price guard,
# stale-pointer safety, Returning navigation and Booking scoping unchanged.  The
# only behavioral correction is the departure candidate time boundary.
base.select_cheapest_tab = select_cheapest_tab_v6
base.capture_state = capture_state_v6
base.phase_candidates = phase_candidates_v6
base.wait_for_candidate = wait_for_candidate_v6


if __name__ == "__main__":
    asyncio.run(base.main())
