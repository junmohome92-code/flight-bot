import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from flight_bot.config import SLOT_DESIGN_CAPACITY
from flight_bot.db import Database, StaleSlotError
from flight_bot.models import FlightOffer


def add(db, n, *, owner_id="1", origin="CJJ", destination="TPE", origin_type="airport", destination_type="airport"):
    depart = date(2026, 9, 18) + timedelta(days=n)
    returning = depart + timedelta(days=2)
    return db.add_slot(
        platform="telegram",
        owner_id=owner_id,
        origin=origin,
        origin_type=origin_type,
        destination=destination,
        destination_type=destination_type,
        depart_date=depart.isoformat(),
        return_date=returning.isoformat(),
        target_price=350000,
        nonstop=False,
        checked_bag=0,
    )


def offer(price=311811):
    return FlightOffer(
        provider="fake",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        total_price=price,
        observed_price_value=price,
        booking_option_price=320000,
        price_verified=False,
        verification_status="booking_option_only",
        fetched_at=datetime.now(timezone.utc),
    )


def test_twenty_slots_are_scoped_per_owner_and_pause_still_occupies(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    owner_a = [add(db, n, owner_id="group-a") for n in range(20)]
    assert [slot.slot_no for slot in owner_a] == list(range(1, 21))
    db.set_enabled(owner_a[0].id, False)
    with pytest.raises(ValueError, match="이 대화의 감시 슬롯 20개"):
        add(db, 20, owner_id="group-a")

    owner_b = [add(db, 100 + n, owner_id="group-b") for n in range(20)]
    assert [slot.slot_no for slot in owner_b] == list(range(1, 21))
    assert len(db.list_slots()) == 40
    assert owner_b[0].id > 20


def test_slot_limit_can_be_lowered_per_owner_without_changing_design_capacity(tmp_path):
    assert SLOT_DESIGN_CAPACITY == 20
    db = Database(str(tmp_path / "db.sqlite"), slot_limit=5)
    assert [add(db, n, owner_id="one").slot_no for n in range(5)] == [1, 2, 3, 4, 5]
    assert [add(db, 20 + n, owner_id="two").slot_no for n in range(5)] == [1, 2, 3, 4, 5]
    with pytest.raises(ValueError, match="5개"):
        add(db, 50, owner_id="one")


def test_delete_reuses_owner_local_number_but_keeps_generation_guard(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    first = add(db, 0)
    second = add(db, 1)
    assert second.slot_no == 2
    db.delete_slot(second.id)
    replacement = add(db, 3)
    assert replacement.slot_no == 2
    assert replacement.generation
    assert replacement.generation != second.generation
    assert first.slot_no == 1


def test_wal_mode_enabled(tmp_path):
    path = tmp_path / "db.sqlite"
    Database(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_set_target_missing_slot_fails(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        db.set_target(999, 330000)


def test_owner_filter_and_local_lookup_do_not_expose_other_groups(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    one = add(db, 0, owner_id="one")
    two = add(db, 1, owner_id="two")
    assert one.slot_no == 1
    assert two.slot_no == 1
    assert [s.owner_id for s in db.list_slots(owner_platform="telegram", owner_id="one")] == ["one"]
    assert db.get_owned_slot(two.id, "telegram", "one") is None
    assert db.get_owned_slot_by_no(1, "telegram", "one").id == one.id
    assert db.get_owned_slot_by_no(1, "telegram", "two").id == two.id


def test_stale_generation_cannot_write_into_reused_internal_id(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    old = add(db, 0)
    db.delete_slot(old.id)
    replacement = add(db, 1)
    assert replacement.generation != old.generation
    with pytest.raises(StaleSlotError):
        db.save_offer(
            old.id,
            offer(),
            expected_generation=old.generation,
            expected_revision=old.revision,
        )


def test_explicit_location_types_round_trip(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = add(
        db,
        0,
        owner_id="city-group",
        origin="SEL",
        destination="TYO",
        origin_type="city",
        destination_type="city",
    )
    loaded = db.get_slot(slot.id)
    assert loaded.origin_type == "city"
    assert loaded.destination_type == "city"


def test_offer_history_preserves_observed_booking_and_verified_columns(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = add(db, 0)
    value = FlightOffer(
        provider="fake",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        total_price=325400,
        observed_price_value=311811,
        booking_option_price=319000,
        verified_checkout_price=325400,
        price_verified=True,
        verification_status="external_checkout_final_total",
        fetched_at=datetime.now(timezone.utc),
    )
    db.save_offer(slot.id, value, expected_generation=slot.generation, expected_revision=slot.revision)
    with sqlite3.connect(db.path) as conn:
        row = conn.execute(
            "SELECT observed_price, booking_option_price, verified_checkout_price, verification_status FROM offers"
        ).fetchone()
    assert row == (311811, 319000, 325400, "external_checkout_final_total")


def test_legacy_schema_is_additively_migrated_without_reset(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE watch_slots (
              id INTEGER PRIMARY KEY,
              owner_platform TEXT NOT NULL,
              owner_id TEXT NOT NULL,
              origin TEXT NOT NULL,
              destination TEXT NOT NULL,
              depart_date TEXT NOT NULL,
              return_date TEXT NOT NULL,
              nonstop INTEGER NOT NULL DEFAULT 0,
              checked_bag INTEGER NOT NULL DEFAULT 0,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE offers (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              slot_id INTEGER NOT NULL,
              provider TEXT NOT NULL,
              total_price INTEGER NOT NULL,
              currency TEXT NOT NULL,
              fetched_at TEXT NOT NULL
            );
            CREATE TABLE alert_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              slot_id INTEGER NOT NULL,
              platform TEXT NOT NULL,
              recipient_id TEXT NOT NULL,
              total_price INTEGER NOT NULL,
              currency TEXT NOT NULL,
              sent_at TEXT NOT NULL
            );
            INSERT INTO watch_slots
              (id, owner_platform, owner_id, origin, destination, depart_date, return_date, created_at, updated_at)
            VALUES
              (1, 'telegram', 'group-a', 'CJJ', 'TPE', '2026-09-18', '2026-09-20', 'x', 'x'),
              (2, 'telegram', 'group-b', 'SEL', 'TYO', '2026-09-22', '2026-09-24', 'x', 'x');
            """
        )

    db = Database(str(path))
    with sqlite3.connect(path) as conn:
        watch_columns = {row[1] for row in conn.execute("PRAGMA table_info(watch_slots)")}
        offer_columns = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
        alert_columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_history)")}
        first = conn.execute(
            "SELECT slot_no, generation, revision, target_price, enabled, origin_type, destination_type "
            "FROM watch_slots WHERE id=1"
        ).fetchone()
        second = conn.execute(
            "SELECT slot_no, origin_type, destination_type FROM watch_slots WHERE id=2"
        ).fetchone()

    assert {"slot_no", "origin_type", "destination_type", "last_verified_price", "currency", "generation", "revision"} <= watch_columns
    assert {"price_verified", "booking_url", "observed_price", "verified_checkout_price"} <= offer_columns
    assert {"delivery_state", "dedupe_key", "error"} <= alert_columns
    assert first[0] == 1
    assert first[1]
    assert first[2] == 1
    assert first[3] == 0
    assert first[4] == 0
    assert first[5:] == ("airport", "airport")
    # Each owner starts its own visible slot numbering at #1 and legacy city
    # rows are backfilled to explicit city types.
    assert second == (1, "city", "city")
