from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .config import Settings
from .models import FlightOffer, WatchSlot


class ProviderError(RuntimeError):
    pass


class SerpApiProvider:
    """Google Flights via SerpApi.

    Rule: a displayed search price alone is not treated as verified. We follow
    departure_token -> booking_token and prefer Booking Options prices.
    """

    name = "serpapi"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.serpapi_api_key:
            raise ProviderError("SERPAPI_API_KEY가 설정되지 않았습니다.")
        params = {**params, "api_key": self.settings.serpapi_api_key, "engine": "google_flights"}
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(self.settings.serpapi_base_url, params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("error"):
            raise ProviderError(str(payload["error"]))
        return payload

    @staticmethod
    def _base_params(slot: WatchSlot) -> dict[str, Any]:
        params: dict[str, Any] = {
            "departure_id": slot.origin,
            "arrival_id": slot.destination,
            "outbound_date": slot.depart_date,
            "return_date": slot.return_date,
            "currency": "KRW",
            "hl": "ko",
            "gl": "kr",
            "type": "1",  # round trip
        }
        if slot.nonstop:
            params["stops"] = "0"
        return params

    @staticmethod
    def _flight_label(flights: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        if not flights:
            return None, None
        airlines = sorted({str(f.get("airline", "")).strip() for f in flights if f.get("airline")})
        nums = [str(f.get("flight_number", "")).strip() for f in flights if f.get("flight_number")]
        return (" / ".join(airlines) or None, " / ".join(nums) or None)

    @staticmethod
    def _extract_booking_options(payload: dict[str, Any]) -> list[dict[str, Any]]:
        options = payload.get("booking_options") or []
        return options if isinstance(options, list) else []

    async def search(self, slot: WatchSlot) -> FlightOffer:
        first = await self._get(self._base_params(slot))
        candidates = (first.get("best_flights") or []) + (first.get("other_flights") or [])
        candidates = [c for c in candidates if c.get("departure_token")]
        if not candidates:
            raise ProviderError("출국편 departure_token을 가진 결과가 없습니다.")

        verified: list[FlightOffer] = []
        # API quota 보호를 위해 표시 가격이 낮은 후보부터 최대 5개만 상세 검증합니다.
        candidates.sort(key=lambda x: x.get("price") if isinstance(x.get("price"), (int, float)) else 10**15)

        for outbound in candidates[:5]:
            second_params = self._base_params(slot)
            second_params["departure_token"] = outbound["departure_token"]
            second = await self._get(second_params)
            returns = (second.get("best_flights") or []) + (second.get("other_flights") or [])
            for inbound in returns[:5]:
                booking_token = inbound.get("booking_token")
                if not booking_token:
                    continue
                booking = await self._get({"booking_token": booking_token, "currency": "KRW", "hl": "ko", "gl": "kr"})
                for option in self._extract_booking_options(booking):
                    together = option.get("together") or {}
                    price = together.get("price")
                    if not isinstance(price, (int, float)) or price <= 0:
                        continue
                    flights = (outbound.get("flights") or []) + (inbound.get("flights") or [])
                    airline, flight_numbers = self._flight_label(flights)
                    seller = together.get("book_with") or option.get("book_with")
                    verified.append(
                        FlightOffer(
                            provider=self.name,
                            origin=slot.origin,
                            destination=slot.destination,
                            depart_date=slot.depart_date,
                            return_date=slot.return_date,
                            total_price=int(price),
                            currency="KRW",
                            price_verified=True,
                            airline=airline,
                            outbound_flight=flight_numbers,
                            inbound_flight=None,
                            carry_on="Booking Options 응답에서 확인 필요",
                            checked_baggage="정보 확인 필요",
                            booking_provider=str(seller) if seller else None,
                            booking_url=together.get("booking_request", {}).get("url") if isinstance(together.get("booking_request"), dict) else None,
                            raw=None,
                            fetched_at=datetime.now(timezone.utc),
                        )
                    )

        if not verified:
            raise ProviderError("Booking Options에서 검증 가능한 판매 가격을 찾지 못했습니다.")
        return min(verified, key=lambda x: x.total_price)
