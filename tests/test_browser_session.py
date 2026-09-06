from __future__ import annotations

import pytest

from flight_bot.browser_session import PlaywrightBrowserSession
from flight_bot.config import Settings


class _FakePage:
    def __init__(self, context):
        self.context = context
        self.timeout = None
        self.closed = False

    def set_default_timeout(self, value: int) -> None:
        self.timeout = value

    async def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self):
        self.closed = False
        self.route_calls = 0
        self.page = _FakePage(self)

    async def new_page(self):
        return self.page

    async def route(self, *_args, **_kwargs):
        self.route_calls += 1

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.contexts = []

    async def new_context(self, **_kwargs):
        context = _FakeContext()
        self.contexts.append(context)
        return context


@pytest.mark.asyncio
async def test_each_price_search_gets_a_fresh_context_and_discards_previous_storage():
    settings = Settings(browser_timeout_ms=12345, browser_block_assets=False)
    session = PlaywrightBrowserSession(settings)
    browser = _FakeBrowser()

    async def fake_started():
        return browser

    session._ensure_started = fake_started  # type: ignore[method-assign]

    first = await session.new_page()
    first_context = first.context
    second = await session.new_page()
    second_context = second.context

    assert first_context is not second_context
    assert first_context.closed is True
    assert second_context.closed is False
    assert first.timeout == 12345
    assert second.timeout == 12345
    assert len(browser.contexts) == 2


@pytest.mark.asyncio
async def test_release_page_closes_its_whole_context():
    settings = Settings(browser_block_assets=False)
    session = PlaywrightBrowserSession(settings)
    browser = _FakeBrowser()

    async def fake_started():
        return browser

    session._ensure_started = fake_started  # type: ignore[method-assign]
    page = await session.new_page()
    context = page.context

    await session.release_page(page)

    assert context.closed is True
    assert context not in session._contexts
