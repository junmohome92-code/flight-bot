from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from flight_bot.config import Settings
from flight_bot.google_query import QUERY_CONTRACT
from flight_bot.models import WatchSlot
from flight_bot.runtime_results_provider import RuntimeGoogleResultsProvider


ARTIFACT_DIR = Path("artifacts/google-msedge-win")


class MsEdgeBrowserSession:
    """Run the production provider inside installed Microsoft Edge.

    This is a diagnostic-only Windows adapter. It changes only the browser
    executable/channel; URL generation, Cheapest handling, reload/recovery and
    row extraction remain the real RuntimeGoogleResultsProvider implementation.
    """

    def __init__(self, playwright: Playwright, settings: Settings) -> None:
        self.playwright = playwright
        self.settings = settings
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def _ensure_started(self) -> None:
        if self.browser is not None:
            return
        self.browser = await self.playwright.chromium.launch(
            channel="msedge",
            headless=False,
        )
        self.context = await self.browser.new_context(
            locale="en-US",
            timezone_id=self.settings.timezone,
            viewport={"width": 1365, "height": 900},
            service_workers="block",
        )

    async def new_page(self) -> Page:
        await self._ensure_started()
        assert self.context is not None
        if self.page is None or self.page.is_closed():
            self.page = await self.context.new_page()
        self.page.set_default_timeout(self.settings.browser_timeout_ms)
        return self.page

    async def release_page(self, page: Page) -> None:
        # Keep the final Google surface visible long enough for human inspection.
        self.page = page
        if not page.is_closed():
            await page.wait_for_timeout(8_000)

    async def close(self) -> None:
        if self.context is not None:
            try:
                await self.context.close()
            except Exception:
                pass
        if self.browser is not None:
            try:
                await self.browser.close()
            except Exception:
                pass


async def save_debug(page: Page | None, stem: str) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if page is None or page.is_closed():
        return
    try:
        await page.screenshot(path=str(ARTIFACT_DIR / f"{stem}.png"), full_page=True)
    except Exception:
        pass
    try:
        body = await page.locator("body").inner_text(timeout=3_000)
        (ARTIFACT_DIR / f"{stem}.txt").write_text(body, encoding="utf-8")
    except Exception:
        pass


async def main() -> int:
    if not sys.platform.startswith("win"):
        print("This probe is Windows-only.")
        return 2

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        browser_headless=False,
        browser_timeout_ms=60_000,
        browser_block_assets=False,
        browser_debug_dir=str(ARTIFACT_DIR),
        alert_nonstop_only=True,
        alert_max_offers=4,
        google_language="en",
        google_gl="kr",
        google_currency="KRW",
    )
    slot = WatchSlot(
        id=1,
        owner_platform="msedge-probe",
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

    print("==================================================")
    print(" Google Flights - Playwright Microsoft Edge test")
    print("==================================================")
    print("browser_channel=msedge")
    print(f"query_contract={QUERY_CONTRACT}")
    print("route=CJJ->TPE->CJJ")
    print("dates=2026-09-18..2026-09-20")
    print("booking_navigation=NO")
    print("external_checkout_navigation=NO")
    print("")

    playwright = await async_playwright().start()
    session = MsEdgeBrowserSession(playwright, settings)
    provider = RuntimeGoogleResultsProvider(settings, browser_session=session)
    try:
        print(f"selection_url={provider.build_search_url(slot)}")
        offer = await provider.search(slot)
        rows = list(offer.display_offers or [])
        print("\n=== GOOGLE MSEDGE RESULT ===")
        print(f"status=SUCCESS")
        print(f"provider={offer.provider}")
        print(f"lowest_direct_round_trip={offer.total_price:,} KRW")
        print(f"direct_offer_count={len(rows)}")
        for index, row in enumerate(rows, 1):
            times = list(row.get("times") or [])
            time_text = " -> ".join(str(x) for x in times[:2]) if times else "time unknown"
            print(
                f"offer_{index}={int(row['price']):,} KRW | "
                f"{row.get('airline') or 'airline unknown'} | {time_text}"
            )
        print(f"result_url={offer.google_flights_url}")
        print(f"artifact_dir={ARTIFACT_DIR.resolve()}")
        return 0
    except Exception as exc:
        page = session.page
        await save_debug(page, "google-msedge-failed")
        print("\n=== GOOGLE MSEDGE RESULT ===")
        print("status=FAILED")
        print(f"error_type={type(exc).__name__}")
        print(f"error={exc}")
        print(f"artifact_dir={ARTIFACT_DIR.resolve()}")
        print("If BAT2 succeeds but this fails, the remaining difference is session/launch behavior, not the Google query contract.")
        return 2
    finally:
        await session.close()
        await playwright.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
