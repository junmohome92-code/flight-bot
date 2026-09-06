from __future__ import annotations

import pytest

import flight_bot.providers as providers_module
from flight_bot.config import Settings
from flight_bot.models import WatchSlot
from flight_bot.runtime_results_provider import RuntimeGoogleResultsProvider


class _FakePage:
    def __init__(self, trace):
        self.trace = trace
        self.url = "about:blank"

    async def goto(self, url, **kwargs):
        self.url = url
        self.trace.append("goto")

    async def wait_for_timeout(self, ms):
        self.trace.append(f"wait:{ms}")

    def is_closed(self):
        return False


class _FakeBrowserSession:
    def __init__(self, trace):
        self.trace = trace
        self.page = _FakePage(trace)

    async def new_page(self):
        self.trace.append("new-page")
        return self.page

    async def release_page(self, page):
        self.trace.append("release-page")

    async def close(self):
        pass


class _TraceProvider(RuntimeGoogleResultsProvider):
    def __init__(self, settings, trace, *, query_builder=None):
        self.trace = trace
        super().__init__(
            settings,
            query_builder=query_builder,
            browser_session=_FakeBrowserSession(trace),
        )

    async def _check_captcha(self, page):
        self.trace.append("captcha-check")

    async def _extract_best(self, page, slot):
        self.trace.append("extract-direct")
        return {
            "price": 308545,
            "airline": "EASTAR JET",
            "flight_numbers": None,
            "nonstop": True,
            "separate_ticket": False,
            "text": "Nonstop CJJ-TPE ₩308,545 round trip",
            "candidate_count": 2,
            "display_offers": [
                {
                    "price": 308545,
                    "airline": "EASTAR JET",
                    "times": ["11:40 PM", "1:10 AM"],
                    "nonstop": True,
                }
            ],
        }

    async def _debug_screenshot(self, page, name):
        self.trace.append(f"debug:{name}")


def _slot():
    return WatchSlot(
        id=1,
        owner_platform="telegram",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        nonstop=True,
        checked_bag=0,
        enabled=True,
        target_price=999999,
    )


@pytest.mark.asyncio
async def test_runtime_search_delegates_to_shared_accepted_flow(monkeypatch):
    trace = []

    async def fake_prepare(page, search_url, **kwargs):
        trace.append("canonical-prepare")
        assert kwargs["selection_wait_ms"] == 25000
        assert kwargs["ready_wait_ms"] == 8000
        assert kwargs["recovery_reloads"] == 2
        return page, 2

    monkeypatch.setattr(providers_module, "prepare_cheapest_surface", fake_prepare)
    provider = _TraceProvider(
        Settings(_env_file=None),
        trace,
        query_builder=lambda slot: "https://www.google.com/travel/flights/search?runtime-test=1",
    )

    offer = await provider.search(_slot())

    assert offer.total_price == 308545
    assert offer.result_url.endswith("runtime-test=1")
    assert offer.raw["query_contract"] == "accepted-tfs-v1"
    assert offer.raw["cheapest_selected_full_reload"] == 1
    assert offer.raw["price_recovery_reload_count"] == 2
    assert [item for item in trace if item in {"goto", "canonical-prepare", "extract-direct", "release-page"}] == [
        "goto",
        "canonical-prepare",
        "extract-direct",
        "release-page",
    ]


def test_runtime_default_url_matches_accepted_probe_contract():
    provider = RuntimeGoogleResultsProvider(Settings(_env_file=None), browser_session=_FakeBrowserSession([]))
    assert provider.build_search_url(_slot()) == (
        "https://www.google.com/travel/flights/search?"
        "tfs=CBwQAhoeEgoyMDI2LTA5LTE4agcIARIDQ0pKcgcIARIDVFBFGh4SCjIwMjYtMDktMjBqBwgBEgNUUEVyBwgBEgNDSkpAAUgBcAGCAQsI____________AZgBAQ"
        "&hl=en&gl=kr&curr=KRW"
    )


def test_runtime_provider_exposes_accepted_flow_identity():
    assert RuntimeGoogleResultsProvider.name == "google-playwright-results-observed-accepted-flow"
    assert RuntimeGoogleResultsProvider.accepted_for_alerts is True
    assert RuntimeGoogleResultsProvider.price_recovery_reloads == 2
    assert RuntimeGoogleResultsProvider.direct_settle_ms == 3500
