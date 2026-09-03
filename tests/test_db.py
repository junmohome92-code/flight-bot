import sqlite3

import pytest

from flight_bot.db import Database


def add(db, n):
    return db.add_slot(platform="telegram", owner_id="1", origin="CJJ", destination="TPE",
                       depart_date=f"2026-09-{18+n:02d}", return_date=f"2026-09-{20+n:02d}",
                       target_price=350000, nonstop=False, checked_bag=0)


def test_exactly_three_fixed_slots_and_pause_still_occupies(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    assert [add(db, n).id for n in range(3)] == [1, 2, 3]
    db.set_enabled(1, False)
    with pytest.raises(ValueError):
        add(db, 3)


def test_delete_reuses_fixed_slot_number(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    add(db, 0); add(db, 1); add(db, 2)
    db.delete_slot(2)
    assert add(db, 3).id == 2


def test_wal_mode_enabled(tmp_path):
    path = tmp_path / "db.sqlite"
    Database(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
