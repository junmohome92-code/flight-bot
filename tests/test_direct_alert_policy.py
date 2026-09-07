from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


def _service_and_slot(tmp_path, *, max_offers=5):
    settings = Settings(_env_file=None, alert_max_offers=max_offers)
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
    return service, slot


def _row(index: int, price: int) -> dict:
    return {
        "price": price,
        "times": ["23:40", "01:10", "13:15", "16:40"],
        "outbound_airline": "이스타항공",
        "return_airline": "에어로케이",
        "outbound_airline_code": "ZE",
        "return_airline_code": "RF",
        "outbound_flight": f"ZE{781 + index}",
        "return_flight": f"RF{321 + index}",
        "nonstop": True,
    }


def test_default_product_policy_is_direct_round_trip_top_five():
    settings = Settings(_env_file=None)
    assert settings.alert_nonstop_only is True
    assert settings.alert_max_offers == 5
    assert settings.require_verified_alerts is False


def test_alert_message_lists_ranked_naver_round_trip_rows(tmp_path):
    service, slot = _service_and_slot(tmp_path)
    result_url = "https://flight.naver.com/flights/international/example"
    rows = [_row(i, 319620 + i * 10000) for i in range(5)]
    offer = FlightOffer(
        provider="naver-flights-sse",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        total_price=319620,
        observed_price_value=319620,
        result_url=result_url,
        checked_baggage="정보 확인 불가",
        display_offers=rows,
        fetched_at=datetime.now(timezone.utc),
    )

    message = service.format_offer(slot, offer)

    assert "Naver Flights 직항 왕복가 TOP 5" in message
    assert "319,620KRW" in message
    assert "359,620KRW" in message
    assert "가는편: 이스타항공 ZE781" in message
    assert "오는편: 에어로케이 RF321" in message
    assert message.count("https://") == 1
    assert result_url in message


def test_alert_message_dedupes_identical_flight_pair(tmp_path):
    service, slot = _service_and_slot(tmp_path)
    row = _row(0, 319620)
    offer = FlightOffer(
        provider="naver-flights-sse",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        total_price=319620,
        observed_price_value=319620,
        result_url="https://flight.naver.com/flights/international/example",
        display_offers=[row, dict(row)],
    )

    message = service.format_offer(slot, offer)
    assert message.count("319,620KRW") == 1
    assert "2. " not in message


class _ObservedProvider:
    name = "naver-flights-sse"
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
            verification_status="naver_sse_round_trip_fare",
            result_url="https://flight.naver.com/flights/international/example",
            display_offers=[_row(0, 330000)],
        )


class _Notifier:
    def __init__(self):
        self.messages = []

    async def send(self, platform, recipient_id, text):
        self.messages.append(text)


@pytest.mark.asyncio
async def test_naver_api_displayed_price_can_alert_in_current_scope(tmp_path):
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
