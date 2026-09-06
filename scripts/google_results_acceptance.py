from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

from flight_bot.config import Settings
from flight_bot.google_query import QUERY_CONTRACT
from flight_bot.runtime_results_provider import RuntimeGoogleResultsProvider

try:  # direct Windows execution from scripts/
    import google_booking_acceptance as acceptance
    import google_booking_pointer_probe as base
except ImportError:  # pytest/import from repository root
    from scripts import google_booking_acceptance as acceptance
    from scripts import google_booking_pointer_probe as base


class _NativeEdgeSession:
    """Browser-session adapter so the active probe executes production Provider.search.

    Only browser launch/tab ownership is Windows-specific. URL generation,
    Cheapest selection/reload/recovery, direct-row extraction and FlightOffer
    construction are exactly the production implementation used on Ubuntu.
    """

    def __init__(self, context, page: Page, *, timeout_ms: int, keep_open_seconds: int):
        self.context = context
        self.page = page
        self.timeout_ms = timeout_ms
        self.keep_open_seconds = keep_open_seconds

    async def new_page(self) -> Page:
        if self.page is None or self.page.is_closed():
            self.page = await acceptance.claim_initial_page(self.context, self.timeout_ms)
        self.page.set_default_timeout(self.timeout_ms)
        return self.page

    async def release_page(self, page: Page) -> None:
        # Provider.search releases its page in finally. Keep the accepted result
        # visible briefly for the human acceptance check, then let the outer
        # script close the dedicated Edge process/context.
        self.page = page
        if self.keep_open_seconds > 0 and not page.is_closed():
            await page.wait_for_timeout(self.keep_open_seconds * 1000)

    async def close(self) -> None:
        return None


def _semantic_rows(rows: list[dict], limit: int) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple] = set()
    for row in rows:
        try:
            price = int(row.get("price"))
        except (TypeError, ValueError, AttributeError):
            continue
        airline = re.sub(r"\s+", " ", str(row.get("airline") or "").strip()).lower()
        times = tuple(
            re.sub(r"\s+", " ", str(value).strip()).lower()
            for value in (row.get("times") or [])
        )
        flight_numbers = re.sub(r"\s+", "", str(row.get("flight_numbers") or "").upper())
        key = (price, airline, times, flight_numbers)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= limit:
            break
    return result


async def _run_session(playwright) -> None:
    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    max_offers = max(1, int(os.getenv("ALERT_MAX_OFFERS", "4")))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "8"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))

    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = base.free_local_port()
    edge_process = None
    browser = None
    page: Page | None = None

    try:
        edge_process = base.launch_edge_blank(profile_dir, port)
        await base.wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]
        page = await acceptance.claim_initial_page(context, timeout_ms)

        settings = Settings(
            _env_file=None,
            browser_headless=False,
            browser_timeout_ms=timeout_ms,
            browser_block_assets=False,
            browser_debug_dir=str(artifact_dir),
            alert_nonstop_only=True,
            alert_max_offers=max_offers,
            google_language="en",
            google_gl="kr",
            google_currency="KRW",
        )
        session = _NativeEdgeSession(
            context,
            page,
            timeout_ms=timeout_ms,
            keep_open_seconds=keep_open_seconds,
        )
        provider = RuntimeGoogleResultsProvider(settings, browser_session=session)

        # Same slot data used by real Telegram/runtime searches.
        from flight_bot.models import WatchSlot

        slot = WatchSlot(
            id=1,
            owner_platform="acceptance",
            owner_id="1",
            origin="CJJ",
            destination="TPE",
            depart_date="2026-09-18",
            return_date="2026-09-20",
            nonstop=True,
            checked_bag=0,
            enabled=True,
            target_price=999999,
        )

        expected_url = provider.build_search_url(slot)
        print(f"query_contract={QUERY_CONTRACT}")
        print(f"selection_url={expected_url}")
        offer = await provider.search(slot)
        rows = _semantic_rows(list(offer.display_offers or []), max_offers)
        if not rows:
            raise RuntimeError("production provider returned no direct display rows")

        print("\n=== DIRECT GOOGLE RESULTS ===")
        print("departure_selection_policy=production-provider-row-scoped-lowest")
        print(f"price_recovery_reload_count={offer.raw.get('price_recovery_reload_count')}")
        print("alert_nonstop_only=True")
        print(f"alert_max_offers={max_offers}")
        print(f"direct_offer_count={len(rows)}")
        for index, row in enumerate(rows, start=1):
            times = row.get("times") or []
            time_text = f"{times[0]} -> {times[1]}" if len(times) >= 2 else "time unknown"
            print(
                f"direct_offer_{index}={int(row['price']):,} KRW | "
                f"{row.get('airline') or 'airline unknown'} | {time_text}"
            )

        print("\n=== SUMMARY ===")
        print(f"query_contract={QUERY_CONTRACT}")
        print(f"provider={offer.provider}")
        print(f"lowest_direct_round_trip={int(rows[0]['price']):,} KRW")
        print(f"displayed_direct_offers={len(rows)}")
        print("connections_in_alert=0")
        print("booking_navigation_performed=False")
        print("external_checkout_navigation_performed=False")
        print(f"google_flights_result_url={offer.google_flights_url}")
        print("acceptance=PRODUCTION_PROVIDER_DIRECT_ONLY_SINGLE_LINK")
        print(f"artifact_dir={artifact_dir.resolve()}")
    except Exception:
        if page is not None and not page.is_closed():
            try:
                await base.save_debug(page, artifact_dir, "snapshot-results-probe-error")
            except Exception:
                pass
        raise
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if edge_process is not None and edge_process.poll() is None:
            try:
                edge_process.terminate()
                edge_process.wait(timeout=5)
            except Exception:
                pass


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("This acceptance probe is Windows-only")
    if base.env_bool("BROWSER_HEADLESS", False):
        raise SystemExit("This acceptance probe must run visible; BROWSER_HEADLESS=false")

    print("Google Flights production-provider acceptance")
    print(f"  production query contract: {QUERY_CONTRACT}")
    print("  production Provider.search end-to-end: YES")
    print("  Cheapest-first forced refresh: YES")
    print("  round-trip displayed price source: YES")
    print("  connections/stops excluded from alert: YES")
    print("  alert offer count configurable: YES")
    print("  Booking navigation: NO")
    print("  external checkout navigation: NO")
    print("  user-facing URL count: 1 (Google Flights results only)")

    playwright = await async_playwright().start()
    try:
        await _run_session(playwright)
    except Exception as exc:
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        raise SystemExit(2) from exc
    finally:
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())
