from __future__ import annotations

import json
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
            {"departureLocationCode": "CJJ", "departureLocationType": "airport", "arrivalLocationCode": "TPE", "arrivalLocationType": "airport", "departureDate": "20260918"},
            {"departureLocationCode": "TPE", "departureLocationType": "airport", "arrivalLocationCode": "CJJ", "arrivalLocationType": "airport", "departureDate": "20260920"},
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


def fares_from(data: dict) -> list[int]:
    fares: list[int] = []
    for mapping in data.get("fareMappings") or []:
        for fare in mapping.get("fares") or []:
            total = (fare.get("adult") or {}).get("totalFare")
            if isinstance(total, (int, float)):
                fares.append(int(total))
    return fares


def main() -> int:
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(build_payload(), separators=(",", ":")).encode("utf-8"),
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

    valid: list[dict] = []
    event_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        event_count += 1
        try:
            data = json.loads(line[5:].strip())
        except (json.JSONDecodeError, TypeError):
            continue
        itineraries = data.get("itineraries") or []
        mappings = data.get("fareMappings") or []
        fares = fares_from(data)
        status = data.get("status") or {}
        if itineraries and mappings:
            valid.append(data)
            print(
                "event_valid="
                f"{event_count} itineraries={len(itineraries)} mappings={len(mappings)} "
                f"fares={len(fares)} lowest={min(fares) if fares else 'none'} "
                f"completed={status.get('isCompleted')} "
                f"status_lowest_direct={(status.get('lowestFare') or {}).get('direct')}"
            )

    print(f"sse_event_count={event_count}")
    if not valid:
        print("valid_payload=False")
        return 3

    last = valid[-1]
    all_seen_fares = [fare for data in valid for fare in fares_from(data)]
    final_fares = fares_from(last)
    print("valid_payload=True")
    print(f"valid_event_count={len(valid)}")
    print(f"last_itinerary_count={len(last.get('itineraries') or [])}")
    print(f"last_fare_mapping_count={len(last.get('fareMappings') or [])}")
    print(f"last_lowest_total_fare={min(final_fares) if final_fares else 'none'}")
    print(f"all_events_lowest_total_fare={min(all_seen_fares) if all_seen_fares else 'none'}")
    return 0 if final_fares else 4


if __name__ == "__main__":
    raise SystemExit(main())
