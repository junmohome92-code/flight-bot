from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from playwright.async_api import async_playwright


_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
from google_departure_transition import _install_returning_candidate_guard  # noqa: E402


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_CONTRACT_TESTS") != "1",
    reason="return phase boundary test runs in its dedicated CI job",
)


@pytest.mark.asyncio
async def test_return_guard_rejects_stale_outbound_rows_before_and_after_marker():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    try:
        await page.set_content(
            """<!doctype html><html><body><script>
window.__flightBotInitConfig = {origin: 'CJJ', destination: 'TPE'};
window.__flightBotCaptureV4 = {
  phase: 'returning',
  returningMarker: false,
  returningMarkerAtMs: null,
  candidates: [
    {
      id: 'stale-outbound',
      phase: 'returning',
      returningMarkerAtSeen: false,
      rowText: '11:40 PM 1:10 AM EASTAR JET CJJ Cheongju - TPE Taiwan Nonstop ₩308,545'
    }
  ]
};
</script></body></html>"""
        )

        first = await _install_returning_candidate_guard(page)
        assert first["installed"] is True
        assert first["purged"] == 1

        # Before the Returning marker, no candidate may enter the returning set.
        await page.evaluate(
            """() => window.__flightBotCaptureV4.candidates.push({
              id: 'pre-marker-return',
              phase: 'returning',
              returningMarkerAtSeen: false,
              rowText: '2:20 PM 5:45 PM EASTAR JET TPE Taiwan - CJJ Cheongju Nonstop +₩0'
            })"""
        )
        assert await page.evaluate("() => window.__flightBotCaptureV4.candidates.length") == 0

        # After the marker, an explicit outbound code order is still stale and
        # must be rejected, while TPE -> CJJ is a legitimate return direction.
        await page.evaluate(
            """() => {
              const s = window.__flightBotCaptureV4;
              s.returningMarker = true;
              s.returningMarkerAtMs = performance.now();
              s.candidates.push({
                id: 'post-marker-outbound',
                phase: 'returning',
                returningMarkerAtSeen: true,
                rowText: '11:40 PM 1:10 AM EASTAR JET CJJ Cheongju - TPE Taiwan Nonstop ₩308,545'
              });
              s.candidates.push({
                id: 'real-return',
                phase: 'returning',
                returningMarkerAtSeen: true,
                rowText: '2:20 PM 5:45 PM EASTAR JET TPE Taiwan - CJJ Cheongju Nonstop +₩0'
              });
            }"""
        )

        ids = await page.evaluate(
            "() => window.__flightBotCaptureV4.candidates.map(item => item.id)"
        )
        assert ids == ["real-return"]
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_return_guard_allows_marker_scoped_card_when_route_tokens_are_omitted():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    try:
        await page.set_content(
            """<!doctype html><html><body><script>
window.__flightBotInitConfig = {origin: 'CJJ', destination: 'TPE'};
window.__flightBotCaptureV4 = {
  phase: 'returning',
  returningMarker: true,
  returningMarkerAtMs: performance.now(),
  candidates: []
};
</script></body></html>"""
        )
        result = await _install_returning_candidate_guard(page)
        assert result["installed"] is True

        await page.evaluate(
            """() => window.__flightBotCaptureV4.candidates.push({
              id: 'compact-return',
              phase: 'returning',
              returningMarkerAtSeen: true,
              rowText: '2:20 PM 5:45 PM EASTAR JET 2 hr 25 min Nonstop +₩0'
            })"""
        )
        ids = await page.evaluate(
            "() => window.__flightBotCaptureV4.candidates.map(item => item.id)"
        )
        assert ids == ["compact-return"]
    finally:
        await browser.close()
        await playwright.stop()
