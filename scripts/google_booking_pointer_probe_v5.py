from __future__ import annotations

import asyncio
import json
import time
import warnings
from typing import Any

from playwright.async_api import Locator, Page

from flight_bot.google_ui_contract import MIN_KRW_PRICE, parse_krw_prices

# The legacy acceptance module still contains one JavaScript regex inside a
# normal Python triple-quoted string. Python 3.12+ reports that as a cosmetic
# SyntaxWarning while importing it. Keep the focused V5 acceptance output clean;
# the warning is unrelated to Google UI selection correctness.
warnings.filterwarnings("ignore", category=SyntaxWarning, message=r"invalid escape sequence")

try:  # pytest/import from repository root
    from scripts import google_booking_pointer_probe as base
except ImportError:  # direct: python scripts/google_booking_pointer_probe_v5.py
    import google_booking_pointer_probe as base


_CHEAPEST_RE = base._CHEAPEST_RE
_ORIGINAL_CAPTURE_STATE = base.capture_state
_SELECTION_REFRESH_SECONDS = 0.08
_last_refresh_at: dict[int, float] = {}
_cached_selected: dict[int, dict[str, Any] | None] = {}


async def _control_state(locator: Locator) -> dict[str, Any]:
    """Read strong selection semantics from the interactive Cheapest host.

    Google can render the Best/Cheapest switch as a tab, radio-like control, or
    another accessible interactive element. Do not infer selection from CSS
    class names; only explicit accessibility/data state is accepted.
    """
    try:
        value = await locator.evaluate(
            r"""el => {
                const selector = '[role="tab"], [role="radio"], [role="button"], [role="link"], button, a, [tabindex="0"]';
                const host = el.matches?.(selector) ? el : (el.closest?.(selector) || el);
                const attr = name => host.getAttribute?.(name);
                const ariaSelected = attr('aria-selected');
                const ariaPressed = attr('aria-pressed');
                const ariaChecked = attr('aria-checked');
                const ariaCurrent = attr('aria-current');
                const dataSelected = attr('data-selected');
                const dataState = attr('data-state');
                const currentSelected = ['true', 'page', 'step', 'location', 'date', 'time'].includes(String(ariaCurrent || '').toLowerCase());
                const dataSelectedFlag = ['true', 'selected', 'active', 'checked', 'on'].includes(String(dataSelected || '').toLowerCase());
                const dataStateFlag = ['selected', 'active', 'checked', 'on'].includes(String(dataState || '').toLowerCase());
                let selectedBy = null;
                if (ariaSelected === 'true') selectedBy = 'aria-selected';
                else if (ariaPressed === 'true') selectedBy = 'aria-pressed';
                else if (ariaChecked === 'true') selectedBy = 'aria-checked';
                else if (currentSelected) selectedBy = 'aria-current';
                else if (dataSelectedFlag) selectedBy = 'data-selected';
                else if (dataStateFlag) selectedBy = 'data-state';
                else if (host instanceof HTMLInputElement && host.checked) selectedBy = 'checked';
                const text = (host.innerText || host.textContent || host.getAttribute?.('aria-label') || '').replace(/\s+/g, ' ').trim();
                const role = attr('role');
                const hostInteractive = Boolean(
                    host.matches?.('button, a, [role="tab"], [role="radio"], [role="button"], [role="link"], [tabindex="0"]')
                );
                return {
                    tag: host.tagName || '',
                    role: role || '',
                    text,
                    ariaSelected,
                    ariaPressed,
                    ariaChecked,
                    ariaCurrent,
                    dataSelected,
                    dataState,
                    tabindex: attr('tabindex'),
                    selectedBy,
                    isSelected: Boolean(selectedBy),
                    hostInteractive,
                    connected: Boolean(host.isConnected)
                };
            }"""
        )
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def _candidate_locators(page: Page) -> list[Locator]:
    """Return fresh Cheapest candidates, ordered from strongest semantics."""
    locators: list[Locator] = []
    for role in ("tab", "radio", "button", "link"):
        role_locator = page.get_by_role(role, name=_CHEAPEST_RE)
        try:
            count = min(await role_locator.count(), 12)
        except Exception:
            count = 0
        for index in range(count):
            locators.append(role_locator.nth(index))

    # Fallback is allowed only when the text sits inside an interactive host.
    # This prevents clicking a plain explanatory "Cheapest" string elsewhere.
    text_locator = page.get_by_text(_CHEAPEST_RE)
    try:
        count = min(await text_locator.count(), 20)
    except Exception:
        count = 0
    for index in range(count):
        item = text_locator.nth(index)
        try:
            if not await item.is_visible():
                continue
        except Exception:
            continue
        state = await _control_state(item)
        if state.get("hostInteractive"):
            locators.append(item)
    return locators


async def _visible_click_target(page: Page) -> tuple[Locator | None, dict[str, Any]]:
    for locator in await _candidate_locators(page):
        try:
            if not await locator.is_visible():
                continue
        except Exception:
            continue
        state = await _control_state(locator)
        if state.get("hostInteractive") and _CHEAPEST_RE.search(str(state.get("text") or "")):
            return locator, state
    return None, {}


async def _selected_cheapest_state(page: Page) -> dict[str, Any] | None:
    for locator in await _candidate_locators(page):
        try:
            if not await locator.is_visible():
                continue
        except Exception:
            continue
        state = await _control_state(locator)
        if state.get("isSelected") and _CHEAPEST_RE.search(str(state.get("text") or "")):
            return state
    return None


async def _diagnostic_states(page: Page) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for locator in await _candidate_locators(page):
        state = await _control_state(locator)
        if not state:
            continue
        key = (
            str(state.get("tag") or ""),
            str(state.get("role") or ""),
            str(state.get("text") or "")[:240],
            str(state.get("selectedBy") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        results.append(state)
        if len(results) >= 12:
            break
    return results


async def _stamp_capture(page: Page, selected: dict[str, Any]) -> dict[str, Any]:
    text = str(selected.get("text") or "")
    prices = parse_krw_prices(text, min_price=MIN_KRW_PRICE)
    advertised = min(prices) if prices else None
    try:
        value = await page.evaluate(
            r"""({text, advertised, evidence}) => {
                const s = window.__flightBotCaptureV4;
                if (!s) return {};
                const now = performance.now();
                if (!s.cheapestSelected) {
                    s.cheapestSelected = true;
                    s.cheapestSelectedAtMs = now;
                }
                s.cheapestText = text || s.cheapestText || '';
                s.cheapestSelectionEvidence = evidence || null;
                if (advertised !== null && (s.advertisedPrice === null || advertised < s.advertisedPrice)) {
                    s.advertisedPrice = advertised;
                    s.advertisedChangedAtMs = now;
                }
                return {
                    cheapestSelected: s.cheapestSelected,
                    cheapestSelectedAtMs: s.cheapestSelectedAtMs,
                    cheapestText: s.cheapestText,
                    cheapestSelectionEvidence: s.cheapestSelectionEvidence,
                    advertisedPrice: s.advertisedPrice,
                    advertisedChangedAtMs: s.advertisedChangedAtMs
                };
            }""",
            {
                "text": text,
                "advertised": advertised,
                "evidence": selected.get("selectedBy"),
            },
        )
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def select_cheapest_tab_v5(page: Page, timeout_ms: int) -> dict[str, Any]:
    # Preserve the existing hardening invariant: capture starts before click.
    await base.set_phase(page, "departure", cheapest_requested=True)

    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    control: Locator | None = None
    before: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline and control is None:
        control, before = await _visible_click_target(page)
        if control is None:
            await page.wait_for_timeout(50)
    if control is None:
        states = await _diagnostic_states(page)
        print(f"cheapest_controls_found={json.dumps(states, ensure_ascii=False)[:5000]}")
        raise RuntimeError("Cheapest/최저가 interactive control was not found")

    await control.click(timeout=5000)
    clicked_at = time.monotonic()
    selected: dict[str, Any] | None = None
    while time.monotonic() - clicked_at < 5.0:
        # Re-query the page after every click transition. Google may replace the
        # original node, so the pre-click locator is not trusted as state truth.
        selected = await _selected_cheapest_state(page)
        if selected is not None:
            stamped = await _stamp_capture(page, selected)
            if stamped:
                selected = {**selected, **stamped}
            break
        await page.wait_for_timeout(40)

    print("cheapest_tab_found=True")
    print("cheapest_tab_clicked=True")
    if selected is None:
        states = await _diagnostic_states(page)
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


async def capture_state_v5(page: Page) -> dict:
    """Augment V4 capture with fresh strong Cheapest selection semantics.

    The V4 DOM observer remains responsible for transient flight rows. This
    shim only fills the selection/advertised fields when Google's current
    control semantics are not aria-selected/aria-pressed.
    """
    value = await _ORIGINAL_CAPTURE_STATE(page)
    if not isinstance(value, dict) or value.get("phase") != "departure":
        return value

    page_key = id(page)
    now = time.monotonic()
    selected = _cached_selected.get(page_key)
    if now - _last_refresh_at.get(page_key, 0.0) >= _SELECTION_REFRESH_SECONDS:
        selected = await _selected_cheapest_state(page)
        _last_refresh_at[page_key] = now
        _cached_selected[page_key] = selected
        if selected is not None:
            stamped = await _stamp_capture(page, selected)
            if stamped:
                selected = {**selected, **stamped}
                _cached_selected[page_key] = selected

    if selected is None:
        return value

    value["cheapestSelected"] = True
    if selected.get("cheapestSelectedAtMs") is not None:
        value["cheapestSelectedAtMs"] = selected.get("cheapestSelectedAtMs")
    value["cheapestText"] = str(selected.get("text") or selected.get("cheapestText") or value.get("cheapestText") or "")
    if selected.get("advertisedPrice") is not None:
        value["advertisedPrice"] = selected.get("advertisedPrice")
    if selected.get("advertisedChangedAtMs") is not None:
        value["advertisedChangedAtMs"] = selected.get("advertisedChangedAtMs")
    value["cheapestSelectionEvidence"] = selected.get("selectedBy") or selected.get("cheapestSelectionEvidence")
    return value


# Keep every existing transient-row, pointer, Returning, Booking and fail-closed
# rule intact. Only replace the two narrow Windows-acceptance boundaries that
# proved too strict on the live Google control semantics.
base.select_cheapest_tab = select_cheapest_tab_v5
base.capture_state = capture_state_v5


if __name__ == "__main__":
    asyncio.run(base.main())
