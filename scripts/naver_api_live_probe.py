from __future__ import annotations

import json
import sys
import urllib.request


ENDPOINT = "https://flight-api.naver.com/flight/international/searchFlights"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)


def build_payload() -> dict:
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
                "departureLocationCode": "CJJ",
                "departureLocationType": "airport",
                "arrivalLocationCode": "TPE",
                "arrivalLocationType": "airport",
                "departureDate": "20260918",
            },
            {
                "departureLocationCode": "TPE",
                "departureLocationType": "airport",
                "arrivalLocationCode": "CJJ",
                "arrivalLocationType": "airport",
                "departureDate": "20260920",
            },
        ],
        "openReturnDays": 0,
        "flightFilter": {
            "filter": {
                "airlines": [],
                "departureAirports": [["CJJ"], []],
                "arrivalAirports": [[], ["CJJ"]],
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


def main() -> int:
    body = json.dumps(build_payload(), separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": USER_AGENT,
            "Referer": "https://flight.naver.com/",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8", errors="replace")
            print(f"http_status={response.status}")
            print(f"content_type={response.headers.get('Content-Type', '')}")
    except Exception as exc:
        print(f"probe_error={type(exc).__name__}: {exc}")
        return 2

    best = None
    events = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        events += 1
        raw_json = line[5:].strip()
        if not raw_json:
            continue
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        itineraries = data.get("itineraries") or []
        fare_mappings = data.get("fareMappings") or []
        if itineraries and fare_mappings:
            if best is None or (
                len(itineraries), len(fare_mappings)
            ) > (
                len(best.get("itineraries") or []),
                len(best.get("fareMappings") or []),
            ):
                best = data

    print(f"sse_event_count={events}")
    if not best:
        print("valid_payload=False")
        return 3

    itineraries = best.get("itineraries") or []
    fare_mappings = best.get("fareMappings") or []
    fares = []
    for mapping in fare_mappings:
        for fare in mapping.get("fares") or []:
            adult = fare.get("adult") or {}
            total = adult.get("totalFare")
            if isinstance(total, (int, float)):
                fares.append(int(total))

    print("valid_payload=True")
    print(f"itinerary_count={len(itineraries)}")
    print(f"fare_mapping_count={len(fare_mappings)}")
    print(f"fare_count={len(fares)}")
    if fares:
        print(f"lowest_total_fare={min(fares)}")
        return 0
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
