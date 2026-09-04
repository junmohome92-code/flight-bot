import sqlite3

import pytest

from flight_bot.db import Database


def add(db, n):
    return db.add_slot(
        platform="telegram",
        owner_id="1",
        origin="CJJ",
        destination="TPE",
        depart_date=f"2026-09-{18+n:02d}",
        return_date=f"2026-09-{20+n:02d}",
        target_price=350000,
        nonstop=False,
        checked_bag=0,
    )


def test_exactly_three_fixed_slots_and_pause_still_occupies(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    assert [add(db, n).id for n in range(3)] == [1, 2, 3]
    db.set_enabled(1, False)
    with pytest.raises(ValueError):
        add(db, 3)


def test_delete_reuses_fixed_slot_number(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    add(db, 0)
    add(db, 1)
    add(db, 2)
    db.delete_slot(2)
    assert add(db, 3).id == 2


def test_wal_mode_enabled(tmp_path):
    path = tmp_path / "db.sqlite"
    Database(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_set_target_missing_slot_fails(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        db.set_target(1, 330000)


def test_legacy_watch_table_gets_last_verified_and_currency_columns(tmp_path):
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
            """
        )

    Database(str(path))
    with sqlite3.connect(path) as conn:
        watch_columns = {row[1] for row in conn.execute("PRAGMA table_info(watch_slots)")}
        offer_columns = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}

    assert "last_verified_price" in watch_columns
    assert "currency" in watch_columns
    assert "price_verified" in offer_columns
    assert "booking_url" in offer_columns
