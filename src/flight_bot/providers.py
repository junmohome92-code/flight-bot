from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .browser_session import PlaywrightBrowserSession
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
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b", re.I)
_STOP_RE = re.compile(r"\b\d+\s*stops?\b|\bstops?\b|경유", re.I)


def parse_krw_price(text: str | None) -> int | None:
    values = parse_krw_prices(text)
    return values[0] if values else None


def parse_all_krw_prices(text: str | None) -> list[int]:
    return parse_krw_prices(text)


def is_nonstop_row(text: str | None) -> bool:
    """Return True only when Google explicitly marks the row as nonstop/direct."""
    value = text or ""
    if "직항" in value:
        return True
    lower = value.lower()
    if "nonstop" in lower:
        return True
    if _STOP_RE.search(value):
        return False
    return False


def _airline_from_row(row_text: str) -> str | None:
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
                "tway",
                "eastar",
                "jin air",
                "korean air",
                "asiana",
            )
        ):
            return line
    return None


def summarize_candidate(candidate: dict) -> dict:
    row_text = str(candidate.get("text") or "")
    times: list[str] = []
    for value in _TIME_RE.findall(row_text):
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized not in times:
            times.append(normalized)
        if len(times) >= 2:
            break
    return {
        "price": int(candidate["price"]),
        "airline": _airline_from_row(row_text),
        "flight_numbers": " / ".join(dict.fromkeys(_FLIGHT_NO_RE.findall(row_text))) or None,
        "times": times,
        "nonstop": is_nonstop_row(row_text),
        "text": row_text[:2000],
    }


def rank_alert_candidates(candidates: list[dict], *, nonstop_only: bool, limit: int) -> list[dict]:
    """Rank concrete Google rows for notification without inventing missing rows."""
    ranked: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for candidate in sorted(candidates, key=lambda item: int(item["price"])):
        summary = summarize_candidate(candidate)
        if nonstop_only and not summary["nonstop"]:
            continue
        key = (int(summary["price"]), str(summary.get("text") or ""))
        if key in seen:
            continue
        seen.add(key)
        ranked.append(summary)
        if len(ranked) >= max(1, int(limit)):
            break
    return ranked


class GoogleFlightsPlaywrightProvider:
    """Google Flights result-page observed-price provider.

    Product boundary:
    - The alert price is the round-trip price visibly shown by Google Flights.
    - Stop/connection rows are excluded by default through ``ALERT_NONSTOP_ONLY``.
    - The notification may show several ranked direct rows, controlled by
      ``ALERT_MAX_OFFERS``.
    - The only user-facing URL is the Google Flights search-result page.
    - Booking options, OTA links and external checkout are intentionally outside
      the current product scope, so ``price_verified`` remains False.
    """

    name = "google-playwright-results-observed"
    accepted_for_alerts = True

    def __init__(self, settings: Settings, query_builder=None, browser_session=None):
        self.settings = settings
        self._query_builder = query_builder or self._default_query_builder
        self._browser_session = browser_session or PlaywrightBrowserSession(settings)

    def _default_query_builder(self, slot: WatchSlot) -> str:
        # fast-flights is URL-builder-only. Its parser is never trusted as a
        # price source; all prices come from concrete Google result rows.
        try:
            from fast_flights import FlightQuery, Passengers, create_query
        except ImportError as exc:
            raise ProviderError("fast-flights is not installed") from exc

        max_stops = 0 if (self.settings.alert_nonstop_only or slot.nonstop) else None
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

    async def close(self) -> None:
        await self._browser_session.close()

    async def _check_captcha(self, page: Page) -> None:
        url = page.url.lower()
        title = (await page.title()).lower()
        if "/sorry/" in url or "unusual traffic" in title:
            raise CaptchaDetectedError("Google CAPTCHA / unusual-traffic page detected")
        if await page.locator("iframe[src*='recaptcha'], div.g-recaptcha, div#recaptcha").count():
            raise CaptchaDetectedError("Google reCAPTCHA detected")

    async def _wait_results(self, page: Page) -> None:
        try:
            await page.get_by_text(
                re.compile(r"Departing flights|출발 항공편|Top departing flights|인기 출발 항공편", re.I)
            ).first.wait_for(state="visible", timeout=self.settings.browser_timeout_ms)
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
                    if not await item.is_visible():
                        continue
                    try:
                        selected_before = await item.evaluate(
                            """el => {
                                const host = el.closest('[role="tab"], button, [role="button"]') || el;
                                return host.getAttribute('aria-selected') === 'true' ||
                                       host.getAttribute('aria-pressed') === 'true';
                            }"""
                        )
                    except Exception:
                        selected_before = False
                    if not selected_before:
                        await item.click(timeout=4000)
                    for _ in range(40):
                        try:
                            selected = await item.evaluate(
                                """el => {
                                    const host = el.closest('[role="tab"], button, [role="button"]') || el;
                                    return host.getAttribute('aria-selected') === 'true' ||
                                           host.getAttribute('aria-pressed') === 'true';
                                }"""
                            )
                        except Exception:
                            selected = False
                        if selected:
                            return
                        await page.wait_for_timeout(50)
            except Exception:
                continue
        raise ProviderError("Google Flights Cheapest/최저가 tab could not be selected")

    async def _row_text_for_price_element(self, item: Locator, slot: WatchSlot) -> str:
        try:
            return str(
                await item.evaluate(
                    r"""(el, route) => {
                        let node = el;
                        const forwardToken = `${route.origin}-${route.destination}`.toUpperCase();
                        const reverseToken = `${route.destination}-${route.origin}`.toUpperCase();
                        for (let depth = 0; depth < 14 && node; depth += 1, node = node.parentElement) {
                            const text = (node.innerText || node.textContent || '').trim();
                            if (!text || text.length > 1800) continue;
                            const normalized = text.replace(/[–—‑−]/g, '-').replace(/\s+/g, ' ').toUpperCase();
                            const times = text.match(/\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi) || [];
                            const forwardCount = normalized.split(forwardToken).length - 1;
                            const reverseCount = normalized.split(reverseToken).length - 1;
                            const shape = /nonstop|stops?|직항|경유|\bhr\b|시간/i.test(text);
                            const broad = /flight search|search results|all filters|top departing flights|other departing flights/i.test(text);
                            if (!broad && times.length >= 2 && times.length <= 4 && forwardCount === 1 && reverseCount === 0 && shape) {
                                return text;
                            }
                        }
                        return '';
                    }""",
                    {"origin": slot.origin.upper(), "destination": slot.destination.upper()},
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
            row_text = (await self._row_text_for_price_element(item, slot)).strip()
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
            row_text = (await self._row_text_for_price_element(item, slot)).strip()
            if not flight_card_is_specific(row_text, slot.origin, slot.destination):
                continue
            for price in values:
                found[(price, row_text)] = {"price": price, "text": row_text, "source": "visible-text"}

        return sorted(found.values(), key=lambda item: int(item["price"]))

    async def _extract_best(self, page: Page, slot: WatchSlot) -> dict:
        candidates = await self._row_candidates(page, slot)
        if not candidates:
            body = await page.locator("body").inner_text()
            if "price unavailable" in body.lower() or "가격 정보를 이용할 수" in body:
                raise PriceUnavailableError(
                    "Google Flights loaded the route but returned Price unavailable for this IP/session"
                )
            raise ProviderError("Google Flights loaded results but no row-scoped KRW flight price was found")

        display = rank_alert_candidates(
            candidates,
            nonstop_only=self.settings.alert_nonstop_only,
            limit=self.settings.alert_max_offers,
        )
        if not display:
            raise ProviderError("Google Flights loaded results but no explicit nonstop/direct row was found")

        best = display[0]
        return {
            "price": int(best["price"]),
            "airline": best.get("airline"),
            "flight_numbers": best.get("flight_numbers"),
            "nonstop": bool(best.get("nonstop")),
            "separate_ticket": "separate ticket" in str(best.get("text") or "").lower()
            or "self-transfer" in str(best.get("text") or "").lower(),
            "text": str(best.get("text") or "")[:2000],
            "candidate_count": len(candidates),
            "display_offers": display,
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
        page: Page | None = None
        try:
            page = await self._browser_session.new_page()
            search_url = self.build_search_url(slot)
            await page.goto(search_url, wait_until="domcontentloaded")
            await self._check_captcha(page)
            await self._wait_results(page)

            # Live Windows acceptance showed that Cheapest can be selected while
            # rows are still "Fetching results". Selecting Cheapest first and
            # then doing one full refresh reliably materializes the price rows.
            await self._select_cheapest_tab(page)
            await page.reload(wait_until="domcontentloaded", timeout=self.settings.browser_timeout_ms)
            await self._check_captcha(page)
            await self._wait_results(page)
            await self._select_cheapest_tab(page)

            best = await self._extract_best(page, slot)
            await self._debug_screenshot(page, f"slot-{slot.id}-results.png")

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
                try:
                    await page.close()
                except Exception:
                    pass
