from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode


NAVER_FLIGHT_API = "https://flight-api.naver.com/flight/international/searchFlights"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


class NaverAPIError(RuntimeError):
    pass


def build_result_url(origin: str, destination: str, depart: str, return_date: str) -> str:
    origin = origin.strip().upper()
    destination = destination.strip().upper()
    path = (
        "https://flight.naver.com/flights/international/"
        f"{origin}:airport-{destination}:airport-{depart.replace('-', '')}/"
        f"{destination}:airport-{origin}:airport-{return_date.replace('-', '')}"
    )
    query = urlencode({"adult": 1, "fareType": "Y", "isDirect": "true"})
    return f"{path}?{query}"


def build_payload(origin: str, destination: str, depart: str, return_date: str) -> dict[str, Any]:
    origin = origin.strip().upper()
    destination = destination.strip().upper()
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
                "departureLocationType": "airport",
                "arrivalLocationCode": destination,
                "arrivalLocationType": "airport",
                "departureDate": depart.replace("-", ""),
            },
            {
                "departureLocationCode": destination,
                "departureLocationType": "airport",
                "arrivalLocationCode": origin,
                "arrivalLocationType": "airport",
                "departureDate": return_date.replace("-", ""),
            },
        ],
        "openReturnDays": 0,
        "flightFilter": {
            "filter": {
                "airlines": [],
                "departureAirports": [[origin], []],
                "arrivalAirports": [[], [origin]],
                "departureTime": [],
                "fareTypes": [],
                "flightDurationSeconds": [],
                "hasCardBenefit": True,
                "isIndividual": False,
                "isLowCarbonEmission": False,
                "isSameAirlines": False,
                "isSameDepArrAirport": True,
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


def _headers(user_agent: str = DEFAULT_USER_AGENT) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": user_agent,
        "Referer": "https://flight.naver.com/",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def request_sse(
    payload: dict[str, Any],
    *,
    timeout_seconds: int = 30,
    attempts: int = 3,
    endpoint: str = NAVER_FLIGHT_API,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[str, dict[str, Any]]:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    last_error: Exception | None = None
    attempts = max(1, int(attempts))

    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            endpoint,
            data=encoded,
            method="POST",
            headers=_headers(user_agent),
        )
        try:
            with urllib.request.urlopen(request, timeout=max(5, int(timeout_seconds))) as response:
                body = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" not in content_type.lower():
                    raise NaverAPIError(f"unexpected Naver content type: {content_type or 'missing'}")
                return body, {
                    "http_status": int(response.status),
                    "content_type": content_type,
                    "attempt": attempt,
                    "endpoint": endpoint,
                }
        except urllib.error.HTTPError as exc:
            last_error = exc
            if (exc.code == 429 or 500 <= exc.code < 600) and attempt < attempts:
                time.sleep(attempt * 3)
                continue
            raise NaverAPIError(f"Naver Flights API HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, NaverAPIError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
                continue
            break

    raise NaverAPIError(f"Naver Flights API request failed after {attempts} attempt(s): {last_error}")


def parse_sse_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        raw_json = line[5:].strip()
        if not raw_json:
            continue
        try:
            value = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def select_best_payload(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [event for event in events if event.get("itineraries") and event.get("fareMappings")]
    if not valid:
        return None

    def score(event: dict[str, Any]) -> tuple[int, int, int]:
        completed = int((event.get("status") or {}).get("isCompleted") is True)
        return completed, len(event.get("fareMappings") or []), len(event.get("itineraries") or [])

    return max(valid, key=score)


def _format_time(value: object) -> str:
    text = str(value or "").strip()
    if len(text) == 4 and text.isdigit():
        return f"{text[:2]}:{text[2:]}"
    return text


def _airline_name(status: dict[str, Any], code: str) -> str:
    value = (status.get("airlinesCodeMap") or {}).get(code)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("airlineName", "name", "nameKo", "koreanName"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return code


def _segment_summary(itinerary: dict[str, Any] | None, status: dict[str, Any]) -> dict[str, Any] | None:
    if not itinerary:
        return None
    segments = itinerary.get("segments") or []
    # The production product is direct-only. Reject any unexpected connection.
    if len(segments) != 1:
        return None
    segment = segments[0]
    marketing = segment.get("marketingCarrier") or {}
    departure = segment.get("departure") or {}
    arrival = segment.get("arrival") or {}
    airline_code = str(marketing.get("airlineCode") or "").strip()
    flight_number = str(marketing.get("flightNumber") or "").strip()
    return {
        "flight": f"{airline_code}{flight_number}",
        "airline_code": airline_code,
        "airline": _airline_name(status, airline_code),
        "departure": _format_time(departure.get("time")),
        "arrival": _format_time(arrival.get("time")),
        "departure_airport": str(departure.get("airportCode") or ""),
        "arrival_airport": str(arrival.get("airportCode") or ""),
        "departure_date": str(departure.get("date") or ""),
        "arrival_date": str(arrival.get("date") or ""),
        "duration_seconds": int(itinerary.get("duration") or 0),
    }


def _resolve_itinerary_pair(mapping_id: str, itinerary_ids: list[str]) -> tuple[str, str] | None:
    # Prefer exact known IDs; this also works if an itinerary ID itself contains '-'.
    for outbound in sorted(itinerary_ids, key=len, reverse=True):
        prefix = outbound + "-"
        if mapping_id.startswith(prefix):
            returning = mapping_id[len(prefix) :]
            if returning in itinerary_ids:
                return outbound, returning
    parts = mapping_id.split("-", 1)
    if len(parts) == 2 and parts[0] in itinerary_ids and parts[1] in itinerary_ids:
        return parts[0], parts[1]
    return None


def rows_from_payload(payload: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    status = payload.get("status") or {}
    itinerary_map = {
        str(item.get("itineraryId")): item
        for item in (payload.get("itineraries") or [])
        if item.get("itineraryId")
    }
    itinerary_ids = list(itinerary_map)
    candidates: list[dict[str, Any]] = []

    for mapping in payload.get("fareMappings") or []:
        pair = _resolve_itinerary_pair(str(mapping.get("itineraryIds") or ""), itinerary_ids)
        if not pair:
            continue
        outbound = _segment_summary(itinerary_map.get(pair[0]), status)
        returning = _segment_summary(itinerary_map.get(pair[1]), status)
        if not outbound or not returning:
            continue

        for fare in mapping.get("fares") or []:
            total = (fare.get("adult") or {}).get("totalFare")
            if not isinstance(total, (int, float)) or total <= 0:
                continue
            candidates.append(
                {
                    "price": int(total),
                    "times": [
                        outbound["departure"],
                        outbound["arrival"],
                        returning["departure"],
                        returning["arrival"],
                    ],
                    "outbound_flight": outbound["flight"],
                    "return_flight": returning["flight"],
                    "outbound_airline_code": outbound["airline_code"],
                    "return_airline_code": returning["airline_code"],
                    "outbound_airline": outbound["airline"],
                    "return_airline": returning["airline"],
                    "outbound_departure_airport": outbound["departure_airport"],
                    "outbound_arrival_airport": outbound["arrival_airport"],
                    "return_departure_airport": returning["departure_airport"],
                    "return_arrival_airport": returning["arrival_airport"],
                    "outbound_departure_date": outbound["departure_date"],
                    "return_departure_date": returning["departure_date"],
                    "partner_code": str(fare.get("partnerCode") or ""),
                    "fare_type": str(fare.get("fareType") or ""),
                    "is_confirmed": bool(fare.get("isConfirmed")),
                    "itinerary_ids": [pair[0], pair[1]],
                    "nonstop": True,
                }
            )

    # One row per actual flight pair. If several sellers/fare types exist, keep
    # the cheapest confirmed option for that same itinerary combination.
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in candidates:
        key = (
            row["outbound_flight"],
            row["return_flight"],
            tuple(row["times"]),
        )
        old = best.get(key)
        if old is None:
            best[key] = row
            continue
        old_key = (int(old["price"]), 0 if old.get("is_confirmed") else 1)
        new_key = (int(row["price"]), 0 if row.get("is_confirmed") else 1)
        if new_key < old_key:
            best[key] = row

    rows = list(best.values())
    rows.sort(
        key=lambda row: (
            int(row["price"]),
            str(row["outbound_flight"]),
            str(row["return_flight"]),
        )
    )
    return rows[: max(1, int(limit))]


def query_round_trip(
    origin: str,
    destination: str,
    depart: str,
    return_date: str,
    *,
    timeout_seconds: int = 30,
    attempts: int = 3,
    limit: int = 20,
    endpoint: str = NAVER_FLIGHT_API,
) -> tuple[list[dict[str, Any]], dict[str, Any], str, dict[str, Any]]:
    payload = build_payload(origin, destination, depart, return_date)
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
    }
    return rows, diagnostics, raw_sse, selected
