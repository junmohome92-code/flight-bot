from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import SLOT_DESIGN_CAPACITY
from .models import ALERT_ARMED, ALERTED, FlightOffer, WatchSlot

DEFAULT_ACTIVE_SLOT_LIMIT = SLOT_DESIGN_CAPACITY


class StaleSlotError(RuntimeError):
    """A search finished for a slot generation/revision that no longer exists."""


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
  generation TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  total_price INTEGER NOT NULL,
  observed_price INTEGER,
  booking_option_price INTEGER,
  verified_checkout_price INTEGER,
  verification_status TEXT NOT NULL DEFAULT 'unverified',
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
  delivery_state TEXT NOT NULL DEFAULT 'SENT',
  dedupe_key TEXT,
  error TEXT,
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

CREATE INDEX IF NOT EXISTS idx_offers_slot_fetched ON offers(slot_id, fetched_at);
CREATE INDEX IF NOT EXISTS idx_alert_history_slot_sent ON alert_history(slot_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_search_runs_slot_started ON search_runs_v2(slot_id, started_at);
"""


class Database:
    def __init__(self, path: str, *, slot_limit: int = DEFAULT_ACTIVE_SLOT_LIMIT):
        if not 1 <= int(slot_limit) <= SLOT_DESIGN_CAPACITY:
            raise ValueError(f"slot_limit must be between 1 and {SLOT_DESIGN_CAPACITY}")
        self.path = path
        self.slot_limit = int(slot_limit)
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
        watch_columns = self._columns(conn, "watch_slots")
        watch_additions = {
            "target_price": "INTEGER NOT NULL DEFAULT 0",
            "alert_state": "TEXT NOT NULL DEFAULT 'ARMED'",
            "last_observed_price": "INTEGER",
            "lowest_observed_price": "INTEGER",
            "last_verified_price": "INTEGER",
            "last_checked_at": "TEXT",
            "last_alerted_price": "INTEGER",
            "last_alerted_at": "TEXT",
            "currency": "TEXT NOT NULL DEFAULT 'KRW'",
            "generation": "TEXT",
            "revision": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, ddl in watch_additions.items():
            if name not in watch_columns:
                conn.execute(f"ALTER TABLE watch_slots ADD COLUMN {name} {ddl}")
        conn.execute(
            "UPDATE watch_slots SET generation=lower(hex(randomblob(16))) WHERE generation IS NULL OR generation=''"
        )
        conn.execute("UPDATE watch_slots SET revision=1 WHERE revision IS NULL OR revision<1")
        conn.execute("UPDATE watch_slots SET enabled=0 WHERE target_price<=0")

        offer_columns = self._columns(conn, "offers")
        offer_additions = {
            "price_verified": "INTEGER NOT NULL DEFAULT 0",
            "observed_price": "INTEGER",
            "booking_option_price": "INTEGER",
            "verified_checkout_price": "INTEGER",
            "verification_status": "TEXT NOT NULL DEFAULT 'unverified'",
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
        conn.execute("UPDATE offers SET observed_price=total_price WHERE observed_price IS NULL")

        alert_columns = self._columns(conn, "alert_history")
        alert_additions = {
            "delivery_state": "TEXT NOT NULL DEFAULT 'SENT'",
            "dedupe_key": "TEXT",
            "error": "TEXT",
        }
        for name, ddl in alert_additions.items():
            if name not in alert_columns:
                conn.execute(f"ALTER TABLE alert_history ADD COLUMN {name} {ddl}")

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
            generation=str(row["generation"] or ""),
            revision=int(row["revision"] or 1),
        )

    def _occupied_ids(self, conn: sqlite3.Connection) -> set[int]:
        return {
            row[0]
            for row in conn.execute(
                "SELECT id FROM watch_slots WHERE id BETWEEN 1 AND ?",
                (SLOT_DESIGN_CAPACITY,),
            )
        }

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
        generation = uuid4().hex
        with self.connect() as conn:
            occupied = self._occupied_ids(conn)
            slot_id = next((idx for idx in range(1, self.slot_limit + 1) if idx not in occupied), None)
            if slot_id is None:
                raise ValueError(
                    f"감시 슬롯 {self.slot_limit}개가 모두 사용 중입니다. 기존 슬롯을 삭제해 주세요."
                )
            conn.execute(
                """INSERT INTO watch_slots
                (id, owner_platform, owner_id, origin, destination, depart_date, return_date,
                 nonstop, checked_bag, enabled, target_price, alert_state, generation, revision,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 1, ?, ?)""",
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
                    generation,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM watch_slots WHERE id=?", (slot_id,)).fetchone()
        return self._slot(row)

    def list_slots(
        self,
        enabled_only: bool = False,
        *,
        owner_platform: str | None = None,
        owner_id: str | None = None,
    ) -> list[WatchSlot]:
        with self.connect() as conn:
            sql = "SELECT * FROM watch_slots WHERE id BETWEEN 1 AND ?"
            params: list[object] = [SLOT_DESIGN_CAPACITY]
            if enabled_only:
                sql += " AND enabled=1"
            if owner_platform is not None:
                sql += " AND owner_platform=?"
                params.append(owner_platform)
            if owner_id is not None:
                sql += " AND owner_id=?"
                params.append(owner_id)
            sql += " ORDER BY id"
            rows = conn.execute(sql, params).fetchall()
        return [self._slot(row) for row in rows]

    def get_slot(self, slot_id: int) -> WatchSlot | None:
        if not 1 <= int(slot_id) <= SLOT_DESIGN_CAPACITY:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM watch_slots WHERE id=?", (slot_id,)).fetchone()
        return self._slot(row) if row else None

    def get_owned_slot(self, slot_id: int, platform: str, owner_id: str) -> WatchSlot | None:
        slot = self.get_slot(slot_id)
        if not slot:
            return None
        if slot.owner_platform != platform or slot.owner_id != owner_id:
            return None
        return slot

    def set_enabled(self, slot_id: int, enabled: bool) -> None:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE watch_slots SET enabled=?, revision=revision+1, updated_at=? WHERE id=?",
                (int(enabled), datetime.now(timezone.utc).isoformat(), slot_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"슬롯 #{slot_id}을 찾을 수 없습니다.")

    def set_target(self, slot_id: int, target_price: int) -> None:
        if target_price <= 0:
            raise ValueError("목표가는 0원보다 커야 합니다.")
        with self.connect() as conn:
            cur = conn.execute(
                """UPDATE watch_slots
                SET target_price=?, alert_state=?, revision=revision+1, updated_at=?
                WHERE id=?""",
                (target_price, ALERT_ARMED, datetime.now(timezone.utc).isoformat(), slot_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"슬롯 #{slot_id}을 찾을 수 없습니다.")

    def delete_slot(self, slot_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM offers WHERE slot_id=?", (slot_id,))
            conn.execute("DELETE FROM alert_history WHERE slot_id=?", (slot_id,))
            conn.execute("DELETE FROM search_runs_v2 WHERE slot_id=?", (slot_id,))
            cur = conn.execute("DELETE FROM watch_slots WHERE id=?", (slot_id,))
            if cur.rowcount == 0:
                raise ValueError(f"슬롯 #{slot_id}을 찾을 수 없습니다.")

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

    def assert_slot_version(self, slot: WatchSlot) -> WatchSlot:
        current = self.get_slot(slot.id)
        if (
            current is None
            or current.generation != slot.generation
            or current.revision != slot.revision
        ):
            raise StaleSlotError(f"slot #{slot.id} changed while search was running")
        return current

    def save_offer(
        self,
        slot_id: int,
        offer: FlightOffer,
        *,
        expected_generation: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        fetched = (offer.fetched_at or datetime.now(timezone.utc)).isoformat()
        observed = int(offer.observed_price)
        verified = offer.verified_price
        with self.connect() as conn:
            row = conn.execute(
                "SELECT generation, revision, lowest_observed_price FROM watch_slots WHERE id=?",
                (slot_id,),
            ).fetchone()
            if row is None:
                raise StaleSlotError(f"slot #{slot_id} no longer exists")
            if expected_generation is not None and str(row["generation"] or "") != expected_generation:
                raise StaleSlotError(f"slot #{slot_id} generation changed")
            if expected_revision is not None and int(row["revision"] or 1) != expected_revision:
                raise StaleSlotError(f"slot #{slot_id} revision changed")

            conn.execute(
                """INSERT INTO offers
                (slot_id, provider, total_price, observed_price, booking_option_price,
                 verified_checkout_price, verification_status, currency, price_verified,
                 airline, outbound_flight, inbound_flight, separate_ticket, nonstop,
                 booking_provider, booking_url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    slot_id,
                    offer.provider,
                    offer.total_price,
                    observed,
                    offer.booking_option_price,
                    verified,
                    offer.verification_status,
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
            current_low = row["lowest_observed_price"]
            new_low = observed if current_low is None else min(int(current_low), observed)
            where = "id=?"
            params: list[object] = [
                observed,
                new_low,
                fetched,
                offer.currency,
                int(offer.price_verified),
                verified,
                fetched,
                slot_id,
            ]
            if expected_generation is not None:
                where += " AND generation=?"
                params.append(expected_generation)
            if expected_revision is not None:
                where += " AND revision=?"
                params.append(expected_revision)
            cur = conn.execute(
                f"""UPDATE watch_slots
                SET last_observed_price=?, lowest_observed_price=?, last_checked_at=?, currency=?,
                    last_verified_price=CASE WHEN ? THEN ? ELSE last_verified_price END,
                    updated_at=? WHERE {where}""",
                params,
            )
            if cur.rowcount == 0:
                raise StaleSlotError(f"slot #{slot_id} changed before offer commit")

    def set_alert_state(self, slot_id: int, state: str, *, alerted_price: int | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            if state in {ALERTED, "SENDING"}:
                cur = conn.execute(
                    """UPDATE watch_slots
                    SET alert_state=?, last_alerted_price=?, last_alerted_at=?, revision=revision+1, updated_at=?
                    WHERE id=?""",
                    (state, alerted_price, now, now, slot_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE watch_slots SET alert_state=?, revision=revision+1, updated_at=? WHERE id=?",
                    (state, now, slot_id),
                )
            if cur.rowcount == 0:
                raise StaleSlotError(f"slot #{slot_id} no longer exists")

    def begin_alert(self, slot: WatchSlot, offer: FlightOffer) -> int:
        dedupe_key = f"{slot.generation}:{slot.id}:{slot.target_price}:{uuid4().hex}"
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO alert_history
                (slot_id, platform, recipient_id, total_price, currency, delivery_state,
                 dedupe_key, sent_at)
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
                (
                    slot.id,
                    slot.owner_platform,
                    slot.owner_id,
                    offer.total_price,
                    offer.currency,
                    dedupe_key,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cur.lastrowid)

    def finish_alert(self, alert_id: int, *, state: str, error: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE alert_history SET delivery_state=?, error=? WHERE id=?",
                (state, error, alert_id),
            )
