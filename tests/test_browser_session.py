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
async def test_parallel_price_searches_get_distinct_live_contexts():
    settings = Settings(_env_file=None, browser_timeout_ms=12345, browser_block_assets=False)
    session = PlaywrightBrowserSession(settings)
    browser = _FakeBrowser()

    async def fake_started():
        return browser

    session._ensure_started = fake_started  # type: ignore[method-assign]

    first = await session.new_page()
    second = await session.new_page()

    assert first.context is not second.context
    assert first.context.closed is False
    assert second.context.closed is False
    assert first.timeout == 12345
    assert second.timeout == 12345
    assert len(browser.contexts) == 2
    assert len(session._contexts) == 2


@pytest.mark.asyncio
async def test_release_page_closes_only_its_own_context():
    settings = Settings(_env_file=None, browser_block_assets=False)
    session = PlaywrightBrowserSession(settings)
    browser = _FakeBrowser()

    async def fake_started():
        return browser

    session._ensure_started = fake_started  # type: ignore[method-assign]
    first = await session.new_page()
    second = await session.new_page()

    await session.release_page(first)

    assert first.context.closed is True
    assert second.context.closed is False
    assert first.context not in session._contexts
    assert second.context in session._contexts
