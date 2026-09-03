from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .config import Settings
from .models import FlightOffer, WatchSlot


class ProviderError(RuntimeError):
    pass


class CaptchaDetectedError(ProviderError):
    pass


_KRW_RE = re.compile(r"₩\s*([0-9][0-9,]*)")
_WON_ARIA_RE = re.compile(r"([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)", re.I)
_AIRLINE_RE = re.compile(r"flight with ([^.]+)", re.I)
_FLIGHT_NO_RE = re.compile(r"\b([A-Z0-9]{2,3}\s?\d{2,4})\b")


def parse_krw_price(text: str | None) -> int | None:
    if not text:
        return None
    match = _KRW_RE.search(text) or _WON_ARIA_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


class GoogleFlightsPlaywrightProvider:
    """Google Flights rendered-browser provider.

    `fast-flights` is used only to generate Google's own `tfs` search URL.
    Playwright/Chromium then opens the real Google Flights page and reads the
    rendered flight rows. Separate-ticket/self-transfer itineraries are not
    hidden. Booking verification is attempted only when the caller asks for it
    (normally on a newly crossed target price).
    """

    name = "google-playwright"

    def __init__(self, settings: Settings, query_builder=None):
        self.settings = settings
        self._query_builder = query_builder or self._default_query_builder

    def _default_query_builder(self, slot: WatchSlot) -> str:
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
        joiner = "&" if "?" in query.url() else "?"
        return f"{query.url()}{joiner}gl={self.settings.google_gl}"

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
        try:
            await page.locator("li:has(div[aria-label^='From '])").first.wait_for(
                state="visible", timeout=self.settings.browser_timeout_ms
            )
        except PlaywrightTimeoutError as exc:
            body = (await page.locator("body").inner_text())[:1000]
            raise ProviderError(f"Google Flights result rows did not load: {body}") from exc

    async def _expand_results(self, page: Page) -> None:
        for label in ("View more flights", "More flights"):
            button = page.get_by_text(label, exact=False).last
            try:
                if await button.count() and await button.is_visible():
                    await button.click(timeout=2500)
                    await page.wait_for_timeout(800)
                    break
            except Exception:
                pass

    async def _rows(self, page: Page, *, nonstop_only: bool) -> list[dict]:
        locator = page.locator("li:has(div[aria-label^='From '])")
        rows: list[dict] = []
        for idx in range(await locator.count()):
            row = locator.nth(idx)
            try:
                text = await row.inner_text()
                desc_node = row.locator("div[aria-label^='From ']").first
                desc = (await desc_node.get_attribute("aria-label")) or ""
            except Exception:
                continue
            price = parse_krw_price(text)
            if price is None:
                price = parse_krw_price((await row.get_attribute("aria-label")) or "")
            if price is None:
                continue
            is_nonstop = "nonstop" in (text + " " + desc).lower()
            if nonstop_only and not is_nonstop:
                continue
            airline_match = _AIRLINE_RE.search(desc)
            airline = airline_match.group(1).strip() if airline_match else None
            flight_numbers = " / ".join(dict.fromkeys(_FLIGHT_NO_RE.findall(text + " " + desc))) or None
            rows.append(
                {
                    "locator": row,
                    "price": price,
                    "airline": airline,
                    "flight_numbers": flight_numbers,
                    "nonstop": is_nonstop,
                    "separate_ticket": "separate ticket" in text.lower() or "self-transfer" in text.lower(),
                    "text": text[:1500],
                    "description": desc[:1500],
                }
            )
        rows.sort(key=lambda item: item["price"])
        return rows

    async def _verify_booking(self, page: Page, outbound: dict, *, nonstop_only: bool) -> int | None:
        try:
            await outbound["locator"].click(timeout=7000)
            await page.wait_for_timeout(1200)
            await self._check_captcha(page)
            await self._wait_results(page)
            returns = await self._rows(page, nonstop_only=nonstop_only)
            if not returns:
                return None
            await returns[0]["locator"].click(timeout=7000)
            await page.wait_for_timeout(1500)
            await self._check_captcha(page)

            lowest = page.get_by_text("Lowest total price", exact=False).first
            if await lowest.count():
                container = lowest.locator("xpath=..")
                for _ in range(3):
                    text = await container.inner_text()
                    price = parse_krw_price(text)
                    if price:
                        return price
                    container = container.locator("xpath=..")

            prices: list[int] = []
            spans = page.locator("span[aria-label*='won' i], span[aria-label*='KRW' i]")
            for idx in range(await spans.count()):
                price = parse_krw_price((await spans.nth(idx).get_attribute("aria-label")) or "")
                if price:
                    prices.append(price)
            return min(prices) if prices else None
        except Exception:
            return None

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
            await self._expand_results(page)
            rows = await self._rows(page, nonstop_only=slot.nonstop)
            if not rows:
                raise ProviderError("Google Flights rendered no price-bearing flight rows")
            best = rows[0]
            await self._debug_screenshot(page, f"slot-{slot.id}-results.png")

            verified_price = None
            verified = False
            if verify_below_price is not None and best["price"] <= verify_below_price:
                verified_price = await self._verify_booking(page, best, nonstop_only=slot.nonstop)
                if verified_price is not None:
                    verified = True
                    await self._debug_screenshot(page, f"slot-{slot.id}-booking.png")

            total_price = verified_price if verified else best["price"]
            return FlightOffer(
                provider=self.name,
                origin=slot.origin,
                destination=slot.destination,
                depart_date=slot.depart_date,
                return_date=slot.return_date,
                total_price=total_price,
                currency=self.settings.google_currency,
                price_verified=verified,
                airline=best["airline"],
                outbound_flight=best["flight_numbers"],
                inbound_flight=None,
                carry_on="Google Flights 상세 확인 필요",
                checked_baggage="정보 확인 불가" if slot.checked_bag == 0 else f"요청 기준 {slot.checked_bag}개",
                booking_provider="Google Flights" if verified else None,
                booking_url=page.url,
                separate_ticket=best["separate_ticket"],
                nonstop=best["nonstop"],
                raw={"result_count": len(rows), "observed_price": best["price"], "row": best["text"]},
                fetched_at=datetime.now(timezone.utc),
            )
        except CaptchaDetectedError:
            if page:
                await self._debug_screenshot(page, f"slot-{slot.id}-captcha.png")
            raise
        except ProviderError:
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
