from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


ALERT_ARMED = "ARMED"
ALERT_SENDING = "SENDING"
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
    generation: str = ""
    revision: int = 1


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
    # Product-facing link. For the current scope this is the Google Flights
    # round-trip result page and is the only URL exposed in alerts.
    result_url: str | None = None
    separate_ticket: bool | None = None
    nonstop: bool | None = None
    # Ranked Google Flights rows prepared for notification. This is transient
    # presentation data; the lowest row remains the persisted primary offer.
    display_offers: list[dict[str, Any]] | None = None
    raw: dict[str, Any] | None = None
    fetched_at: datetime | None = None
    observed_price_value: int | None = None
    booking_option_price: int | None = None
    verified_checkout_price: int | None = None
    verification_status: str = "unverified"

    @property
    def observed_price(self) -> int:
        """Price actually observed in the provider flight row."""
        if self.observed_price_value is not None:
            return int(self.observed_price_value)
        raw_value = (self.raw or {}).get("observed_price")
        try:
            return int(raw_value) if raw_value is not None else int(self.total_price)
        except (TypeError, ValueError):
            return int(self.total_price)

    @property
    def verified_price(self) -> int | None:
        """External seller checkout final total, if verification completed."""
        if not self.price_verified:
            return None
        if self.verified_checkout_price is not None:
            return int(self.verified_checkout_price)
        return int(self.total_price)

    @property
    def google_flights_url(self) -> str | None:
        """Google Flights result-page URL used in user-facing messages."""
        return self.result_url or self.booking_url
