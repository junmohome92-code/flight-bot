from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Locator, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .config import Settings
from .google_ui_contract import flight_card_is_specific, parse_krw_prices
from .models import FlightOffer, WatchSlot


class ProviderError(RuntimeError):
    pass


class CaptchaDetectedError(ProviderError):
    pass


class PriceUnavailableError(ProviderError):
    pass


_FLIGHT_NO_RE = re.compile(r"\b([A-Z0-9]{2,3}\s?\d{2,4})\b")
_CHEAPEST_RE = re.compile(r"^\s*(?:Cheapest\b|최저가)", re.I)
_KRW_TEXT_RE = re.compile(r"₩\s*[0-9][0-9,]*")


def parse_krw_price(text: str | None) -> int | None:
    values = parse_krw_prices(text)
    return values[0] if values else None


def parse_all_krw_prices(text: str | None) -> list[int]:
    return parse_krw_prices(text)


class GoogleFlightsPlaywrightProvider:
    """Legacy runtime provider kept fail-closed until the UI acceptance gate passes.

    Important boundaries:
    - It may return a row-scoped Google *observed* price.
    - It must never use a page-wide KRW minimum.
    - It must never set ``price_verified=True``.  The project verification
      contract requires an external seller checkout/final-total check, which is
      not implemented in this legacy provider.

    The accepted transient/pointer flow is being validated separately before
    replacing this class.
    """

    name = "google-playwright-legacy-unverified"
    accepted_for_alerts = False

    def __init__(self, settings: Settings, query_builder=None):
        self.settings = settings
        self._query_builder = query_builder or self._default_query_builder

    def _default_query_builder(self, slot: WatchSlot) -> str:
        # Kept only for the legacy runtime until the accepted browser-side query
        # builder replaces it.  fast-flights is not trusted as a price parser.
        try:
            from fast_flights import FlightQuery, Passengers, create_query
        except ImportError as exc:
            raise ProviderError("fast-flights is not installed") from exc

        max_stops = 0 if slot.nonstop else None
        query = create_query(
            flights=[
                FlightQuery(
                    date=slot.depart_date,
                    from_airport=slot.origin,
                    to_airport=slot.destination,
                    max_stops=max_stops,
                ),
                FlightQuery(
                    date=slot.return_date,
                    from_airport=slot.destination,
                    to_airport=slot.origin,
                    max_stops=max_stops,
                ),
            ],
            seat="economy",
            trip="round-trip",
            passengers=Passengers(adults=1),
            language=self.settings.google_language,
            currency=self.settings.google_currency,
            max_stops=max_stops,
            checked_bags=max(0, slot.checked_bag),
            hide_separate_and_self_transfer=False,
        )
        url = query.url()
        return f"{url}{'&' if '?' in url else '?'}gl={self.settings.google_gl}"

    def build_search_url(self, slot: WatchSlot) -> str:
        return self._query_builder(slot)

    async def _setup(self):
        playwright = await async_playwright().start()
        browser: Browser = await playwright.chromium.launch(
            headless=self.settings.browser_headless,
            args=["--disable-dev-shm-usage"],
        )
        context: BrowserContext = await browser.new_context(
            locale="en-US",
            timezone_id=self.settings.timezone,
            viewport={"width": 1365, "height": 900},
        )
        if self.settings.browser_block_assets:

            async def route_handler(route):
                if route.request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_handler)
        page = await context.new_page()
        page.set_default_timeout(self.settings.browser_timeout_ms)
        return playwright, browser, context, page

    async def _check_captcha(self, page: Page) -> None:
        url = page.url.lower()
        title = (await page.title()).lower()
        if "/sorry/" in url or "unusual traffic" in title:
            raise CaptchaDetectedError("Google CAPTCHA / unusual-traffic page detected")
        if await page.locator("iframe[src*='recaptcha'], div.g-recaptcha, div#recaptcha").count():
            raise CaptchaDetectedError("Google reCAPTCHA detected")

    async def _wait_results(self, page: Page) -> None:
        deadline_ms = self.settings.browser_timeout_ms
        try:
            await page.get_by_text(
                re.compile(r"Departing flights|출발 항공편|Top departing flights|인기 출발 항공편", re.I)
            ).first.wait_for(state="visible", timeout=deadline_ms)
        except PlaywrightTimeoutError as exc:
            body = (await page.locator("body").inner_text())[:1500]
            if "price unavailable" in body.lower() or "가격 정보를 이용할 수" in body:
                raise PriceUnavailableError(
                    "Google Flights loaded the route but returned Price unavailable for this IP/session"
                ) from exc
            raise ProviderError(f"Google Flights results did not load: {body}") from exc

    async def _select_cheapest_tab(self, page: Page) -> None:
        for locator in (
            page.get_by_role("tab", name=_CHEAPEST_RE),
            page.get_by_role("button", name=_CHEAPEST_RE),
            page.get_by_text(_CHEAPEST_RE),
        ):
            try:
                for index in range(await locator.count()):
                    item = locator.nth(index)
                    if await item.is_visible():
                        await item.click(timeout=4000)
                        await page.wait_for_timeout(900)
                        return
            except Exception:
                continue

    async def _row_text_for_price_element(self, item: Locator) -> str:
        try:
            return str(
                await item.evaluate(
                    """el => {
                        let node = el;
                        for (let depth = 0; depth < 14 && node; depth += 1, node = node.parentElement) {
                            const text = (node.innerText || node.textContent || '').trim();
                            if (!text || text.length > 1800) continue;
                            const normalized = text.replace(/[–—]/g, '-').replace(/\s+/g, ' ').toUpperCase();
                            const times = text.match(/\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi) || [];
                            const routeCount = normalized.split('CJJ-TPE').length - 1;
                            const shape = /nonstop|stops?|직항|경유|\bhr\b|시간/i.test(text);
                            if (times.length >= 2 && times.length <= 4 && routeCount <= 1 && shape) return text;
                        }
                        return '';
                    }"""
                )
            )
        except Exception:
            return ""

    async def _row_candidates(self, page: Page, slot: WatchSlot) -> list[dict]:
        found: dict[tuple[int, str], dict] = {}

        labelled = page.locator("[aria-label]")
        for index in range(await labelled.count()):
            item = labelled.nth(index)
            try:
                label = await item.get_attribute("aria-label")
            except Exception:
                continue
            values = parse_krw_prices(label)
            if not values:
                continue
            row_text = (await self._row_text_for_price_element(item)).strip()
            if not flight_card_is_specific(row_text, slot.origin, slot.destination):
                continue
            for price in values:
                found[(price, row_text)] = {"price": price, "text": row_text, "source": "aria-label"}

        visible = page.get_by_text(_KRW_TEXT_RE)
        for index in range(await visible.count()):
            item = visible.nth(index)
            try:
                if not await item.is_visible():
                    continue
                own = (await item.inner_text()).strip()
            except Exception:
                continue
            values = parse_krw_prices(own)
            if not values:
                continue
            row_text = (await self._row_text_for_price_element(item)).strip()
            if not flight_card_is_specific(row_text, slot.origin, slot.destination):
                continue
            for price in values:
                found[(price, row_text)] = {"price": price, "text": row_text, "source": "visible-text"}

        return sorted(found.values(), key=lambda item: int(item["price"]))

    async def _extract_best(self, page: Page, slot: WatchSlot) -> dict:
        await self._select_cheapest_tab(page)
        candidates = await self._row_candidates(page, slot)
        if not candidates:
            body = await page.locator("body").inner_text()
            if "price unavailable" in body.lower() or "가격 정보를 이용할 수" in body:
                raise PriceUnavailableError(
                    "Google Flights loaded the route but returned Price unavailable for this IP/session"
                )
            raise ProviderError("Google Flights loaded results but no row-scoped KRW flight price was found")

        best = candidates[0]
        row_text = str(best["text"])
        lower = row_text.lower()
        if slot.nonstop and "nonstop" not in lower and "직항" not in row_text:
            raise ProviderError("nonstop slot resolved to a non-nonstop candidate")

        airline = None
        ignored = {"round trip", "nonstop", "price unavailable"}
        for line in (line.strip() for line in row_text.splitlines() if line.strip()):
            low = line.lower()
            if low in ignored:
                continue
            if any(
                token in low
                for token in (
                    "airlines",
                    "airways",
                    "aero",
                    "jeju",
                    "t'way",
                    "eastar",
                    "jin air",
                    "korean air",
                    "asiana",
                )
            ):
                airline = line
                break

        return {
            "price": int(best["price"]),
            "airline": airline,
            "flight_numbers": " / ".join(dict.fromkeys(_FLIGHT_NO_RE.findall(row_text))) or None,
            "nonstop": ("nonstop" in lower or "직항" in row_text),
            "separate_ticket": "separate ticket" in lower or "self-transfer" in lower,
            "text": row_text[:2000],
            "row_price_count": len(candidates),
            "source": best["source"],
        }

    async def _debug_screenshot(self, page: Page, name: str) -> None:
        if not self.settings.browser_debug_dir:
            return
        path = Path(self.settings.browser_debug_dir)
        path.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(path / name), full_page=True)
        except Exception:
            pass

    async def search(self, slot: WatchSlot, *, verify_below_price: int | None = None) -> FlightOffer:
        playwright = browser = context = page = None
        try:
            playwright, browser, context, page = await self._setup()
            await page.goto(self.build_search_url(slot), wait_until="domcontentloaded")
            await self._check_captcha(page)
            await self._wait_results(page)
            best = await self._extract_best(page, slot)
            await self._debug_screenshot(page, f"slot-{slot.id}-results.png")

            verification_requested = verify_below_price is not None and best["price"] <= verify_below_price
            # Fail closed.  Google Booking options are not the project's
            # verification boundary; an external seller checkout/final total is.
            verified = False

            return FlightOffer(
                provider=self.name,
                origin=slot.origin,
                destination=slot.destination,
                depart_date=slot.depart_date,
                return_date=slot.return_date,
                total_price=best["price"],
                currency=self.settings.google_currency,
                price_verified=verified,
                airline=best["airline"],
                outbound_flight=best["flight_numbers"],
                carry_on="정보 확인 불가",
                checked_baggage="정보 확인 불가",
                booking_provider=None,
                booking_url=page.url,
                separate_ticket=best["separate_ticket"],
                nonstop=best["nonstop"],
                raw={
                    "observed_price": best["price"],
                    "row": best["text"],
                    "row_price_count": best["row_price_count"],
                    "price_source": best["source"],
                    "verification_requested": verification_requested,
                    "verification_status": "external_checkout_not_implemented",
                    "accepted_for_alerts": self.accepted_for_alerts,
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
            raise ProviderError(f"Playwright Google Flights search failed: {exc}") from exc
        finally:
            if page:
                await page.close()
            if context:
                await context.close()
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
