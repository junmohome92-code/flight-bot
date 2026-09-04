from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


ALERT_ARMED = "ARMED"
ALERTED = "ALERTED"


@dataclass(slots=True)
class WatchSlot:
    id: int
    owner_platform: str
    owner_id: str
    origin: str
    destination: str
    depart_date: str
    return_date: str
    nonstop: bool
    checked_bag: int
    enabled: bool
    target_price: int
    alert_state: str = ALERT_ARMED
    last_observed_price: int | None = None
    lowest_observed_price: int | None = None
    last_verified_price: int | None = None
    last_checked_at: str | None = None
    last_alerted_price: int | None = None
    last_alerted_at: str | None = None
    currency: str = "KRW"


@dataclass(slots=True)
class FlightOffer:
    provider: str
    origin: str
    destination: str
    depart_date: str
    return_date: str
    total_price: int
    currency: str = "KRW"
    price_verified: bool = False
    airline: str | None = None
    outbound_flight: str | None = None
    inbound_flight: str | None = None
    carry_on: str | None = None
    checked_baggage: str | None = None
    booking_provider: str | None = None
    booking_url: str | None = None
    separate_ticket: bool | None = None
    nonstop: bool | None = None
    raw: dict[str, Any] | None = None
    fetched_at: datetime | None = None

    @property
    def observed_price(self) -> int:
        """Price actually observed in the provider UI/result row.

        A verified checkout may legitimately differ from the earlier observed
        row. Providers should preserve the row value in raw['observed_price'].
        """
        raw_value = (self.raw or {}).get("observed_price")
        try:
            return int(raw_value) if raw_value is not None else int(self.total_price)
        except (TypeError, ValueError):
            return int(self.total_price)

    @property
    def verified_price(self) -> int | None:
        """Final verified price, or None when verification has not crossed the contract boundary."""
        return int(self.total_price) if self.price_verified else None
