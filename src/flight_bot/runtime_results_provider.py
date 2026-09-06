from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import Locator, Page

from .models import FlightOffer, WatchSlot
from .providers import (
    CaptchaDetectedError,
    GoogleFlightsPlaywrightProvider,
    PriceUnavailableError,
    ProviderError,
)


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


class RuntimeGoogleResultsProvider(GoogleFlightsPlaywrightProvider):
    """Production Google-results provider using the live-accepted Cheapest flow.

    The previous runtime implementation had a simplified Cheapest selector. On
    real Google Flights that could fail before the forced refresh and then the
    normal ``finally`` block closed the page, which looked like the browser just
    opened and disappeared. This provider mirrors the proven acceptance order:

    1. wait for a real interactive Cheapest control,
    2. click it and require strong selected-state evidence,
    3. full reload exactly once,
    4. recover transient Price unavailable with at most two extra reloads,
    5. re-check/re-click Cheapest only if the reload reset it,
    6. let the direct rows settle before reading row-scoped prices.

    Body-wide KRW text is used only as a readiness signal. Candidate prices still
    come only from the inherited row-scoped flight-card extractor.
    """

    name = "google-playwright-results-observed-accepted-flow"
    accepted_for_alerts = True
    selection_wait_ms = 25_000
    ready_wait_ms = 8_000
    price_recovery_reloads = 2
    direct_settle_ms = 3_500

    async def _control_state(self, locator: Locator) -> dict[str, Any]:
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

    async def _candidate_locators(self, page: Page) -> list[Locator]:
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
            state = await self._control_state(item)
            if state.get("hostInteractive"):
                locators.append(item)
        return locators

    async def _selected_cheapest_state(self, page: Page) -> dict[str, Any] | None:
        for locator in await self._candidate_locators(page):
            try:
                if not await locator.is_visible():
                    continue
            except Exception:
                continue
            state = await self._control_state(locator)
            if state.get("isSelected") and _CHEAPEST_RE.search(str(state.get("text") or "")):
                return state
        return None

    async def _visible_cheapest_control(self, page: Page) -> tuple[Locator | None, dict[str, Any]]:
        for locator in await self._candidate_locators(page):
            try:
                if not await locator.is_visible():
                    continue
            except Exception:
                continue
            state = await self._control_state(locator)
            if state.get("hostInteractive") and _CHEAPEST_RE.search(str(state.get("text") or "")):
                return locator, state
        return None, {}

    async def _ensure_cheapest_selected(self, page: Page) -> bool:
        selected = await self._selected_cheapest_state(page)
        if selected is not None:
            print("runtime_cheapest_found=True")
            print("runtime_cheapest_clicked=False")
            print(f"runtime_cheapest_selected_by={selected.get('selectedBy')}")
            return False

        deadline = asyncio.get_running_loop().time() + self.selection_wait_ms / 1000
        control: Locator | None = None
        before: dict[str, Any] = {}
        while asyncio.get_running_loop().time() < deadline and control is None:
            control, before = await self._visible_cheapest_control(page)
            if control is None:
                await page.wait_for_timeout(100)

        if control is None:
            raise ProviderError("runtime Cheapest/최저가 interactive control was not found within 25s")

        print(f"runtime_cheapest_control={str(before.get('text') or '')[:240]}")
        await control.click(timeout=5_000)
        print("runtime_cheapest_clicked=True")

        selected_deadline = time.monotonic() + 5.0
        while time.monotonic() < selected_deadline:
            selected = await self._selected_cheapest_state(page)
            if selected is not None:
                print("runtime_cheapest_selected=True")
                print(f"runtime_cheapest_selected_by={selected.get('selectedBy')}")
                return True
            await page.wait_for_timeout(50)

        raise ProviderError("runtime Cheapest/최저가 was clicked but no strong selected-state evidence appeared")

    async def _surface_state(self, page: Page) -> str:
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

    async def _reload_or_reopen(self, page: Page, search_url: str) -> Page:
        if not page.is_closed():
            try:
                await page.reload(
                    wait_until="domcontentloaded",
                    timeout=self.settings.browser_timeout_ms,
                )
                return page
            except Exception:
                if not page.is_closed():
                    raise

        replacement = await self._browser_session.new_page()
        await replacement.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=self.settings.browser_timeout_ms,
        )
        print("runtime_page_recovery=opened-replacement")
        return replacement

    async def _ensure_price_ready(self, page: Page, search_url: str) -> tuple[Page, int]:
        reloads = 0
        cycle = 0
        while True:
            cycle += 1
            deadline = asyncio.get_running_loop().time() + self.ready_wait_ms / 1000
            unavailable_since: float | None = None

            while asyncio.get_running_loop().time() < deadline:
                state = await self._surface_state(page)
                if state == "ready":
                    print(f"runtime_price_surface=ready recovery_reloads={reloads}")
                    return page, reloads
                if state == "closed":
                    page = await self._reload_or_reopen(page, search_url)
                    break
                if state == "unavailable":
                    if unavailable_since is None:
                        unavailable_since = time.monotonic()
                        print(f"runtime_price_unavailable=True cycle={cycle}")
                    if time.monotonic() - unavailable_since >= 0.45:
                        break
                else:
                    unavailable_since = None
                await page.wait_for_timeout(100)

            if reloads >= self.price_recovery_reloads:
                raise PriceUnavailableError(
                    f"Google Flights still has no usable KRW price after {reloads} recovery reload(s)"
                )
            reloads += 1
            print(f"runtime_price_recovery_reload={reloads}/{self.price_recovery_reloads}")
            page = await self._reload_or_reopen(page, search_url)
            await page.wait_for_timeout(350)

    async def search(self, slot: WatchSlot, *, verify_below_price: int | None = None) -> FlightOffer:
        page: Page | None = None
        try:
            print(f"runtime_search_start=slot-{slot.id} {slot.origin}->{slot.destination}")
            page = await self._browser_session.new_page()
            search_url = self.build_search_url(slot)
            await page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=self.settings.browser_timeout_ms,
            )
            print(f"runtime_selection_url={page.url}")
            await self._check_captcha(page)

            print("runtime_stage=cheapest-warmup")
            await self._ensure_cheapest_selected(page)
            await self._debug_screenshot(page, f"slot-{slot.id}-cheapest-before-refresh.png")

            print("runtime_cheapest_selected_full_reload=1")
            page = await self._reload_or_reopen(page, search_url)
            await page.wait_for_timeout(350)
            await self._check_captcha(page)

            page, recovery_count = await self._ensure_price_ready(page, search_url)
            await self._check_captcha(page)

            print("runtime_stage=cheapest-post-reload")
            post_clicked = await self._ensure_cheapest_selected(page)
            print(f"runtime_cheapest_post_reload_reclicked={post_clicked}")
            print(f"runtime_price_recovery_reload_count={recovery_count}")

            print(f"runtime_direct_settle_ms={self.direct_settle_ms}")
            await page.wait_for_timeout(self.direct_settle_ms)
            best = await self._extract_best(page, slot)
            await self._debug_screenshot(page, f"slot-{slot.id}-results.png")
            print(f"runtime_direct_offer_count={len(best['display_offers'])}")
            print(f"runtime_lowest_direct_round_trip={best['price']}")

            return FlightOffer(
                provider=self.name,
                origin=slot.origin,
                destination=slot.destination,
                depart_date=slot.depart_date,
                return_date=slot.return_date,
                total_price=best["price"],
                observed_price_value=best["price"],
                currency=self.settings.google_currency,
                price_verified=False,
                verified_checkout_price=None,
                verification_status="google_flights_displayed_round_trip",
                airline=best["airline"],
                outbound_flight=best["flight_numbers"],
                carry_on="정보 확인 불가",
                checked_baggage="정보 확인 불가",
                booking_provider=None,
                booking_url=None,
                result_url=search_url,
                display_offers=best["display_offers"],
                separate_ticket=best["separate_ticket"],
                nonstop=best["nonstop"],
                raw={
                    "observed_price": best["price"],
                    "row": best["text"],
                    "row_candidate_count": best["candidate_count"],
                    "display_offer_count": len(best["display_offers"]),
                    "alert_nonstop_only": self.settings.alert_nonstop_only,
                    "alert_max_offers": self.settings.alert_max_offers,
                    "verification_status": "google_flights_displayed_round_trip",
                    "accepted_for_alerts": self.accepted_for_alerts,
                    "cheapest_selected_full_reload": 1,
                    "price_recovery_reload_count": recovery_count,
                },
                fetched_at=datetime.now(timezone.utc),
            )
        except (CaptchaDetectedError, PriceUnavailableError, ProviderError):
            if page:
                await self._debug_screenshot(page, f"slot-{slot.id}-error.png")
            raise
        except Exception as exc:
            if page:
                await self._debug_screenshot(page, f"slot-{slot.id}-error.png")
            raise ProviderError(f"accepted-flow Google Flights search failed: {exc}") from exc
        finally:
            if page:
                try:
                    await self._browser_session.release_page(page)
                except Exception:
                    pass
