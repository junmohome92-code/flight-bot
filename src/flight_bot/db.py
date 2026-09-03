from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import FlightOffer, WatchSlot

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_slots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_platform TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  origin TEXT NOT NULL,
  destination TEXT NOT NULL,
  depart_date TEXT NOT NULL,
  return_date TEXT NOT NULL,
  nonstop INTEGER NOT NULL DEFAULT 1,
  checked_bag INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_verified_price INTEGER,
  currency TEXT NOT NULL DEFAULT 'KRW',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  FOREIGN KEY(slot_id) REFERENCES watch_slots(id)
);

CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  total_price INTEGER NOT NULL,
  currency TEXT NOT NULL,
  price_verified INTEGER NOT NULL,
  airline TEXT,
  outbound_flight TEXT,
  inbound_flight TEXT,
  carry_on TEXT,
  checked_baggage TEXT,
  booking_provider TEXT,
  booking_url TEXT,
  fetched_at TEXT NOT NULL,
  FOREIGN KEY(slot_id) REFERENCES watch_slots(id)
);

CREATE TABLE IF NOT EXISTS alert_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL,
  platform TEXT NOT NULL,
  recipient_id TEXT NOT NULL,
  total_price INTEGER NOT NULL,
  currency TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  FOREIGN KEY(slot_id) REFERENCES watch_slots(id)
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _slot(row: sqlite3.Row) -> WatchSlot:
        return WatchSlot(
            id=row["id"], owner_platform=row["owner_platform"], owner_id=row["owner_id"],
            origin=row["origin"], destination=row["destination"], depart_date=row["depart_date"],
            return_date=row["return_date"], nonstop=bool(row["nonstop"]), checked_bag=row["checked_bag"],
            enabled=bool(row["enabled"]), last_verified_price=row["last_verified_price"], currency=row["currency"]
        )

    def add_slot(self, *, platform: str, owner_id: str, origin: str, destination: str,
                 depart_date: str, return_date: str, nonstop: bool, checked_bag: int,
                 max_slots: int) -> WatchSlot:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM watch_slots WHERE enabled=1").fetchone()[0]
            if count >= max_slots:
                raise ValueError(f"활성 슬롯은 최대 {max_slots}개까지 가능합니다.")
            cur = conn.execute(
                """INSERT INTO watch_slots
                (owner_platform, owner_id, origin, destination, depart_date, return_date,
                 nonstop, checked_bag, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (platform, owner_id, origin.upper(), destination.upper(), depart_date, return_date,
                 int(nonstop), checked_bag, now, now),
            )
            row = conn.execute("SELECT * FROM watch_slots WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._slot(row)

    def list_slots(self, enabled_only: bool = False) -> list[WatchSlot]:
        sql = "SELECT * FROM watch_slots" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
        with self.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._slot(r) for r in rows]

    def get_slot(self, slot_id: int) -> WatchSlot | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM watch_slots WHERE id=?", (slot_id,)).fetchone()
        return self._slot(row) if row else None

    def set_enabled(self, slot_id: int, enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE watch_slots SET enabled=?, updated_at=? WHERE id=?",
                         (int(enabled), datetime.now(timezone.utc).isoformat(), slot_id))

    def delete_slot(self, slot_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM watch_slots WHERE id=?", (slot_id,))

    def save_offer(self, slot_id: int, offer: FlightOffer) -> None:
        fetched = (offer.fetched_at or datetime.now(timezone.utc)).isoformat()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO offers
                (slot_id, provider, total_price, currency, price_verified, airline,
                 outbound_flight, inbound_flight, carry_on, checked_baggage,
                 booking_provider, booking_url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (slot_id, offer.provider, offer.total_price, offer.currency, int(offer.price_verified),
                 offer.airline, offer.outbound_flight, offer.inbound_flight, offer.carry_on,
                 offer.checked_baggage, offer.booking_provider, offer.booking_url, fetched),
            )
            if offer.price_verified:
                conn.execute("UPDATE watch_slots SET last_verified_price=?, currency=?, updated_at=? WHERE id=?",
                             (offer.total_price, offer.currency, fetched, slot_id))

    def record_alert(self, slot: WatchSlot, offer: FlightOffer) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO alert_history (slot_id, platform, recipient_id, total_price, currency, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (slot.id, slot.owner_platform, slot.owner_id, offer.total_price, offer.currency,
                 datetime.now(timezone.utc).isoformat()),
            )
