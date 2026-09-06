from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_CONTRACT_TESTS") != "1",
    reason="browser contract test runs in its dedicated CI job",
)

_DOM_CAPTURE = Path(__file__).resolve().parents[1] / "scripts" / "google_dom_capture.js"

_DEPARTURE_HTML = """<!doctype html>
<html><body>
<button role="tab" aria-selected="false" id="cheap">Cheapest from ₩418,500</button>
<div id="dep" style="cursor:pointer">
  <span>11:40 PM</span><span>1:10 AM</span><span>EASTAR JET</span>
  <span>2 hr 30 min</span><span>CJJ–TPE</span><span>Nonstop</span>
  <span id="dep-price">₩418,500</span><span>round trip</span>
</div>
</body></html>"""

_RETURN_HTML = """<!doctype html>
<html><body>
<h2>Returning flights</h2>
<div id="ret" style="cursor:pointer">
  <span>2:20 PM</span><span>5:45 PM</span><span>EASTAR JET</span>
  <span>2 hr 25 min</span><span>Nonstop</span><span id="ret-price">+₩0</span>
</div>
</body></html>"""


async def _serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        first = await reader.readline()
        path = first.decode("latin1", errors="ignore").split(" ")[1]
        while True:
            line = await reader.readline()
            if not line or line in {b"\r\n", b"\n"}:
                break
        body = _RETURN_HTML if path.startswith("/returning") else _DEPARTURE_HTML
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
async def test_capture_survives_text_mutation_and_full_return_navigation():
    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    dom_capture = _DOM_CAPTURE.read_text(encoding="utf-8")
    init = (
        "window.__flightBotInitConfig = "
        + json.dumps({"origin": "CJJ", "destination": "TPE"})
        + ";\n"
        + dom_capture
    )

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    await context.add_init_script(init)
    page = await context.new_page()

    try:
        await page.goto(f"http://127.0.0.1:{port}/departure")
        await page.evaluate(
            """() => {
                const s = window.__flightBotCaptureV4;
                s.phase = 'departure';
                s.phaseStartedAtMs = performance.now();
                s.cheapestRequestedAtMs = performance.now();
                sessionStorage.setItem('__flightBotPointerPhaseV4', 'departure');
            }"""
        )
        # Change only Text-node characterData for the row price. The observer
        # must inspect mutation.target.parentElement and preserve the 311,811 row.
        await page.evaluate(
            """() => {
                const tab = document.getElementById('cheap');
                tab.setAttribute('aria-selected', 'true');
                tab.firstChild.data = 'Cheapest from ₩311,811';
                document.getElementById('dep-price').firstChild.data = '₩311,811';
            }"""
        )
        await page.wait_for_timeout(180)
        departure = await page.evaluate(
            """() => ({
                selected: window.__flightBotCaptureV4.cheapestSelected,
                advertised: window.__flightBotCaptureV4.advertisedPrice,
                prices: window.__flightBotCaptureV4.candidates
                    .filter(x => x.phase === 'departure').map(x => x.price)
            })"""
        )
        assert departure["selected"] is True
        assert departure["advertised"] == 311811
        assert 311811 in departure["prices"]

        # Persist the next phase exactly as the real probe does before outbound
        # click. A full document navigation must recreate V4 capture as active.
        await page.evaluate(
            """() => {
                sessionStorage.setItem('__flightBotPointerPhaseV4', 'returning');
                window.__flightBotCaptureV4.phase = 'returning';
            }"""
        )
        await page.goto(f"http://127.0.0.1:{port}/returning")
        await page.wait_for_timeout(180)
        returning = await page.evaluate(
            """() => ({
                phase: window.__flightBotCaptureV4.phase,
                marker: window.__flightBotCaptureV4.returningMarker,
                prices: window.__flightBotCaptureV4.candidates
                    .filter(x => x.phase === 'returning').map(x => x.price)
            })"""
        )
        assert returning["phase"] == "returning"
        assert returning["marker"] is True
        assert 0 in returning["prices"]
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()
        server.close()
        await server.wait_closed()
