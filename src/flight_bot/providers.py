from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from .config import Settings
from .locations import location_type
from .models import FlightOffer, WatchSlot
from .naver_api import NaverAPIError
from .naver_search import build_result_url, query_round_trip


class ProviderError(RuntimeError):
    pass


class NaverFlightsSSEProvider:
    """Production direct round-trip provider backed by Naver Flights SSE.

    Supports both airport codes and metropolitan city codes. New slots persist
    the selected location type explicitly; legacy/ad-hoc callers can still fall
    back to deterministic code inference. The provider never launches a browser
    or parses DOM/CSS.
    """

    name = "naver-flights-sse"
    accepted_for_alerts = True

    def __init__(self, settings: Settings):
        self.settings = settings
        self._request_lock = asyncio.Lock()
        self._last_request_started = 0.0

    async def close(self) -> None:
        return None

    async def _respect_request_interval(self) -> None:
        interval = max(0.0, float(self.settings.naver_min_request_interval_seconds))
        elapsed = time.monotonic() - self._last_request_started
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)
        self._last_request_started = time.monotonic()

    @staticmethod
    def _slot_location_type(value: str, stored_type: str) -> str:
        return stored_type if stored_type in {"airport", "city"} else location_type(value)

    async def search(self, slot: WatchSlot, *, verify_below_price: int | None = None) -> FlightOffer:
        del verify_below_price  # Checkout verification is outside the current product scope.
        if not slot.return_date:
            raise ProviderError("Naver provider requires a round-trip return date")

        origin_type = self._slot_location_type(slot.origin, slot.origin_type)
        destination_type = self._slot_location_type(slot.destination, slot.destination_type)
        try:
            async with self._request_lock:
                await self._respect_request_interval()
                rows, diagnostics, _raw_sse, _selected = await asyncio.to_thread(
                    query_round_trip,
                    slot.origin,
                    slot.destination,
                    slot.depart_date,
                    slot.return_date,
                    origin_type=origin_type,
                    destination_type=destination_type,
                    timeout_seconds=self.settings.naver_api_timeout_seconds,
                    attempts=self.settings.naver_api_attempts,
                    limit=max(20, self.settings.alert_max_offers),
                    endpoint=self.settings.naver_api_url,
                )
        except NaverAPIError as exc:
            raise ProviderError(str(exc)) from exc
        except Exception as exc:
            raise ProviderError(f"Naver Flights SSE search failed: {exc}") from exc

        display = rows[: self.settings.alert_max_offers]
        if not display:
            raise ProviderError("Naver Flights returned no direct round-trip offers")

        best = display[0]
        outbound_airline = str(best.get("outbound_airline") or best.get("outbound_airline_code") or "").strip()
        return_airline = str(best.get("return_airline") or best.get("return_airline_code") or "").strip()
        airline = outbound_airline if outbound_airline == return_airline else " + ".join(
            value for value in (outbound_airline, return_airline) if value
        )
        price = int(best["price"])
        result_url = build_result_url(
            slot.origin,
            slot.destination,
            slot.depart_date,
            slot.return_date,
            origin_type=origin_type,
            destination_type=destination_type,
        )

        return FlightOffer(
            provider=self.name,
            origin=slot.origin,
            destination=slot.destination,
            depart_date=slot.depart_date,
            return_date=slot.return_date,
            total_price=price,
            observed_price_value=price,
            currency="KRW",
            price_verified=False,
            verified_checkout_price=None,
            verification_status="naver_sse_round_trip_fare",
            airline=airline or None,
            outbound_flight=str(best.get("outbound_flight") or "") or None,
            inbound_flight=str(best.get("return_flight") or "") or None,
            carry_on="정보 확인 불가",
            checked_baggage="정보 확인 불가",
            booking_provider=None,
            booking_url=None,
            result_url=result_url,
            display_offers=display,
            separate_ticket=None,
            nonstop=True,
            raw={
                "source": "NAVER_SSE_API",
                "observed_price": price,
                "round_trip": True,
                "direct_only": True,
                "origin_type": origin_type,
                "destination_type": destination_type,
                "display_offer_count": len(display),
                "advertised_lowest_direct": diagnostics.get("advertised_lowest_direct"),
                "sse_event_count": diagnostics.get("sse_event_count"),
                "itinerary_count": diagnostics.get("itinerary_count"),
                "fare_mapping_count": diagnostics.get("fare_mapping_count"),
                "http_status": diagnostics.get("http_status"),
                "content_type": diagnostics.get("content_type"),
                "accepted_for_alerts": self.accepted_for_alerts,
            },
            fetched_at=datetime.now(timezone.utc),
        )
