from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from playwright.async_api import Locator, Page


_CHEAPEST_RE = re.compile(r"^\s*(?:Cheapest\b|최저가)", re.I)
_PRICE_UNAVAILABLE_RE = re.compile(
    r"price(?:s)? unavailable|"
    r"가격\s*표시\s*불가|"
    r"가격\s*정보\s*없음|"
    r"가격\s*정보를\s*이용할\s*수\s*없|"
    r"가격을\s*이용할\s*수\s*없",
    re.I,
)
_KRW_READY_RE = re.compile(
    r"₩\s*[0-9][0-9,]*|[0-9][0-9,]*\s+(?:South Korean won|Korean won|KRW)",
    re.I,
)


class GoogleResultsFlowError(RuntimeError):
    pass


class GooglePriceUnavailableError(GoogleResultsFlowError):
    pass


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
                const currentSelected = ['true', 'page', 'step', 'location', 'date', 'time']
                    .includes(String(ariaCurrent || '').toLowerCase());
                const dataSelectedFlag = ['true', 'selected', 'active', 'checked', 'on']
                    .includes(String(dataSelected || '').toLowerCase());
                const dataStateFlag = ['selected', 'active', 'checked', 'on']
                    .includes(String(dataState || '').toLowerCase());
                let selectedBy = null;
                if (ariaSelected === 'true') selectedBy = 'aria-selected';
                else if (ariaPressed === 'true') selectedBy = 'aria-pressed';
                else if (ariaChecked === 'true') selectedBy = 'aria-checked';
                else if (currentSelected) selectedBy = 'aria-current';
                else if (dataSelectedFlag) selectedBy = 'data-selected';
                else if (dataStateFlag) selectedBy = 'data-state';
                else if (host instanceof HTMLInputElement && host.checked) selectedBy = 'checked';
                const text = (host.innerText || host.textContent || host.getAttribute?.('aria-label') || '')
                    .replace(/\s+/g, ' ').trim();
                return {
                    tag: host.tagName || '',
                    role: attr('role') || '',
                    text,
                    selectedBy,
                    isSelected: Boolean(selectedBy),
                    hostInteractive: Boolean(
                        host.matches?.('button, a, [role="tab"], [role="radio"], [role="button"], [role="link"], [tabindex="0"]')
                    ),
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
        locator = page.get_by_role(role, name=_CHEAPEST_RE)
        try:
            count = min(await locator.count(), 12)
        except Exception:
            count = 0
        for index in range(count):
            locators.append(locator.nth(index))

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


async def _visible_cheapest_control(page: Page) -> tuple[Locator | None, dict[str, Any]]:
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


async def ensure_cheapest_selected(page: Page, timeout_ms: int) -> tuple[dict[str, Any], bool]:
    """Require strong selected-state evidence, not CSS/class heuristics."""

    selected = await _selected_cheapest_state(page)
    if selected is not None:
        print("cheapest_tab_found=True")
        print("cheapest_tab_clicked=False")
        print("cheapest_tab_selected=True")
        print(f"cheapest_selection_evidence={selected.get('selectedBy')}")
        print(f"cheapest_tab_role={selected.get('role') or 'none'}")
        print(f"cheapest_tab_text_after={str(selected.get('text') or '')[:300]}")
        return selected, False

    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    control: Locator | None = None
    before: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline and control is None:
        control, before = await _visible_cheapest_control(page)
        if control is None:
            await page.wait_for_timeout(50)
    if control is None:
        raise GoogleResultsFlowError("Cheapest/최저가 interactive control was not found")

    await control.click(timeout=5_000)
    clicked_at = time.monotonic()
    selected = None
    while time.monotonic() - clicked_at < 5.0:
        selected = await _selected_cheapest_state(page)
        if selected is not None:
            break
        await page.wait_for_timeout(40)

    print("cheapest_tab_found=True")
    print("cheapest_tab_clicked=True")
    if selected is None:
        raise GoogleResultsFlowError(
            "Cheapest/최저가 control was clicked but no strong selected-state evidence appeared"
        )
    print("cheapest_tab_selected=True")
    print(f"cheapest_selection_evidence={selected.get('selectedBy')}")
    print(f"cheapest_tab_role={selected.get('role') or 'none'}")
    print(f"cheapest_tab_text_before={str(before.get('text') or '')[:300]}")
    print(f"cheapest_tab_text_after={str(selected.get('text') or '')[:300]}")
    return selected, True


async def search_surface_state(page: Page) -> str:
    """Use body-wide KRW only as readiness; never as a candidate price source."""

    if page.is_closed():
        return "closed"
    try:
        body = await page.locator("body").inner_text(timeout=2_500)
    except Exception:
        return "closed" if page.is_closed() else "loading"
    text = body[:40_000]
    if _KRW_READY_RE.search(text):
        return "ready"
    if _PRICE_UNAVAILABLE_RE.search(text):
        return "unavailable"
    return "loading"


ReloadPage = Callable[[Page, str, int], Awaitable[Page]]
EnsureSelected = Callable[[Page, int], Awaitable[tuple[dict[str, Any], bool]]]


async def ensure_search_price_ready(
    page: Page,
    search_url: str,
    *,
    reload_page: ReloadPage,
    timeout_ms: int,
    ready_wait_ms: int = 8_000,
    max_reloads: int = 2,
) -> tuple[Page, int]:
    reloads = 0
    cycle = 0
    while True:
        cycle += 1
        deadline = asyncio.get_running_loop().time() + max(1_000, ready_wait_ms) / 1000
        unavailable_since: float | None = None

        while asyncio.get_running_loop().time() < deadline:
            state = await search_surface_state(page)
            if state == "ready":
                print(f"price_surface_state=ready recovery_reloads={reloads}")
                return page, reloads
            if state == "closed":
                print("price_surface_state=target-closed")
                page = await reload_page(page, search_url, timeout_ms)
                break
            if state == "unavailable":
                if unavailable_since is None:
                    unavailable_since = time.monotonic()
                    print(f"price_unavailable_detected=True cycle={cycle}")
                if time.monotonic() - unavailable_since >= 0.45:
                    break
            else:
                unavailable_since = None
            await page.wait_for_timeout(100)

        if reloads >= max_reloads:
            raise GooglePriceUnavailableError(
                f"Google Flights still has no usable KRW price after {reloads} recovery reload(s)"
            )
        reloads += 1
        print(f"price_unavailable_recovery_reload={reloads}/{max_reloads}")
        page = await reload_page(page, search_url, timeout_ms)
        await page.wait_for_timeout(350)


async def prepare_cheapest_surface(
    page: Page,
    search_url: str,
    *,
    reload_page: ReloadPage,
    timeout_ms: int,
    selection_wait_ms: int = 25_000,
    ready_wait_ms: int = 8_000,
    recovery_reloads: int = 2,
    ensure_selected: EnsureSelected = ensure_cheapest_selected,
) -> tuple[Page, int]:
    """Canonical production + acceptance order.

    Cheapest first -> unconditional full reload once -> bounded Price unavailable
    recovery -> re-check Cheapest. Platform-specific page recovery is injected,
    but the behavioral state machine is shared by Windows acceptance and the
    production runtime used by Ubuntu/Docker.
    """

    print("runtime_stage=cheapest-warmup")
    _, warm_clicked = await ensure_selected(page, selection_wait_ms)
    print("cheapest_warmup_selected=True")
    print(f"cheapest_warmup_clicked={warm_clicked}")

    print("cheapest_selected_full_reload=1")
    page = await reload_page(page, search_url, timeout_ms)
    await page.wait_for_timeout(350)

    page, recovery_count = await ensure_search_price_ready(
        page,
        search_url,
        reload_page=reload_page,
        timeout_ms=timeout_ms,
        ready_wait_ms=ready_wait_ms,
        max_reloads=recovery_reloads,
    )
    page.set_default_timeout(timeout_ms)

    print("runtime_stage=cheapest-post-reload")
    _, post_clicked = await ensure_selected(page, selection_wait_ms)
    print("cheapest_post_reload_selected=True")
    print(f"cheapest_post_reload_reclicked={post_clicked}")
    print(f"price_recovery_reload_count={recovery_count}")
    return page, recovery_count
