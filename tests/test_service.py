import asyncio
from datetime import datetime, timezone

import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.models import FlightOffer
from flight_bot.service import FlightService


class FakeProvider:
    name = "fake"
    accepted_for_alerts = True

    def __init__(self, prices, *, delay: float = 0.0, verified: bool = True, accepted_for_alerts: bool = True):
        self.prices = list(prices)
        self.calls = []
        self.delay = delay
        self.verified = verified
        self.accepted_for_alerts = accepted_for_alerts

    async def search(self, slot, *, verify_below_price=None):
        self.calls.append((slot.id, slot.generation, slot.revision, verify_below_price))
        if self.delay:
            await asyncio.sleep(self.delay)
        price = self.prices.pop(0)
        return FlightOffer(
            provider=self.name,
            origin=slot.origin,
            destination=slot.destination,
            depart_date=slot.depart_date,
            return_date=slot.return_date,
            total_price=price,
            observed_price_value=price,
            verified_checkout_price=price if self.verified else None,
            price_verified=self.verified,
            verification_status="external_checkout_final_total" if self.verified else "naver_sse_round_trip_fare",
            result_url="https://flight.naver.com/flights/international/test",
            display_offers=[
                {
                    "price": price,
                    "outbound_airline": "TEST AIR",
                    "return_airline": "TEST AIR",
                    "outbound_flight": "TA100",
                    "return_flight": "TA101",
                    "times": ["10:00", "12:00", "15:00", "17:00"],
                    "nonstop": True,
                }
            ],
            raw={"observed_price": price},
            fetched_at=datetime.now(timezone.utc),
        )


class FakeNotifier:
    def __init__(self, db: Database | None = None, *, fail: bool = False):
        self.messages = []
        self.db = db
        self.fail = fail
        self.state_during_send = None

    async def send(self, platform, recipient_id, text):
        if self.db:
            self.state_during_send = self.db.get_slot(1).alert_state
        if self.fail:
            raise RuntimeError("send failed")
        self.messages.append((platform, recipient_id, text))


def make_slot(db: Database, *, owner_id="1"):
    return db.add_slot(
        platform="telegram",
        owner_id=owner_id,
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        target_price=350000,
        nonstop=True,
        checked_bag=0,
    )


@pytest.mark.asyncio
async def test_target_alert_is_one_shot_until_target_is_explicitly_changed(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([340000, 330000, 360000, 345000, 340000])
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    for _ in range(4):
        await service.check_slot(slot.id, notify_target=True)

    assert len(notifier.messages) == 1
    assert notifier.messages[0][2].startswith("🔥 목표가 도달")
    assert [call[3] for call in provider.calls] == [350000, None, None, None]
    assert db.get_slot(slot.id).alert_state == "ALERTED"

    db.set_target(slot.id, 355000)
    await service.check_slot(slot.id, notify_target=True)
    assert len(notifier.messages) == 2
    assert db.get_slot(slot.id).alert_state == "ALERTED"


@pytest.mark.asyncio
async def test_daily_summary_is_sent_once_when_requested_and_uses_ranked_window(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([400000, 390000])
    service = FlightService(Settings(), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    await service.check_slot(slot.id, notify_target=True, notify_daily_summary=False)
    assert notifier.messages == []

    await service.check_slot(slot.id, notify_target=True, notify_daily_summary=True)
    assert len(notifier.messages) == 1
    text = notifier.messages[0][2]
    assert text.startswith("📊 정기 가격 알림")
    assert "Naver Flights 직항 왕복가" in text
    assert "390,000" in text
    assert text.count("https://") == 1


@pytest.mark.asyncio
async def test_same_scan_does_not_send_target_and_daily_summary_twice(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([340000])
    service = FlightService(Settings(), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    await service.check_slot(slot.id, notify_target=True, notify_daily_summary=True)

    assert len(notifier.messages) == 1
    assert notifier.messages[0][2].startswith("🔥 목표가 도달")


@pytest.mark.asyncio
async def test_unverified_below_target_never_alerts_when_required(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([330000], verified=False)
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    await service.check_slot(slot.id, notify_target=True)

    assert notifier.messages == []
    assert db.get_slot(slot.id).alert_state == "ARMED"
    assert db.get_slot(slot.id).last_observed_price == 330000


@pytest.mark.asyncio
async def test_provider_hard_alert_gate_blocks_provider_even_when_verified_requirement_disabled(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([330000], verified=False, accepted_for_alerts=False)
    service = FlightService(Settings(require_verified_alerts=False), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    await service.check_slot(slot.id, notify_target=True)

    assert notifier.messages == []
    assert db.get_slot(slot.id).alert_state == "ARMED"


@pytest.mark.asyncio
async def test_alert_is_marked_sending_before_external_side_effect(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([330000])
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier(db)
    service.set_notifier(notifier)

    await service.check_slot(slot.id, notify_target=True)

    assert notifier.state_during_send == "SENDING"
    assert db.get_slot(slot.id).alert_state == "ALERTED"


@pytest.mark.asyncio
async def test_failed_delivery_rearms_and_records_failed_attempt(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([330000])
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier(db, fail=True)
    service.set_notifier(notifier)

    result = await service.check_slot(slot.id, notify_target=True)

    assert "알림 전송 실패" in result
    assert db.get_slot(slot.id).alert_state == "ARMED"
    with db.connect() as conn:
        row = conn.execute("SELECT delivery_state FROM alert_history").fetchone()
    assert row[0] == "FAILED"


@pytest.mark.asyncio
async def test_overlapping_checks_cannot_duplicate_same_below_target_alert(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = make_slot(db)
    provider = FakeProvider([340000, 339000], delay=0.02)
    service = FlightService(Settings(require_verified_alerts=True), db, provider=provider)
    notifier = FakeNotifier()
    service.set_notifier(notifier)

    await asyncio.gather(
        service.check_slot(slot.id, notify_target=True),
        service.check_slot(slot.id, notify_target=True),
    )

    assert len(notifier.messages) == 1
    assert [call[3] for call in provider.calls] == [350000, None]


@pytest.mark.asyncio
async def test_overlapping_full_scans_are_suppressed_not_queued(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    make_slot(db)
    provider = FakeProvider([400000], delay=0.05)
    service = FlightService(Settings(), db, provider=provider)

    first, second = await asyncio.gather(service.check_all(), service.check_all())

    assert sorted([first, second]) == [False, True]
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_delete_waits_for_running_check_and_cannot_reuse_slot_mid_search(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    original = make_slot(db)
    provider = FakeProvider([400000], delay=0.05)
    service = FlightService(Settings(), db, provider=provider)

    check_task = asyncio.create_task(service.check_slot(original.id))
    await asyncio.sleep(0.01)
    delete_task = asyncio.create_task(service.command("telegram", "1", "/flight delete 1"))
    await asyncio.gather(check_task, delete_task)

    assert db.get_slot(1) is None
    replacement = await service.command(
        "telegram", "1", "/flight add CJJ TPE 2026-09-19 2026-09-21 350000"
    )
    assert "추가했습니다" in replacement
    assert db.get_slot(1).generation != original.generation


@pytest.mark.asyncio
async def test_commands_cannot_modify_another_owners_slot(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    make_slot(db, owner_id="owner-a")
    service = FlightService(Settings(), db, provider=FakeProvider([]))

    result = await service.command("telegram", "owner-b", "/flight delete 1")

    assert "아닙니다" in result
    assert db.get_slot(1) is not None


@pytest.mark.asyncio
async def test_target_command_rejects_missing_slot(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    service = FlightService(Settings(), db, provider=FakeProvider([]))
    result = await service.command("telegram", "1", "/flight target 1 330000")
    assert "찾을 수 없" in result


@pytest.mark.asyncio
async def test_add_rejects_return_date_before_departure(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    service = FlightService(Settings(), db, provider=FakeProvider([]))
    result = await service.command(
        "telegram",
        "1",
        "/flight add CJJ TPE 2026-09-20 2026-09-18 350000",
    )
    assert "귀국일" in result


@pytest.mark.asyncio
async def test_add_rejects_non_iata_airport_code(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    service = FlightService(Settings(), db, provider=FakeProvider([]))
    result = await service.command(
        "telegram",
        "1",
        "/flight add CHEONGJU TPE 2026-09-18 2026-09-20 350000",
    )
    assert "IATA" in result
