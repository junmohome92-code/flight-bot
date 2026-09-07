from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .locations import location_type
from .naver_api import (
    NAVER_FLIGHT_API,
    NaverAPIError,
    parse_sse_events,
    request_sse,
    rows_from_payload,
    select_best_payload,
)


_VALID_TYPES = {"airport", "city"}


def _type(value: str | None, code: str) -> str:
    resolved = (value or location_type(code)).strip().lower()
    if resolved not in _VALID_TYPES:
        raise ValueError(f"unsupported Naver location type: {resolved}")
    return resolved


def build_result_url(
    origin: str,
    destination: str,
    depart: str,
    return_date: str,
    *,
    origin_type: str | None = None,
    destination_type: str | None = None,
) -> str:
    origin = origin.strip().upper()
    destination = destination.strip().upper()
    origin_type = _type(origin_type, origin)
    destination_type = _type(destination_type, destination)
    path = (
        "https://flight.naver.com/flights/international/"
        f"{origin}:{origin_type}-{destination}:{destination_type}-{depart.replace('-', '')}/"
        f"{destination}:{destination_type}-{origin}:{origin_type}-{return_date.replace('-', '')}"
    )
    query = urlencode({"adult": 1, "fareType": "Y", "isDirect": "true"})
    return f"{path}?{query}"


def build_payload(
    origin: str,
    destination: str,
    depart: str,
    return_date: str,
    *,
    origin_type: str | None = None,
    destination_type: str | None = None,
) -> dict[str, Any]:
    origin = origin.strip().upper()
    destination = destination.strip().upper()
    origin_type = _type(origin_type, origin)
    destination_type = _type(destination_type, destination)

    # When the origin is a single airport, retain the previously validated
    # same-airport return filters. A metropolitan city search intentionally
    # leaves those airport filters empty so Naver may choose any member airport.
    departure_airports = [[origin], []] if origin_type == "airport" else [[], []]
    arrival_airports = [[], [origin]] if origin_type == "airport" else [[], []]

    return {
        "adultCount": 1,
        "childCount": 0,
        "infantCount": 0,
        "device": "pc",
        "isNonstop": True,
        "seatClass": "Y",
        "tripType": "RT",
        "itineraries": [
            {
                "departureLocationCode": origin,
                "departureLocationType": origin_type,
                "arrivalLocationCode": destination,
                "arrivalLocationType": destination_type,
                "departureDate": depart.replace("-", ""),
            },
            {
                "departureLocationCode": destination,
                "departureLocationType": destination_type,
                "arrivalLocationCode": origin,
                "arrivalLocationType": origin_type,
                "departureDate": return_date.replace("-", ""),
            },
        ],
        "openReturnDays": 0,
        "flightFilter": {
            "filter": {
                "airlines": [],
                "departureAirports": departure_airports,
                "arrivalAirports": arrival_airports,
                "departureTime": [],
                "fareTypes": [],
                "flightDurationSeconds": [],
                "hasCardBenefit": True,
                "isIndividual": False,
                "isLowCarbonEmission": False,
                "isSameAirlines": False,
                "isSameDepArrAirport": origin_type == "airport" and destination_type == "airport",
                "isTravelClub": False,
                "minFare": {},
                "viaCount": [],
                "selectedItineraries": [],
            },
            "limit": 200,
            "skip": 0,
            "sort": {"adultMinFare": 1},
        },
        "initialRequest": False,
    }


def query_round_trip(
    origin: str,
    destination: str,
    depart: str,
    return_date: str,
    *,
    origin_type: str | None = None,
    destination_type: str | None = None,
    timeout_seconds: int = 30,
    attempts: int = 3,
    limit: int = 20,
    endpoint: str = NAVER_FLIGHT_API,
) -> tuple[list[dict[str, Any]], dict[str, Any], str, dict[str, Any]]:
    origin_type = _type(origin_type, origin)
    destination_type = _type(destination_type, destination)
    payload = build_payload(
        origin,
        destination,
        depart,
        return_date,
        origin_type=origin_type,
        destination_type=destination_type,
    )
    raw_sse, meta = request_sse(
        payload,
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        endpoint=endpoint,
    )
    events = parse_sse_events(raw_sse)
    selected = select_best_payload(events)
    if selected is None:
        raise NaverAPIError(f"Naver SSE returned no usable round-trip payload (events={len(events)})")
    rows = rows_from_payload(selected, limit=limit)
    if not rows:
        raise NaverAPIError("Naver SSE returned data but no direct round-trip fare rows could be built")
    status = selected.get("status") or {}
    diagnostics = {
        **meta,
        "sse_event_count": len(events),
        "selected_completed": status.get("isCompleted"),
        "itinerary_count": len(selected.get("itineraries") or []),
        "fare_mapping_count": len(selected.get("fareMappings") or []),
        "advertised_lowest_direct": (status.get("lowestFare") or {}).get("direct"),
        "row_count": len(rows),
        "origin_type": origin_type,
        "destination_type": destination_type,
    }
    return rows, diagnostics, raw_sse, selected
