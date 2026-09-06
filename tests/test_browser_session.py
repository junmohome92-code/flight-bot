from __future__ import annotations

from types import SimpleNamespace

import pytest

from flight_bot.browser_session import PlaywrightBrowserSession
from flight_bot.config import Settings


class _FakePage:
    def __init__(self, url: str):
        self.url = url
        self.timeout = None
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def set_default_timeout(self, value: int) -> None:
        self.timeout = value


class _FakeContext:
    def __init__(self, pages):
        self.pages = list(pages)
        self.new_page_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        page = _FakePage("about:blank")
        self.pages.append(page)
        return page


@pytest.mark.asyncio
async def test_new_page_reuses_existing_blank_startup_tab():
    settings = Settings(browser_timeout_ms=12345, browser_profile_dir="")
    session = PlaywrightBrowserSession(settings)
    startup = _FakePage("about:blank")
    context = _FakeContext([startup])

    async def fake_started():
        return context

    session._ensure_started = fake_started  # type: ignore[method-assign]
    page = await session.new_page()

    assert page is startup
    assert context.new_page_calls == 0
    assert startup.timeout == 12345


@pytest.mark.asyncio
async def test_new_page_opens_fresh_when_no_blank_tab_exists():
    settings = Settings(browser_timeout_ms=6789, browser_profile_dir="")
    session = PlaywrightBrowserSession(settings)
    context = _FakeContext([_FakePage("https://example.test/existing")])

    async def fake_started():
        return context

    session._ensure_started = fake_started  # type: ignore[method-assign]
    page = await session.new_page()

    assert page is context.pages[-1]
    assert context.new_page_calls == 1
    assert page.timeout == 6789
