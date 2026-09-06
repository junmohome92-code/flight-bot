from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


API_URL = "https://flight-api.naver.com/flight/international/searchFlights"


def _compact(date_text: str) -> str:
    return date_text.replace("-", "")


def build_payload(origin: str, destination: str, depart: str, return_date: str) -> dict[str, Any]:
    origin = origin.upper()
    destination = destination.upper()
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
                "departureDate": _compact(depart),
            },
            {
                "departureLocationCode": destination,
                "departureLocationType": "airport",
                "arrivalLocationCode": origin,
                "arrivalLocationType": "airport",
                "departureDate": _compact(return_date),
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


def request_sse(payload: dict[str, Any], timeout: int) -> tuple[int, str, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
        ),
        "Referer": "https://flight.naver.com/",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    request = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read().decode("utf-8", errors="replace")


def parse_last_valid_sse(raw: str) -> tuple[dict[str, Any] | None, int]:
    last_valid: dict[str, Any] | None = None
    events = 0
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        text = line[5:].strip()
        if not text:
            continue
        events += 1
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        itineraries = data.get("itineraries") or []
        mappings = data.get("fareMappings") or []
        if itineraries and mappings:
            last_valid = data
    return last_valid, events


def lowest_fare(data: dict[str, Any]) -> int | None:
    values: list[int] = []
    for mapping in data.get("fareMappings") or []:
        for fare in mapping.get("fares") or []:
            adult = fare.get("adult") or {}
            value = adult.get("totalFare")
            if isinstance(value, (int, float)) and value > 0:
                values.append(int(value))
    return min(values) if values else None


def run(args: argparse.Namespace) -> int:
    payload = build_payload(args.origin, args.destination, args.depart, args.return_date)
    print("==================================================")
    print(" NAVER FLIGHTS DIRECT SSE API PROBE")
    print("==================================================")
    print(f"route={args.origin.upper()}->{args.destination.upper()}->{args.origin.upper()}")
    print(f"dates={args.depart}~{args.return_date}")
    print(f"endpoint={API_URL}")
    print("browser_used=False")
    print("direct_only=True")
    print("")

    try:
        status, content_type, raw = request_sse(payload, args.timeout)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        print("API_PROBE_STATUS=FAIL")
        print(f"http_status={exc.code}")
        print(f"response_preview={text[:500]!r}")
        return 2
    except Exception as exc:
        print("API_PROBE_STATUS=FAIL")
        print(f"error={type(exc).__name__}: {exc}")
        return 2

    data, event_count = parse_last_valid_sse(raw)
    print(f"http_status={status}")
    print(f"content_type={content_type}")
    print(f"sse_event_count={event_count}")

    if not data:
        print("API_PROBE_STATUS=FAIL")
        print("reason=no SSE event contained both itineraries and fareMappings")
        print(f"response_preview={raw[:1000]!r}")
        return 2

    itineraries = data.get("itineraries") or []
    mappings = data.get("fareMappings") or []
    fare = lowest_fare(data)
    print("API_PROBE_STATUS=PASS")
    print(f"itinerary_count={len(itineraries)}")
    print(f"fare_mapping_count={len(mappings)}")
    print(f"lowest_fare={fare if fare is not None else 'unavailable'}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Naver Flights direct SSE endpoint")
    parser.add_argument("--origin", default="CJJ")
    parser.add_argument("--destination", default="TPE")
    parser.add_argument("--depart", default="2026-09-18")
    parser.add_argument("--return-date", default="2026-09-20")
    parser.add_argument("--timeout", type=int, default=20)
    return parser.parse_args()


if __name__ == "__main__":
    if not sys.platform.startswith("win"):
        raise SystemExit("This probe is intended for the current Windows test harness")
    raise SystemExit(run(parse_args()))
