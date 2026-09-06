import sqlite3
from datetime import datetime, timezone

import pytest

from flight_bot.db import Database, StaleSlotError
from flight_bot.models import FlightOffer


def add(db, n, *, owner_id="1"):
    return db.add_slot(
        platform="telegram",
        owner_id=owner_id,
        origin="CJJ",
        destination="TPE",
        depart_date=f"2026-09-{18+n:02d}",
        return_date=f"2026-09-{20+n:02d}",
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


def test_exactly_three_fixed_slots_and_pause_still_occupies(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    assert [add(db, n).id for n in range(3)] == [1, 2, 3]
    db.set_enabled(1, False)
    with pytest.raises(ValueError):
        add(db, 3)


def test_delete_reuses_number_but_changes_generation(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    first = add(db, 0)
    add(db, 1)
    add(db, 2)
    db.delete_slot(2)
    replacement = add(db, 3)
    assert replacement.id == 2
    assert replacement.generation
    assert replacement.generation != first.generation or replacement.id != first.id


def test_wal_mode_enabled(tmp_path):
    path = tmp_path / "db.sqlite"
    Database(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_set_target_missing_slot_fails(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        db.set_target(1, 330000)


def test_owner_filter_does_not_expose_other_users_slots(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    add(db, 0, owner_id="one")
    add(db, 1, owner_id="two")
    assert [s.owner_id for s in db.list_slots(owner_platform="telegram", owner_id="one")] == ["one"]
    assert db.get_owned_slot(2, "telegram", "one") is None


def test_stale_generation_cannot_write_into_reused_slot(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    old = add(db, 0)
    db.delete_slot(old.id)
    replacement = add(db, 1)
    assert replacement.id == old.id
    assert replacement.generation != old.generation
    with pytest.raises(StaleSlotError):
        db.save_offer(
            old.id,
            offer(),
            expected_generation=old.generation,
            expected_revision=old.revision,
        )


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


def test_legacy_schema_is_migrated_and_zero_target_is_paused(tmp_path):
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
              (1, 'telegram', '1', 'CJJ', 'TPE', '2026-09-18', '2026-09-20', 'x', 'x');
            """
        )

    db = Database(str(path))
    with sqlite3.connect(path) as conn:
        watch_columns = {row[1] for row in conn.execute("PRAGMA table_info(watch_slots)")}
        offer_columns = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
        alert_columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_history)")}
        migrated = conn.execute("SELECT generation, revision, target_price, enabled FROM watch_slots WHERE id=1").fetchone()

    assert {"last_verified_price", "currency", "generation", "revision"} <= watch_columns
    assert {"price_verified", "booking_url", "observed_price", "verified_checkout_price"} <= offer_columns
    assert {"delivery_state", "dedupe_key", "error"} <= alert_columns
    assert migrated[0]
    assert migrated[1] == 1
    assert migrated[2] == 0
    assert migrated[3] == 0
