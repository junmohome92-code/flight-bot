from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from playwright.async_api import async_playwright


_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
from google_departure_transition import (  # noqa: E402
    click_specific_candidate,
    wait_for_returning_with_recovery,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_CONTRACT_TESTS") != "1",
    reason="departure transition contract runs in its dedicated browser CI job",
)


@pytest.mark.asyncio
async def test_specific_card_click_ignores_inner_price_pointer_action():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page(viewport={"width": 1000, "height": 700})
    try:
        await page.set_content(
            """<!doctype html>
<html><body>
<style>
#card { position: relative; width: 700px; height: 120px; cursor: pointer; border: 1px solid #999; }
#price { position: absolute; right: 10px; top: 40px; cursor: pointer; }
</style>
<div id="card" role="button" tabindex="0">
  <span>11:40 PM</span>
  <span>1:10 AM</span>
  <span>EASTAR JET</span>
  <span>2 hr 30 min</span>
  <span>Nonstop</span>
  <span>CJJ - TPE</span>
  <span id="price" data-flight-bot-pointer-anchor-id="dep-1">₩308,545</span>
</div>
<script>
window.cardClicked = false;
window.innerPriceClicked = false;
const card = document.getElementById('card');
const price = document.getElementById('price');
card.addEventListener('click', () => { window.cardClicked = true; });
price.addEventListener('click', event => {
  window.innerPriceClicked = true;
  event.stopPropagation();
});
window.__flightBotCaptureV4 = {
  refs: { 'dep-1': { anchor: price, row: card } }
};
</script>
</body></html>"""
        )
        candidate = {
            "id": "dep-1",
            "phase": "departure",
            "price": 308545,
            "rowText": "11:40 PM 1:10 AM EASTAR JET 2 hr 30 min CJJ - TPE Nonstop ₩308,545 round trip",
            "anchorRect": {},
            "sourceRect": {},
        }

        mode = await click_specific_candidate(page, candidate, prefix="departure")
        assert mode == "live-card-semantic"
        state = await page.evaluate("() => ({cardClicked: window.cardClicked, innerPriceClicked: window.innerPriceClicked})")
        assert state["cardClicked"] is True
        assert state["innerPriceClicked"] is False
    finally:
        await browser.close()
        await playwright.stop()


_ERROR_HTML = """<!doctype html>
<html><body>
<div>Flights couldn't be loaded</div>
<script>
window.__flightBotCaptureV4 = {
  phase: 'returning',
  phaseStartedAtMs: performance.now(),
  returningMarker: false,
  returningMarkerAtMs: null
};
</script>
</body></html>"""

_RETURNING_HTML = """<!doctype html>
<html><body>
<h2>Returning flights</h2>
<div>2:20 PM 5:45 PM EASTAR JET 2 hr 25 min Nonstop +₩0</div>
<script>
window.__flightBotCaptureV4 = {
  phase: 'returning',
  phaseStartedAtMs: performance.now(),
  returningMarker: false,
  returningMarkerAtMs: null
};
</script>
</body></html>"""


async def _serve_selected(counter: dict[str, int], reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        first = await reader.readline()
        path = first.decode("latin1", errors="ignore").split(" ")[1]
        while True:
            line = await reader.readline()
            if not line or line in {b"\r\n", b"\n"}:
                break
        if path.startswith("/selected"):
            counter["selected"] += 1
            body = _ERROR_HTML if counter["selected"] == 1 else _RETURNING_HTML
        else:
            body = "<html><body>Search page</body></html>"
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
async def test_selected_outbound_load_error_reloads_same_url_then_reaches_returning():
    counter = {"selected": 0}
    server = await asyncio.start_server(lambda r, w: _serve_selected(counter, r, w), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    before_url = f"http://127.0.0.1:{port}/search"
    selected_url = f"http://127.0.0.1:{port}/selected?flight=ZE781"

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        await page.goto(selected_url, wait_until="domcontentloaded")
        ok, reloads = await wait_for_returning_with_recovery(
            page,
            before_url=before_url,
            timeout_ms=5000,
            max_reloads=2,
        )
        assert ok is True
        assert reloads == 1
        assert counter["selected"] >= 2
        assert page.url == selected_url
        assert "Returning flights" in await page.locator("body").inner_text()
        state = await page.evaluate("() => window.__flightBotCaptureV4")
        assert state["phase"] == "returning"
        assert state["returningMarker"] is True
    finally:
        await browser.close()
        await playwright.stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_load_error_without_outbound_url_change_is_not_retried_as_valid_selection():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        await page.set_content(_ERROR_HTML)
        before_url = page.url
        with pytest.raises(RuntimeError, match="before the outbound-selection URL changed"):
            await wait_for_returning_with_recovery(
                page,
                before_url=before_url,
                timeout_ms=3000,
                max_reloads=2,
            )
    finally:
        await browser.close()
        await playwright.stop()
