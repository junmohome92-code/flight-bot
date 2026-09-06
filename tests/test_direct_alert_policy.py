from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.providers import rank_alert_candidates
from flight_bot.service import FlightService


def _candidate(price: int, route: str, stop_text: str, airline: str) -> dict:
    return {
        "price": price,
        "text": (
            f"11:40 PM\n1:10 AM\n{airline}\n2 hr 30 min\n{route}\n"
            f"{stop_text}\n₩{price:,}\nround trip"
        ),
        "source": "test",
    }


def test_default_product_policy_is_direct_observed_results_only():
    settings = Settings(_env_file=None)
    assert settings.alert_nonstop_only is True
    assert settings.alert_max_offers == 4
    assert settings.require_verified_alerts is False


def test_rank_alert_candidates_excludes_connections_and_uses_available_count():
    candidates = [
        _candidate(308545, "CJJ-TPE", "Nonstop", "EASTAR JET"),
        _candidate(381095, "CJJ-TPE", "Nonstop", "Aero K Airlines"),
        _candidate(418730, "CJJ-TPE", "1 stop", "EASTAR JET"),
        _candidate(420338, "CJJ-TPE", "1 stop", "Aero K Airlines"),
    ]

    ranked = rank_alert_candidates(candidates, nonstop_only=True, limit=4)

    assert [item["price"] for item in ranked] == [308545, 381095]
    assert all(item["nonstop"] is True for item in ranked)


def test_rank_alert_candidate_limit_is_configurable_not_fixed_to_four():
    candidates = [
        _candidate(300000 + index * 10000, "CJJ-TPE", "Nonstop", f"Airline {index}")
        for index in range(6)
    ]

    ranked = rank_alert_candidates(candidates, nonstop_only=True, limit=3)

    assert len(ranked) == 3
    assert [item["price"] for item in ranked] == [300000, 310000, 320000]


def test_alert_message_contains_only_one_google_results_link(tmp_path):
    settings = Settings(_env_file=None, alert_max_offers=4)
    service = FlightService(settings, Database(str(tmp_path / "db.sqlite")), provider=object())
    slot = service.db.add_slot(
        platform="telegram",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        target_price=350000,
        nonstop=True,
        checked_bag=0,
    )
    result_url = "https://www.google.com/travel/flights/search?example=roundtrip"
    offer = FlightOffer(
        provider="google-playwright-results-observed",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        total_price=308545,
        observed_price_value=308545,
        result_url=result_url,
        checked_baggage="정보 확인 불가",
        display_offers=[
            {"price": 308545, "airline": "EASTAR JET", "times": ["11:40 PM", "1:10 AM"], "nonstop": True},
            {"price": 381095, "airline": "Aero K Airlines", "times": ["10:30 AM", "12:20 PM"], "nonstop": True},
        ],
        fetched_at=datetime.now(timezone.utc),
    )

    message = service.format_offer(slot, offer)

    assert "308,545KRW" in message
    assert "381,095KRW" in message
    assert "Google Flights 직항 왕복가" in message
    assert message.count("https://") == 1
    assert result_url in message
    assert "Booking" not in message
    assert "checkout" not in message.lower()
    assert "판매처" not in message


class _ObservedProvider:
    name = "observed"
    accepted_for_alerts = True

    async def search(self, slot, *, verify_below_price=None):
        return FlightOffer(
            provider=self.name,
            origin=slot.origin,
            destination=slot.destination,
            depart_date=slot.depart_date,
            return_date=slot.return_date,
            total_price=330000,
            observed_price_value=330000,
            price_verified=False,
            verification_status="google_flights_displayed_round_trip",
            result_url="https://www.google.com/travel/flights/search?observed=1",
            display_offers=[{"price": 330000, "airline": "EASTAR JET", "times": [], "nonstop": True}],
        )


class _Notifier:
    def __init__(self):
        self.messages = []

    async def send(self, platform, recipient_id, text):
        self.messages.append(text)


@pytest.mark.asyncio
async def test_unverified_google_displayed_price_can_alert_in_current_scope(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = db.add_slot(
        platform="telegram",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        target_price=350000,
        nonstop=True,
        checked_bag=0,
    )
    service = FlightService(Settings(_env_file=None), db, provider=_ObservedProvider())
    notifier = _Notifier()
    service.set_notifier(notifier)

    await service.check_slot(slot.id, notify_target=True)

    assert len(notifier.messages) == 1
    assert "330,000KRW" in notifier.messages[0]
    assert notifier.messages[0].count("https://") == 1
