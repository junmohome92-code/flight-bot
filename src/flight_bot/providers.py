from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Locator, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .config import Settings
from .models import FlightOffer, WatchSlot


class ProviderError(RuntimeError):
    pass


class CaptchaDetectedError(ProviderError):
    pass


class PriceUnavailableError(ProviderError):
    pass


_KRW_RE = re.compile(r"₩\s*([0-9][0-9,]*)")
_WON_ARIA_RE = re.compile(r"([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)", re.I)
_FLIGHT_NO_RE = re.compile(r"\b([A-Z0-9]{2,3}\s?\d{2,4})\b")


def parse_krw_price(text: str | None) -> int | None:
    if not text:
        return None
    match = _KRW_RE.search(text) or _WON_ARIA_RE.search(text)
    return int(match.group(1).replace(",", "")) if match else None


def parse_all_krw_prices(text: str | None) -> list[int]:
    if not text:
        return []
    values = [int(v.replace(",", "")) for v in _KRW_RE.findall(text)]
    values.extend(int(v.replace(",", "")) for v in _WON_ARIA_RE.findall(text))
    return sorted(set(values))


class GoogleFlightsPlaywrightProvider:
    """Render Google Flights in Chromium and extract the visible lowest price."""

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
        """Use stable visible section text rather than Google's volatile row DOM."""
        try:
            await page.get_by_text("Departing flights", exact=False).first.wait_for(
                state="visible", timeout=self.settings.browser_timeout_ms
            )
        except PlaywrightTimeoutError as exc:
            body = (await page.locator("body").inner_text())[:1500]
            raise ProviderError(f"Google Flights results did not load: {body}") from exc

    async def _select_cheapest_tab(self, page: Page) -> None:
        try:
            tab = page.get_by_text("Cheapest", exact=True).first
            if await tab.count() and await tab.is_visible():
                await tab.click(timeout=4000)
                await page.wait_for_timeout(1200)
        except Exception:
            pass

    async def _expand_results(self, page: Page) -> None:
        for label in ("View more flights", "More flights"):
            try:
                button = page.get_by_text(label, exact=False).last
                if await button.count() and await button.is_visible():
                    await button.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

    async def _price_anchor(self, page: Page, price: int) -> Locator | None:
        candidates = page.get_by_text(re.compile(rf"₩\s*{price:,}"))
        return candidates.first if await candidates.count() else None

    async def _nearest_clickable(self, anchor: Locator | None) -> Locator | None:
        if anchor is None:
            return None
        for xpath in (
            "ancestor::*[@role='button'][1]",
            "ancestor::*[@role='listitem'][1]",
            "ancestor::li[1]",
        ):
            candidate = anchor.locator(f"xpath={xpath}")
            if await candidate.count():
                return candidate.first
        return None

    async def _extract_best(self, page: Page, slot: WatchSlot) -> dict:
        await self._select_cheapest_tab(page)
        await self._expand_results(page)
        body = await page.locator("body").inner_text()
        prices = parse_all_krw_prices(body)
        if not prices:
            if "price unavailable" in body.lower():
                raise PriceUnavailableError(
                    "Google Flights loaded the route but returned Price unavailable for this IP/session"
                )
            raise ProviderError("Google Flights loaded results but no KRW price was found")

        price = min(prices)
        anchor = await self._price_anchor(page, price)
        clickable = await self._nearest_clickable(anchor)
        row_text = ""
        if clickable is not None:
            try:
                row_text = await clickable.inner_text()
            except Exception:
                pass
        if not row_text and anchor is not None:
            try:
                row_text = await anchor.locator("xpath=ancestor::div[1]").inner_text()
            except Exception:
                pass

        lower = row_text.lower()
        if slot.nonstop and row_text and "nonstop" not in lower:
            raise ProviderError("nonstop slot resolved to a non-nonstop candidate")

        airline = None
        for line in (line.strip() for line in row_text.splitlines() if line.strip()):
            low = line.lower()
            if any(token in low for token in ("airlines", "airways", "aero", "jeju", "t'way", "eastar", "jin air", "korean air")):
                airline = line
                break

        return {
            "locator": clickable,
            "price": price,
            "airline": airline,
            "flight_numbers": " / ".join(dict.fromkeys(_FLIGHT_NO_RE.findall(row_text))) or None,
            "nonstop": "nonstop" in lower if row_text else None,
            "separate_ticket": "separate ticket" in lower or "self-transfer" in lower,
            "text": row_text[:2000],
            "page_price_count": len(prices),
        }

    async def _verify_booking(self, page: Page, best: dict) -> int | None:
        """Best-effort final-price verification; fail closed if UI navigation changes."""
        locator = best.get("locator")
        if locator is None:
            return None
        try:
            await locator.click(timeout=7000)
            await page.wait_for_timeout(1500)
            await self._check_captcha(page)
            await self._wait_results(page)
            body = await page.locator("body").inner_text()
            prices = parse_all_krw_prices(body)
            if not prices:
                return None
            return_price = min(prices)
            anchor = await self._price_anchor(page, return_price)
            return_locator = await self._nearest_clickable(anchor)
            if return_locator is None:
                return None
            await return_locator.click(timeout=7000)
            await page.wait_for_timeout(1800)
            await self._check_captcha(page)
            body = await page.locator("body").inner_text()
            marker = body.lower().find("lowest total price")
            if marker >= 0:
                nearby = body[marker:marker + 1500]
                nearby_prices = parse_all_krw_prices(nearby)
                if nearby_prices:
                    return min(nearby_prices)
            all_prices = parse_all_krw_prices(body)
            return min(all_prices) if all_prices else None
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
            best = await self._extract_best(page, slot)
            await self._debug_screenshot(page, f"slot-{slot.id}-results.png")

            verified_price = None
            verified = False
            if verify_below_price is not None and best["price"] <= verify_below_price:
                verified_price = await self._verify_booking(page, best)
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
                carry_on="Google Flights 상세 확인 필요",
                checked_baggage="정보 확인 불가" if slot.checked_bag == 0 else f"요청 기준 {slot.checked_bag}개",
                booking_provider="Google Flights" if verified else None,
                booking_url=page.url,
                separate_ticket=best["separate_ticket"],
                nonstop=best["nonstop"],
                raw={
                    "page_price_count": best["page_price_count"],
                    "observed_price": best["price"],
                    "row": best["text"],
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
