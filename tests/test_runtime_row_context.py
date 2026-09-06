from __future__ import annotations

import os

import pytest
from playwright.async_api import async_playwright

from flight_bot.config import Settings
from flight_bot.models import WatchSlot
from flight_bot.runtime_results_provider import RuntimeGoogleResultsProvider


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_CONTRACT_TESTS") != "1",
    reason="runtime DOM row contract runs in the browser-contract CI job",
)


def _slot():
    return WatchSlot(
        id=1,
        owner_platform="test",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        nonstop=True,
        checked_bag=0,
        enabled=True,
        target_price=350000,
    )


@pytest.mark.asyncio
async def test_runtime_row_accepts_separate_airport_codes_without_literal_route_token():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        await page.set_content(
            """
            <div id='card'>
              <span>11:40 PM</span><span>1:10 AM</span>
              <span>EASTAR JET</span><span>2 hr 30 min</span>
              <span>CJJ Cheongju International Airport</span>
              <span>TPE Taiwan Taoyuan International Airport</span>
              <span>Nonstop</span><span id='price'>₩311,694 round trip</span>
            </div>
            """
        )
        provider = RuntimeGoogleResultsProvider(Settings(_env_file=None))
        text = await provider._row_text_for_price_element(page.locator("#price"), _slot())
        assert "CJJ" in text
        assert "TPE" in text
        assert "Nonstop" in text
        assert "311,694" in text
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_runtime_row_rejects_reverse_airport_code_order():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        await page.set_content(
            """
            <div id='card'>
              <span>11:40 PM</span><span>1:10 AM</span>
              <span>TPE Taiwan Taoyuan International Airport</span>
              <span>CJJ Cheongju International Airport</span>
              <span>Nonstop</span><span id='price'>₩311,694 round trip</span>
            </div>
            """
        )
        provider = RuntimeGoogleResultsProvider(Settings(_env_file=None))
        text = await provider._row_text_for_price_element(page.locator("#price"), _slot())
        assert text == ""
    finally:
        await browser.close()
        await playwright.stop()
