from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


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
    last_verified_price: int | None
    currency: str = "KRW"


@dataclass(slots=True)
class FlightOffer:
    provider: str
    origin: str
    destination: str
    depart_date: str
    return_date: str
    total_price: int
    currency: str
    price_verified: bool
    airline: str | None = None
    outbound_flight: str | None = None
    inbound_flight: str | None = None
    carry_on: str | None = None
    checked_baggage: str | None = None
    booking_provider: str | None = None
    booking_url: str | None = None
    raw: dict[str, Any] | None = None
    fetched_at: datetime | None = None
