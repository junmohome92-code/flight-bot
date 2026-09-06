from __future__ import annotations

import asyncio

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .config import Settings


class PlaywrightBrowserSession:
    """Reuse one Chromium process while isolating every price observation.

    Each search gets a brand-new BrowserContext, so cookies, HTTP cache,
    localStorage, IndexedDB and service-worker state are never inherited from a
    previous two-hour observation. Up to two independent contexts may remain
    live at once. Dead contexts are reaped before opening a replacement page so
    a target-closed recovery cannot leak browser state/resources indefinitely.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._start_lock = asyncio.Lock()
        self._contexts: set[BrowserContext] = set()

    async def _ensure_started(self) -> Browser:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        async with self._start_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.settings.browser_headless,
                args=["--disable-dev-shm-usage"],
            )
            return self._browser

    async def _reap_dead_contexts(self) -> None:
        for context in list(self._contexts):
            try:
                pages = list(context.pages)
            except Exception:
                continue
            if pages and not all(page.is_closed() for page in pages):
                continue
            self._contexts.discard(context)
            try:
                await context.close()
            except Exception:
                pass

    async def _new_isolated_context(self) -> BrowserContext:
        await self._reap_dead_contexts()
        browser = await self._ensure_started()
        context = await browser.new_context(
            locale="en-US",
            timezone_id=self.settings.timezone,
            viewport={"width": 1365, "height": 900},
            service_workers="block",
        )
        self._contexts.add(context)

        if self.settings.browser_block_assets:
            async def route_handler(route):
                if route.request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_handler)
        return context

    async def new_page(self) -> Page:
        context = await self._new_isolated_context()
        page = await context.new_page()
        page.set_default_timeout(self.settings.browser_timeout_ms)
        return page

    async def release_page(self, page: Page) -> None:
        """Destroy only this search's context, preserving other active searches."""
        try:
            context = page.context
        except Exception:
            context = None
        if context is not None:
            self._contexts.discard(context)
            try:
                await context.close()
                return
            except Exception:
                pass
        try:
            await page.close()
        except Exception:
            pass

    async def close(self) -> None:
        contexts = list(self._contexts)
        self._contexts.clear()
        for context in contexts:
            try:
                await context.close()
            except Exception:
                pass

        browser, playwright = self._browser, self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass
