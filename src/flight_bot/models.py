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
