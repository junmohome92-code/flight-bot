from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright


async def main() -> None:
    playwright = await async_playwright().start()
    browser = None
    try:
        browser = await playwright.chromium.launch(channel="msedge", headless=True)
        print(f"Edge via Playwright: {browser.version}")
    finally:
        if browser is not None:
            await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())
