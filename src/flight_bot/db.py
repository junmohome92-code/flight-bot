from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import ALERT_ARMED, ALERTED, FlightOffer, WatchSlot

MAX_SLOTS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_slots (
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
  target_price INTEGER NOT NULL DEFAULT 0,
  alert_state TEXT NOT NULL DEFAULT 'ARMED',
  last_observed_price INTEGER,
  lowest_observed_price INTEGER,
  last_verified_price INTEGER,
  last_checked_at TEXT,
  last_alerted_price INTEGER,
  last_alerted_at TEXT,
  currency TEXT NOT NULL DEFAULT 'KRW',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
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
  separate_ticket INTEGER,
  nonstop INTEGER,
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

CREATE TABLE IF NOT EXISTS search_runs_v2 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  FOREIGN KEY(slot_id) REFERENCES watch_slots(id)
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate_legacy(conn)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _migrate_legacy(self, conn: sqlite3.Connection) -> None:
        # CREATE TABLE IF NOT EXISTS does not add new columns to an existing DB.
        # Keep this list aligned with every column read by _slot/save_offer so an
        # older home-server database can start safely after an upgrade.
        columns = self._columns(conn, "watch_slots")
        additions = {
            "target_price": "INTEGER NOT NULL DEFAULT 0",
            "alert_state": "TEXT NOT NULL DEFAULT 'ARMED'",
            "last_observed_price": "INTEGER",
            "lowest_observed_price": "INTEGER",
            "last_verified_price": "INTEGER",
            "last_checked_at": "TEXT",
            "last_alerted_price": "INTEGER",
            "last_alerted_at": "TEXT",
            "currency": "TEXT NOT NULL DEFAULT 'KRW'",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE watch_slots ADD COLUMN {name} {ddl}")

        offer_columns = self._columns(conn, "offers")
        offer_additions = {
            "price_verified": "INTEGER NOT NULL DEFAULT 0",
            "airline": "TEXT",
            "outbound_flight": "TEXT",
            "inbound_flight": "TEXT",
            "separate_ticket": "INTEGER",
            "nonstop": "INTEGER",
            "booking_provider": "TEXT",
            "booking_url": "TEXT",
        }
        for name, ddl in offer_additions.items():
            if name not in offer_columns:
                conn.execute(f"ALTER TABLE offers ADD COLUMN {name} {ddl}")

    @staticmethod
    def _slot(row: sqlite3.Row) -> WatchSlot:
        return WatchSlot(
            id=row["id"],
            owner_platform=row["owner_platform"],
            owner_id=row["owner_id"],
            origin=row["origin"],
            destination=row["destination"],
            depart_date=row["depart_date"],
            return_date=row["return_date"],
            nonstop=bool(row["nonstop"]),
            checked_bag=row["checked_bag"],
            enabled=bool(row["enabled"]),
            target_price=row["target_price"],
            alert_state=row["alert_state"],
            last_observed_price=row["last_observed_price"],
            lowest_observed_price=row["lowest_observed_price"],
            last_verified_price=row["last_verified_price"],
            last_checked_at=row["last_checked_at"],
            last_alerted_price=row["last_alerted_price"],
            last_alerted_at=row["last_alerted_at"],
            currency=row["currency"],
        )

    def _occupied_ids(self, conn: sqlite3.Connection) -> set[int]:
        return {row[0] for row in conn.execute("SELECT id FROM watch_slots WHERE id BETWEEN 1 AND 3")}

    def add_slot(
        self,
        *,
        platform: str,
        owner_id: str,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str,
        target_price: int,
        nonstop: bool,
        checked_bag: int,
    ) -> WatchSlot:
        if target_price <= 0:
            raise ValueError("목표가는 0원보다 커야 합니다.")
        origin = origin.strip().upper()
        destination = destination.strip().upper()
        if not origin or not destination or origin == destination:
            raise ValueError("출발지와 도착지를 서로 다른 공항 코드로 입력해 주세요.")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            occupied = self._occupied_ids(conn)
            slot_id = next((idx for idx in range(1, MAX_SLOTS + 1) if idx not in occupied), None)
            if slot_id is None:
                raise ValueError("저장 슬롯은 정확히 3개이며 모두 사용 중입니다. 기존 슬롯을 삭제해 주세요.")
            conn.execute(
                """INSERT INTO watch_slots
                (id, owner_platform, owner_id, origin, destination, depart_date, return_date,
                 nonstop, checked_bag, enabled, target_price, alert_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                (
                    slot_id,
                    platform,
                    owner_id,
                    origin,
                    destination,
                    depart_date,
                    return_date,
                    int(nonstop),
                    max(0, checked_bag),
                    target_price,
                    ALERT_ARMED,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM watch_slots WHERE id=?", (slot_id,)).fetchone()
        return self._slot(row)

    def list_slots(self, enabled_only: bool = False) -> list[WatchSlot]:
        with self.connect() as conn:
            sql = "SELECT * FROM watch_slots WHERE id BETWEEN 1 AND 3"
            if enabled_only:
                sql += " AND enabled=1"
            sql += " ORDER BY id"
            rows = conn.execute(sql).fetchall()
        return [self._slot(row) for row in rows]

    def get_slot(self, slot_id: int) -> WatchSlot | None:
        if slot_id not in {1, 2, 3}:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM watch_slots WHERE id=?", (slot_id,)).fetchone()
        return self._slot(row) if row else None

    def set_enabled(self, slot_id: int, enabled: bool) -> None:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE watch_slots SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), datetime.now(timezone.utc).isoformat(), slot_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"슬롯 #{slot_id}을 찾을 수 없습니다.")

    def set_target(self, slot_id: int, target_price: int) -> None:
        if target_price <= 0:
            raise ValueError("목표가는 0원보다 커야 합니다.")
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE watch_slots SET target_price=?, alert_state=?, updated_at=? WHERE id=?",
                (target_price, ALERT_ARMED, datetime.now(timezone.utc).isoformat(), slot_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"슬롯 #{slot_id}을 찾을 수 없습니다.")

    def delete_slot(self, slot_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM offers WHERE slot_id=?", (slot_id,))
            conn.execute("DELETE FROM alert_history WHERE slot_id=?", (slot_id,))
            conn.execute("DELETE FROM search_runs_v2 WHERE slot_id=?", (slot_id,))
            conn.execute("DELETE FROM watch_slots WHERE id=?", (slot_id,))

    def start_search(self, slot_id: int, provider: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO search_runs_v2(slot_id, provider, status, started_at) VALUES (?, ?, 'running', ?)",
                (slot_id, provider, now),
            )
            return int(cur.lastrowid)

    def finish_search(self, run_id: int, *, status: str, message: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE search_runs_v2 SET status=?, message=?, finished_at=? WHERE id=?",
                (status, message, datetime.now(timezone.utc).isoformat(), run_id),
            )

    def save_offer(self, slot_id: int, offer: FlightOffer) -> None:
        fetched = (offer.fetched_at or datetime.now(timezone.utc)).isoformat()
        observed = int((offer.raw or {}).get("observed_price") or offer.total_price)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO offers
                (slot_id, provider, total_price, currency, price_verified, airline,
                 outbound_flight, inbound_flight, separate_ticket, nonstop,
                 booking_provider, booking_url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    slot_id,
                    offer.provider,
                    offer.total_price,
                    offer.currency,
                    int(offer.price_verified),
                    offer.airline,
                    offer.outbound_flight,
                    offer.inbound_flight,
                    None if offer.separate_ticket is None else int(offer.separate_ticket),
                    None if offer.nonstop is None else int(offer.nonstop),
                    offer.booking_provider,
                    offer.booking_url,
                    fetched,
                ),
            )
            row = conn.execute(
                "SELECT lowest_observed_price FROM watch_slots WHERE id=?",
                (slot_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"슬롯 #{slot_id}을 찾을 수 없습니다.")
            current_low = row[0]
            new_low = observed if current_low is None else min(current_low, observed)
            conn.execute(
                """UPDATE watch_slots
                SET last_observed_price=?, lowest_observed_price=?, last_checked_at=?, currency=?,
                    last_verified_price=CASE WHEN ? THEN ? ELSE last_verified_price END,
                    updated_at=? WHERE id=?""",
                (
                    observed,
                    new_low,
                    fetched,
                    offer.currency,
                    int(offer.price_verified),
                    offer.total_price,
                    fetched,
                    slot_id,
                ),
            )

    def set_alert_state(self, slot_id: int, state: str, *, alerted_price: int | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            if state == ALERTED:
                conn.execute(
                    "UPDATE watch_slots SET alert_state=?, last_alerted_price=?, last_alerted_at=?, updated_at=? WHERE id=?",
                    (state, alerted_price, now, now, slot_id),
                )
            else:
                conn.execute(
                    "UPDATE watch_slots SET alert_state=?, updated_at=? WHERE id=?",
                    (state, now, slot_id),
                )

    def record_alert(self, slot: WatchSlot, offer: FlightOffer) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO alert_history (slot_id, platform, recipient_id, total_price, currency, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    slot.id,
                    slot.owner_platform,
                    slot.owner_id,
                    offer.total_price,
                    offer.currency,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
