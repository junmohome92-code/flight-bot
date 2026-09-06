from __future__ import annotations

import os

import pytest
from playwright.async_api import async_playwright

from scripts.google_booking_pointer_probe_v5 import capture_state_v5, select_cheapest_tab_v5


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_CONTRACT_TESTS") != "1",
    reason="browser contract test runs in its dedicated CI job",
)


@pytest.mark.asyncio
async def test_cheapest_radio_replacement_is_requeried_and_stamped():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    try:
        await page.set_content(
            """<!doctype html>
<html><body>
<script>
window.__flightBotCaptureV4 = {
  phase: 'pre-cheapest',
  phaseStartedAtMs: performance.now(),
  cheapestRequestedAtMs: null,
  cheapestSelected: false,
  cheapestSelectedAtMs: null,
  cheapestText: '',
  cheapestLoading: false,
  advertisedPrice: null,
  advertisedChangedAtMs: performance.now(),
  candidates: [],
  returningMarker: false,
  returningMarkerAtMs: null
};
</script>
<div role="radiogroup" aria-label="Flight ranking">
  <div role="radio" aria-checked="true" tabindex="0">Best from ₩418,500</div>
  <div role="radio" aria-checked="false" tabindex="0" id="cheap">Cheapest from ₩418,500</div>
</div>
<script>
document.getElementById('cheap').addEventListener('click', () => {
  const old = document.getElementById('cheap');
  const replacement = document.createElement('div');
  replacement.id = 'cheap';
  replacement.setAttribute('role', 'radio');
  replacement.setAttribute('aria-checked', 'true');
  replacement.setAttribute('tabindex', '0');
  replacement.textContent = 'Cheapest from ₩311,811';
  old.replaceWith(replacement);
});
</script>
</body></html>"""
        )

        selected = await select_cheapest_tab_v5(page, 3000)
        assert selected["selectedBy"] == "aria-checked"
        assert selected["role"] == "radio"
        assert "311,811" in selected["text"]

        capture = await page.evaluate("() => window.__flightBotCaptureV4")
        assert capture["cheapestSelected"] is True
        assert capture["advertisedPrice"] == 311811
        assert capture["cheapestSelectionEvidence"] == "aria-checked"
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_capture_refreshes_selected_cheapest_advertised_low_water():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    try:
        await page.set_content(
            """<!doctype html>
<html><body>
<script>
window.__flightBotCaptureV4 = {
  phase: 'departure',
  phaseStartedAtMs: performance.now(),
  cheapestRequestedAtMs: performance.now(),
  cheapestSelected: false,
  cheapestSelectedAtMs: null,
  cheapestText: '',
  cheapestLoading: false,
  advertisedPrice: null,
  advertisedChangedAtMs: performance.now(),
  candidates: [],
  returningMarker: false,
  returningMarkerAtMs: null,
  rejectedBroad: 0,
  rejectedSource: 0
};
</script>
<div role="radio" aria-checked="true" tabindex="0" id="cheap">Cheapest from ₩311,811</div>
</body></html>"""
        )

        first = await capture_state_v5(page)
        assert first["cheapestSelected"] is True
        assert first["advertisedPrice"] == 311811
        assert first["cheapestSelectionEvidence"] == "aria-checked"

        await page.locator("#cheap").evaluate("el => { el.textContent = 'Cheapest from ₩299,900'; }")
        await page.wait_for_timeout(120)
        second = await capture_state_v5(page)
        assert second["advertisedPrice"] == 299900
    finally:
        await browser.close()
        await playwright.stop()
