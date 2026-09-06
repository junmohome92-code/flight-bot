from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .config import Settings


class PlaywrightBrowserSession:
    """Reusable Chromium session for the legacy runtime provider.

    The service already serializes searches, so one browser context can be
    reused across slots instead of launching Chromium for every query. When
    ``BROWSER_PROFILE_DIR`` is configured, Playwright uses a persistent profile
    directory; otherwise it falls back to an in-memory context.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._start_lock = asyncio.Lock()

    async def _ensure_started(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        async with self._start_lock:
            if self._context is not None:
                return self._context

            self._playwright = await async_playwright().start()
            launch_args = ["--disable-dev-shm-usage"]
            common = dict(
                headless=self.settings.browser_headless,
                args=launch_args,
            )

            if self.settings.browser_profile_dir:
                profile = Path(self.settings.browser_profile_dir)
                profile.mkdir(parents=True, exist_ok=True)
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile),
                    locale="en-US",
                    timezone_id=self.settings.timezone,
                    viewport={"width": 1365, "height": 900},
                    **common,
                )
            else:
                self._browser = await self._playwright.chromium.launch(**common)
                self._context = await self._browser.new_context(
                    locale="en-US",
                    timezone_id=self.settings.timezone,
                    viewport={"width": 1365, "height": 900},
                )

            if self.settings.browser_block_assets:
                async def route_handler(route):
                    if route.request.resource_type in {"image", "media", "font"}:
                        await route.abort()
                    else:
                        await route.continue_()

                await self._context.route("**/*", route_handler)
            return self._context

    async def new_page(self) -> Page:
        context = await self._ensure_started()

        # Persistent contexts commonly start with one about:blank tab. Reuse it
        # instead of blindly opening a second visible tab. Once the provider
        # closes that page after a search, later searches simply create a fresh
        # page as before.
        page = next(
            (
                candidate
                for candidate in context.pages
                if not candidate.is_closed()
                and (
                    candidate.url in {"", "about:blank", "edge://newtab/", "chrome://newtab/"}
                    or candidate.url.startswith("edge://newtab")
                    or candidate.url.startswith("chrome://newtab")
                )
            ),
            None,
        )
        if page is None:
            page = await context.new_page()
        page.set_default_timeout(self.settings.browser_timeout_ms)
        return page

    async def close(self) -> None:
        context, browser, playwright = self._context, self._browser, self._playwright
        self._context = None
        self._browser = None
        self._playwright = None
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
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
