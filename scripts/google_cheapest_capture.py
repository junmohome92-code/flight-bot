from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from playwright.async_api import Locator, Page

from flight_bot.google_ui_contract import MIN_KRW_PRICE, parse_krw_prices

try:  # direct Windows execution from scripts/
    import google_booking_pointer_probe as base
except ImportError:  # pytest/import from repository root
    from scripts import google_booking_pointer_probe as base


_CHEAPEST_RE = base._CHEAPEST_RE
_SELECTION_REFRESH_SECONDS = 0.08
_last_refresh_at: dict[int, float] = {}
_cached_selected: dict[int, dict[str, Any] | None] = {}


async def _control_state(locator: Locator) -> dict[str, Any]:
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
                    tag: host.tagName || '', role: role || '', text,
                    ariaSelected, ariaPressed, ariaChecked, ariaCurrent,
                    dataSelected, dataState, tabindex: attr('tabindex'),
                    selectedBy, isSelected: Boolean(selectedBy), hostInteractive,
                    connected: Boolean(host.isConnected)
                };
            }"""
        )
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def _candidate_locators(page: Page) -> list[Locator]:
    locators: list[Locator] = []
    for role in ("tab", "radio", "button", "link"):
        role_locator = page.get_by_role(role, name=_CHEAPEST_RE)
        try:
            count = min(await role_locator.count(), 12)
        except Exception:
            count = 0
        for index in range(count):
            locators.append(role_locator.nth(index))

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
            {"text": text, "advertised": advertised, "evidence": selected.get("selectedBy")},
        )
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def _arm_actual_click_boundary(control: Locator) -> None:
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
    try:
        raw = await page.evaluate(
            r"""() => {
                const s = window.__flightBotCaptureV4;
                if (!s) return null;
                if (s.cheapestClickStartedAtMs == null) {
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


async def select_cheapest_tab(page: Page, timeout_ms: int) -> dict[str, Any]:
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

    await _arm_actual_click_boundary(control)
    await control.click(timeout=5000)
    click_boundary = await _ensure_click_boundary_fallback(page)

    clicked_at = time.monotonic()
    selected: dict[str, Any] | None = None
    while time.monotonic() - clicked_at < 5.0:
        selected = await _selected_cheapest_state(page)
        if selected is not None:
            stamped = await _stamp_capture(page, selected)
            if stamped:
                selected = {**selected, **stamped}
            break
        await page.wait_for_timeout(40)

    print("cheapest_tab_found=True")
    print("cheapest_tab_clicked=True")
    if click_boundary is not None:
        print(f"cheapest_click_boundary_ms={click_boundary:.1f}")
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


async def ensure_cheapest_selected(page: Page, timeout_ms: int) -> tuple[dict[str, Any], bool]:
    selected = await _selected_cheapest_state(page)
    if selected is not None:
        stamped = await _stamp_capture(page, selected)
        if stamped:
            selected = {**selected, **stamped}
        print("cheapest_tab_found=True")
        print("cheapest_tab_clicked=False")
        print("cheapest_tab_selected=True")
        print(f"cheapest_selection_evidence={selected.get('selectedBy')}")
        print(f"cheapest_tab_role={selected.get('role') or 'none'}")
        print(f"cheapest_tab_text_after={str(selected.get('text') or '')[:300]}")
        return selected, False
    return await select_cheapest_tab(page, timeout_ms), True


async def capture_state(page: Page) -> dict:
    value = await base.capture_state(page)
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

    if selected is not None:
        value["cheapestSelected"] = True
        if selected.get("cheapestSelectedAtMs") is not None:
            value["cheapestSelectedAtMs"] = selected.get("cheapestSelectedAtMs")
        value["cheapestText"] = str(selected.get("text") or selected.get("cheapestText") or value.get("cheapestText") or "")
        if selected.get("advertisedPrice") is not None:
            value["advertisedPrice"] = selected.get("advertisedPrice")
        if selected.get("advertisedChangedAtMs") is not None:
            value["advertisedChangedAtMs"] = selected.get("advertisedChangedAtMs")
        value["cheapestSelectionEvidence"] = selected.get("selectedBy") or selected.get("cheapestSelectionEvidence")

    try:
        click_started = await page.evaluate(
            "() => window.__flightBotCaptureV4?.cheapestClickStartedAtMs ?? null"
        )
    except Exception:
        click_started = None
    if click_started is not None:
        try:
            value["cheapestClickStartedAtMs"] = float(click_started)
        except (TypeError, ValueError):
            pass
    return value


def phase_candidates(state: dict, phase: str) -> list[dict]:
    if phase != "departure":
        return base.phase_candidates(state, phase)

    raw = [
        item for item in (state.get("candidates") or [])
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
    return [item for item in raw if float(item.get("seenAtMs") or 0.0) >= boundary]


def departure_diagnostics(state: dict) -> None:
    raw = [
        item for item in (state.get("candidates") or [])
        if isinstance(item, dict) and item.get("phase") == "departure"
    ]
    kept = phase_candidates(state, "departure")
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
    print(f"departure_rejected_shape={state.get('rejectedShape', 0)}")
    print(f"departure_rejected_route={state.get('rejectedRoute', 0)}")
    print(f"departure_rejected_price_context={state.get('rejectedPriceContext', 0)}")
    print(f"departure_requested_at_ms={state.get('cheapestRequestedAtMs')}")
    print(f"departure_click_started_at_ms={state.get('cheapestClickStartedAtMs')}")
    print(f"departure_selected_at_ms={state.get('cheapestSelectedAtMs')}")
    if raw:
        sample = [
            {
                "price": item.get("price"),
                "seenAtMs": item.get("seenAtMs"),
                "selectedAtSeen": item.get("cheapestSelectedAtSeen"),
                "routeCount": item.get("routeCount"),
                "sourceText": str(item.get("sourceText") or "")[:160],
                "rowText": str(item.get("rowText") or "")[:420],
            }
            for item in raw[:8]
        ]
        print(f"departure_raw_candidate_sample={json.dumps(sample, ensure_ascii=False)[:6000]}")


async def wait_for_candidate(
    page: Page,
    *,
    phase: str,
    origin: str,
    destination: str,
    timeout_ms: int,
    capture_window_ms: int,
    allow_missing_route: bool,
    min_price: int,
):
    if phase != "departure":
        return await base.wait_for_candidate(
            page,
            phase=phase,
            origin=origin,
            destination=destination,
            timeout_ms=timeout_ms,
            capture_window_ms=capture_window_ms,
            allow_missing_route=allow_missing_route,
            min_price=min_price,
        )

    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    latest: dict = {"phase": "unknown", "candidates": []}
    last_lowest: int | None = None
    low_changed_at = time.monotonic()

    while asyncio.get_running_loop().time() < deadline:
        latest = await capture_state(page)
        candidates = phase_candidates(latest, phase)
        eligible = base.eligible_candidates(
            candidates,
            origin=origin,
            destination=destination,
            allow_missing_route=True,
            min_price=min_price,
        )
        current_lowest = int(eligible[0]["price"]) if eligible else None
        if current_lowest != last_lowest:
            last_lowest = current_lowest
            low_changed_at = time.monotonic()
        low_stable_ms = (time.monotonic() - low_changed_at) * 1000

        now_ms = float(latest.get("nowMs") or 0.0)
        selected_ms = float(latest.get("cheapestSelectedAtMs") or 0.0)
        started_ms = selected_ms or float(latest.get("phaseStartedAtMs") or now_ms)
        elapsed_ms = max(0.0, now_ms - started_ms)
        raw_advertised = latest.get("advertisedPrice")
        advertised = int(raw_advertised) if raw_advertised is not None else None
        changed_ms = float(latest.get("advertisedChangedAtMs") or started_ms)
        advertised_stable_ms = max(0.0, now_ms - changed_ms)
        ready = base.departure_capture_ready(
            candidate_count=len(eligible),
            elapsed_ms=elapsed_ms,
            advertised_stable_ms=advertised_stable_ms,
            candidate_low_stable_ms=low_stable_ms,
            loading=bool(latest.get("cheapestLoading", True)),
            capture_window_ms=capture_window_ms,
            advertised_price=advertised,
            candidate_lowest=current_lowest,
        )
        if ready:
            chosen = base.choose_lowest_candidate(
                candidates,
                origin=origin,
                destination=destination,
                advertised_price=advertised,
                allow_missing_route=True,
                min_price=min_price,
            )
            if chosen is not None:
                return dict(chosen), latest, "explicit-cheapest-settled-lowest"
        await page.wait_for_timeout(15)

    departure_diagnostics(latest)
    return {}, latest, "timeout"
