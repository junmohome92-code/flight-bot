from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Locator, Page

from .browser_session import PlaywrightBrowserSession
from .config import Settings
from .google_query import build_google_flights_search_url
from .google_results_flow import (
    GooglePriceUnavailableError,
    GoogleResultsFlowError,
    prepare_cheapest_surface,
)
from .google_ui_contract import flight_card_is_specific, parse_krw_prices
from .models import FlightOffer, WatchSlot


class ProviderError(RuntimeError):
    pass


class CaptchaDetectedError(ProviderError):
    pass


class PriceUnavailableError(ProviderError):
    pass


_FLIGHT_NO_RE = re.compile(r"\b([A-Z0-9]{2,3}\s?\d{2,4})\b")
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
    """Canonical Google Flights result-page observed-price provider.

    The Windows acceptance probe and the Ubuntu/Docker runtime now share the
    same query contract and Cheapest state machine. Platform-specific browser
    launch/recovery remains an adapter detail only.

    Product boundary:
    - round-trip price visibly shown by Google Flights,
    - explicit Nonstop/direct rows only by default,
    - configurable ranked direct rows in the notification,
    - exactly one user-facing URL: the Google Flights result page,
    - no Booking/OTA/checkout navigation.
    """

    name = "google-playwright-results-observed"
    accepted_for_alerts = True
    selection_wait_ms = 25_000
    ready_wait_ms = 8_000
    price_recovery_reloads = 2
    direct_settle_ms = 3_500

    def __init__(self, settings: Settings, query_builder=None, browser_session=None):
        self.settings = settings
        self._query_builder = query_builder or self._default_query_builder
        self._browser_session = browser_session or PlaywrightBrowserSession(settings)

    def _default_query_builder(self, slot: WatchSlot) -> str:
        # Do not put the nonstop filter into the TFS query. The exact accepted
        # result URL requests the normal round-trip surface; direct-only policy
        # is applied to concrete result rows after capture.
        return build_google_flights_search_url(
            origin=slot.origin,
            destination=slot.destination,
            depart_date=slot.depart_date,
            return_date=slot.return_date,
            language=self.settings.google_language,
            gl=self.settings.google_gl,
            currency=self.settings.google_currency,
        )

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

    async def _reload_page(self, page: Page, search_url: str, timeout_ms: int) -> Page:
        if not page.is_closed():
            try:
                await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                return page
            except Exception:
                if not page.is_closed():
                    raise

        replacement = await self._browser_session.new_page()
        await replacement.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print("runtime_page_recovery=opened-replacement")
        return replacement

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
            search_url = self.build_search_url(slot)
            print(f"runtime_search_start=slot-{slot.id} {slot.origin}->{slot.destination}")
            print(f"runtime_query_contract=accepted-tfs-v1")
            page = await self._browser_session.new_page()
            await page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=self.settings.browser_timeout_ms,
            )
            print(f"runtime_selection_url={page.url}")
            await self._check_captcha(page)

            try:
                page, recovery_count = await prepare_cheapest_surface(
                    page,
                    search_url,
                    reload_page=self._reload_page,
                    timeout_ms=self.settings.browser_timeout_ms,
                    selection_wait_ms=self.selection_wait_ms,
                    ready_wait_ms=self.ready_wait_ms,
                    recovery_reloads=self.price_recovery_reloads,
                )
            except GooglePriceUnavailableError as exc:
                raise PriceUnavailableError(str(exc)) from exc
            except GoogleResultsFlowError as exc:
                raise ProviderError(str(exc)) from exc

            await self._check_captcha(page)
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
                    "query_contract": "accepted-tfs-v1",
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
            raise ProviderError(f"Playwright Google Flights search failed: {exc}") from exc
        finally:
            if page:
                try:
                    await self._browser_session.release_page(page)
                except Exception:
                    pass
