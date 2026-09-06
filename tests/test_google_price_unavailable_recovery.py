from __future__ import annotations

import asyncio
import os

import pytest
from playwright.async_api import async_playwright

from scripts.google_booking_pointer_probe_v7 import (
    ensure_search_price_ready,
    is_target_closed_error,
    reopen_search_page,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_CONTRACT_TESTS") != "1",
    reason="browser recovery contract test runs in its dedicated CI job",
)

_UNAVAILABLE_HTML = """<!doctype html>
<html><body>
<button role="tab" aria-selected="false">Cheapest from Fetching results</button>
<div>Price unavailable</div>
</body></html>"""

_READY_HTML = """<!doctype html>
<html><body>
<button role="tab" aria-selected="false">Cheapest from ₩311,811</button>
<div><span>11:40 PM</span><span>1:10 AM</span><span>Nonstop</span><span>₩311,811</span></div>
</body></html>"""


async def _response_server(counter: dict[str, int], reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await reader.readline()
        while True:
            line = await reader.readline()
            if not line or line in {b"\r\n", b"\n"}:
                break
        counter["requests"] += 1
        body = _UNAVAILABLE_HTML if counter["requests"] == 1 else _READY_HTML
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
async def test_price_unavailable_full_reload_recovers_to_ready(tmp_path):
    counter = {"requests": 0}
    server = await asyncio.start_server(
        lambda r, w: _response_server(counter, r, w), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/search"

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")
        recovered, reloads = await ensure_search_price_ready(
            context,
            page,
            url,
            timeout_ms=5000,
            ready_wait_ms=1800,
            max_reloads=2,
            artifact_dir=tmp_path,
        )
        assert recovered is page
        assert reloads == 1
        assert counter["requests"] >= 2
        assert "₩311,811" in await recovered.locator("body").inner_text()
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_closed_page_is_replaced_and_search_reopened():
    counter = {"requests": 1}  # first served page should already be the ready variant
    server = await asyncio.start_server(
        lambda r, w: _response_server(counter, r, w), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/search"

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.close()
        replacement = await reopen_search_page(context, page, url, 5000)
        assert replacement is not page
        assert replacement.is_closed() is False
        assert "₩311,811" in await replacement.locator("body").inner_text()
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()
        server.close()
        await server.wait_closed()


def test_target_closed_error_classifier_handles_playwright_message():
    exc = RuntimeError("Page.wait_for_timeout: Target page, context or browser has been closed")
    assert is_target_closed_error(exc) is True
