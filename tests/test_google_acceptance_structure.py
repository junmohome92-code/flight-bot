from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from playwright.async_api import async_playwright


_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
from google_booking_acceptance import claim_initial_page, prepare_cheapest_surface  # noqa: E402


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_CONTRACT_TESTS") != "1",
    reason="canonical acceptance lifecycle test runs in its dedicated CI job",
)


_CAPTURE_STATE = """
<script>
window.__flightBotCaptureV4 = {
  phase: 'pre-cheapest',
  phaseStartedAtMs: performance.now(),
  cheapestRequestedAtMs: null,
  cheapestClickStartedAtMs: null,
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
  rejectedSource: 0,
  rejectedShape: 0,
  rejectedRoute: 0,
  rejectedPriceContext: 0
};
</script>
"""

_UNAVAILABLE_HTML = f"""<!doctype html>
<html><body>
{_CAPTURE_STATE}
<button role="tab" aria-selected="false" id="cheap">Cheapest from Fetching results</button>
<div>Price unavailable</div>
<script>
document.getElementById('cheap').addEventListener('click', () => {{
  const el = document.getElementById('cheap');
  el.setAttribute('aria-selected', 'true');
}});
</script>
</body></html>"""

_READY_HTML = f"""<!doctype html>
<html><body>
{_CAPTURE_STATE}
<button role="tab" aria-selected="false" id="cheap">Cheapest from ₩311,811</button>
<div><span>11:40 PM</span><span>1:10 AM</span><span>Nonstop</span><span>₩311,811</span></div>
<script>
document.getElementById('cheap').addEventListener('click', () => {{
  const el = document.getElementById('cheap');
  el.setAttribute('aria-selected', 'true');
}});
</script>
</body></html>"""


async def _serve(counter: dict[str, int], reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        first = await reader.readline()
        parts = first.decode("latin1", errors="ignore").split(" ")
        path = parts[1] if len(parts) > 1 else "/"
        while True:
            line = await reader.readline()
            if not line or line in {b"\r\n", b"\n"}:
                break

        if not path.startswith("/search"):
            payload = b""
            writer.write(
                b"HTTP/1.1 204 No Content\r\n"
                b"Content-Length: 0\r\nConnection: close\r\n\r\n"
            )
            await writer.drain()
            return

        counter["search_requests"] += 1
        body = _UNAVAILABLE_HTML if counter["search_requests"] == 1 else _READY_HTML
        payload = body.encode("utf-8")
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            + f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode("ascii")
            + payload
        )
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_claim_initial_page_reuses_existing_startup_tab():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    initial = await context.new_page()
    try:
        assert len(context.pages) == 1
        claimed = await claim_initial_page(context, 5000)
        assert claimed is initial
        assert len(context.pages) == 1
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_cheapest_is_selected_before_forced_reload_then_reselected_if_needed():
    counter = {"search_requests": 0}
    server = await asyncio.start_server(lambda r, w: _serve(counter, r, w), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/search"

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    initial = await context.new_page()
    try:
        page = await claim_initial_page(context, 5000)
        assert page is initial
        await page.goto(url, wait_until="domcontentloaded")

        page, recovery_count = await prepare_cheapest_surface(
            context,
            page,
            url,
            timeout_ms=5000,
            selection_wait_ms=3000,
            ready_wait_ms=1800,
            recovery_reloads=2,
            artifact_dir=None,
        )

        assert page is initial
        assert len(context.pages) == 1
        assert counter["search_requests"] >= 2
        assert recovery_count == 0
        assert "₩311,811" in await page.locator("body").inner_text()
        assert await page.locator("#cheap").get_attribute("aria-selected") == "true"
        state = await page.evaluate("() => window.__flightBotCaptureV4")
        assert state["cheapestSelected"] is True
        assert state["advertisedPrice"] == 311811
        assert float(state["cheapestClickStartedAtMs"]) > 0
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()
        server.close()
        await server.wait_closed()
