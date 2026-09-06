from __future__ import annotations

import argparse
import asyncio
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode


DEFAULT_ORIGIN = "CJJ"
DEFAULT_DESTINATION = "TPE"
DEFAULT_DEPART = "2026-09-18"
DEFAULT_RETURN = "2026-09-20"
NAVER_FLIGHT_API = "https://flight-api.naver.com/flight/international/searchFlights"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)


@dataclass
class NaverProbeResult:
    url: str
    rows: list[dict]
    body: str
    diagnostics: dict
    artifact_dir: Path


def build_naver_url(origin: str, destination: str, depart: str, return_date: str) -> str:
    origin = origin.strip().upper()
    destination = destination.strip().upper()
    depart_compact = depart.replace("-", "")
    return_compact = return_date.replace("-", "")
    path = (
        "https://flight.naver.com/flights/international/"
        f"{origin}:airport-{destination}:airport-{depart_compact}/"
        f"{destination}:airport-{origin}:airport-{return_compact}"
    )
    query = urlencode({"adult": 1, "fareType": "Y", "isDirect": "true"})
    return f"{path}?{query}"


def build_naver_api_payload(
    origin: str,
    destination: str,
    depart: str,
    return_date: str,
) -> dict:
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


def _api_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": USER_AGENT,
        "Referer": "https://flight.naver.com/",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def _request_sse(payload: dict, timeout_seconds: int, attempts: int = 3) -> tuple[str, dict]:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            NAVER_FLIGHT_API,
            data=encoded,
            method="POST",
            headers=_api_headers(),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
                meta = {
                    "http_status": int(response.status),
                    "content_type": response.headers.get("Content-Type", ""),
                    "attempt": attempt,
                }
                return body, meta
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 or 500 <= exc.code < 600:
                if attempt < attempts:
                    time.sleep(attempt * 3)
                    continue
            raise RuntimeError(f"Naver Flights API HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
                continue
            break

    raise RuntimeError(f"Naver Flights API request failed after {attempts} attempts: {last_error}")


def _parse_sse_events(text: str) -> list[dict]:
    events: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        raw_json = line[5:].strip()
        if not raw_json:
            continue
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            events.append(data)
    return events


def _select_api_payload(events: list[dict]) -> dict | None:
    valid = [
        event
        for event in events
        if event.get("itineraries") and event.get("fareMappings")
    ]
    if not valid:
        return None

    completed = [event for event in valid if (event.get("status") or {}).get("isCompleted") is True]
    if completed:
        return completed[-1]
    return valid[-1]


def _format_time(value: object) -> str:
    text = str(value or "").strip()
    if len(text) == 4 and text.isdigit():
        return f"{text[:2]}:{text[2:]}"
    return text


def _segment_summary(itinerary: dict | None) -> dict | None:
    if not itinerary:
        return None
    segments = itinerary.get("segments") or []
    if not segments:
        return None
    segment = segments[0]
    marketing = segment.get("marketingCarrier") or {}
    departure = segment.get("departure") or {}
    arrival = segment.get("arrival") or {}
    airline_code = str(marketing.get("airlineCode") or "")
    flight_number = str(marketing.get("flightNumber") or "")
    return {
        "flight": f"{airline_code}{flight_number}",
        "airline_code": airline_code,
        "departure": _format_time(departure.get("time")),
        "arrival": _format_time(arrival.get("time")),
        "departure_date": str(departure.get("date") or ""),
        "arrival_date": str(arrival.get("date") or ""),
        "duration_seconds": int(itinerary.get("duration") or 0),
    }


def _resolve_itinerary_pair(mapping_id: str, itinerary_ids: list[str]) -> tuple[str, str] | None:
    # Naver joins the outbound and return itinerary ids with a hyphen. Try exact
    # known-id pairs first so this remains safe even if an id itself contains '-'.
    for outbound in itinerary_ids:
        prefix = outbound + "-"
        if not mapping_id.startswith(prefix):
            continue
        remainder = mapping_id[len(prefix) :]
        if remainder in itinerary_ids:
            return outbound, remainder

    parts = mapping_id.split("-", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return None


def _rows_from_payload(payload: dict) -> list[dict]:
    itineraries = payload.get("itineraries") or []
    itinerary_map = {
        str(item.get("itineraryId")): item
        for item in itineraries
        if item.get("itineraryId")
    }
    itinerary_ids = list(itinerary_map)
    rows: list[dict] = []

    for mapping in payload.get("fareMappings") or []:
        mapping_id = str(mapping.get("itineraryIds") or "")
        pair = _resolve_itinerary_pair(mapping_id, itinerary_ids)
        if not pair:
            continue
        outbound = _segment_summary(itinerary_map.get(pair[0]))
        returning = _segment_summary(itinerary_map.get(pair[1]))
        if not outbound or not returning:
            continue

        for fare in mapping.get("fares") or []:
            adult = fare.get("adult") or {}
            total = adult.get("totalFare")
            if not isinstance(total, (int, float)) or total <= 0:
                continue
            price = int(total)
            times = [
                outbound["departure"],
                outbound["arrival"],
                returning["departure"],
                returning["arrival"],
            ]
            text = (
                f"{outbound['flight']} {times[0]}->{times[1]} / "
                f"{returning['flight']} {times[2]}->{times[3]} / "
                f"partner={fare.get('partnerCode') or ''} fareType={fare.get('fareType') or ''}"
            )
            rows.append(
                {
                    "price": price,
                    "times": times,
                    "score": 100,
                    "text": text,
                    "outbound_flight": outbound["flight"],
                    "return_flight": returning["flight"],
                    "outbound_airline_code": outbound["airline_code"],
                    "return_airline_code": returning["airline_code"],
                    "outbound_departure_date": outbound["departure_date"],
                    "return_departure_date": returning["departure_date"],
                    "partner_code": str(fare.get("partnerCode") or ""),
                    "fare_type": str(fare.get("fareType") or ""),
                    "is_confirmed": bool(fare.get("isConfirmed")),
                    "itinerary_ids": [pair[0], pair[1]],
                }
            )

    # Same flight pair/price may be sold by multiple partners. Keep one compact
    # row for the console/Telegram output while preserving the cheapest ordering.
    best: dict[tuple, dict] = {}
    for row in rows:
        key = (
            int(row["price"]),
            row["outbound_flight"],
            row["return_flight"],
            tuple(row["times"]),
        )
        old = best.get(key)
        if old is None or (not old.get("is_confirmed") and row.get("is_confirmed")):
            best[key] = row

    deduped = list(best.values())
    deduped.sort(key=lambda row: (int(row["price"]), row["outbound_flight"], row["return_flight"]))
    return deduped[:20]


def _diagnostics(events: list[dict], selected: dict | None, meta: dict) -> dict:
    valid = [event for event in events if event.get("itineraries") and event.get("fareMappings")]
    status = (selected or {}).get("status") or {}
    lowest = status.get("lowestFare") or {}
    return {
        **meta,
        "endpoint": NAVER_FLIGHT_API,
        "sse_event_count": len(events),
        "valid_event_count": len(valid),
        "selected_completed": status.get("isCompleted"),
        "selected_itinerary_count": len((selected or {}).get("itineraries") or []),
        "selected_fare_mapping_count": len((selected or {}).get("fareMappings") or []),
        "advertised_lowest_direct": lowest.get("direct"),
    }


def _save_artifacts(
    artifact_dir: Path,
    *,
    raw_sse: str,
    selected: dict,
    rows: list[dict],
    diagnostics: dict,
    result_url: str,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "response.sse.txt").write_text(raw_sse, encoding="utf-8")
    (artifact_dir / "response.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifact_dir / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifact_dir / "result.json").write_text(
        json.dumps(
            {
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "url": result_url,
                "rows": rows,
                "diagnostics": diagnostics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def collect_naver_api_results(
    *,
    origin: str = DEFAULT_ORIGIN,
    destination: str = DEFAULT_DESTINATION,
    depart: str = DEFAULT_DEPART,
    return_date: str = DEFAULT_RETURN,
    result_timeout: int = 70,
    artifact_dir: str | Path = "artifacts/naver-flight-poc",
) -> NaverProbeResult:
    url = build_naver_url(origin, destination, depart, return_date)
    payload = build_naver_api_payload(origin, destination, depart, return_date)
    artifact_path = Path(artifact_dir)
    timeout_seconds = max(5, min(int(result_timeout), 90))

    raw_sse, meta = await asyncio.to_thread(_request_sse, payload, timeout_seconds)
    events = _parse_sse_events(raw_sse)
    selected = _select_api_payload(events)
    diagnostics = _diagnostics(events, selected, meta)

    if selected is None:
        raise RuntimeError(
            "Naver Flights SSE returned no usable itineraries/fareMappings "
            f"(events={len(events)})."
        )

    rows = _rows_from_payload(selected)
    if not rows:
        raise RuntimeError(
            "Naver Flights SSE returned flight/fare data but no complete round-trip rows could be built."
        )

    _save_artifacts(
        artifact_path,
        raw_sse=raw_sse,
        selected=selected,
        rows=rows,
        diagnostics=diagnostics,
        result_url=url,
    )
    return NaverProbeResult(
        url=url,
        rows=rows,
        body=raw_sse,
        diagnostics=diagnostics,
        artifact_dir=artifact_path.resolve(),
    )


async def collect_naver_visible_results(
    *,
    origin: str = DEFAULT_ORIGIN,
    destination: str = DEFAULT_DESTINATION,
    depart: str = DEFAULT_DEPART,
    return_date: str = DEFAULT_RETURN,
    navigation_timeout: int = 60,
    result_timeout: int = 70,
    artifact_dir: str | Path = "artifacts/naver-flight-poc",
    headless: bool = False,
    keep_open: int = 0,
    failure_keep_open: int = 0,
) -> NaverProbeResult:
    # Compatibility wrapper for the existing Telegram E2E caller. The successful
    # Naver path is now the SSE API, so browser-only arguments are intentionally
    # accepted but no longer used.
    del navigation_timeout, headless, keep_open, failure_keep_open
    return await collect_naver_api_results(
        origin=origin,
        destination=destination,
        depart=depart,
        return_date=return_date,
        result_timeout=result_timeout,
        artifact_dir=artifact_dir,
    )


def _print_rows(result: NaverProbeResult, max_rows: int = 4) -> None:
    print("\n=== NAVER RESULT ===")
    print("POC_STATUS=PASS")
    print("source=NAVER_SSE_API")
    print(f"direct_candidate_count={len(result.rows)}")
    print(f"lowest_direct_price={int(result.rows[0]['price']):,} KRW")
    advertised = result.diagnostics.get("advertised_lowest_direct")
    if isinstance(advertised, (int, float)):
        print(f"naver_advertised_lowest_direct={int(advertised):,} KRW")
    for index, row in enumerate(result.rows[:max_rows], start=1):
        times = row.get("times") or []
        outbound_time = " -> ".join(times[:2]) if len(times) >= 2 else "time-unavailable"
        return_time = " -> ".join(times[2:4]) if len(times) >= 4 else "time-unavailable"
        print(
            f"candidate_{index}={int(row['price']):,} KRW | "
            f"{row.get('outbound_flight')} {outbound_time} | "
            f"{row.get('return_flight')} {return_time} | "
            f"partner={row.get('partner_code')}"
        )
    print(f"result_url={result.url}")
    print("booking_navigation_performed=False")
    print(f"artifact_dir={result.artifact_dir}")


async def run(args: argparse.Namespace) -> int:
    print("==================================================")
    print(" NAVER FLIGHTS SSE API POC")
    print("==================================================")
    print(f"route={args.origin.upper()}->{args.destination.upper()}->{args.origin.upper()}")
    print(f"dates={args.depart}~{args.return_date}")
    print("source=flight-api.naver.com SSE")
    print("direct_only=True")
    print("booking_navigation=False")
    print(f"result_url={build_naver_url(args.origin, args.destination, args.depart, args.return_date)}")
    print("")

    try:
        result = await collect_naver_api_results(
            origin=args.origin,
            destination=args.destination,
            depart=args.depart,
            return_date=args.return_date,
            result_timeout=args.result_timeout,
            artifact_dir=args.artifact_dir,
        )
    except Exception as exc:
        print("\n=== NAVER RESULT ===")
        print("POC_STATUS=FAIL")
        print(f"error={type(exc).__name__}: {exc}")
        print(f"artifact_dir={Path(args.artifact_dir).resolve()}")
        print("diagnostic_files=response.sse.txt,response.json,diagnostics.json,result.json")
        return 2

    _print_rows(result)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Naver Flights SSE API POC")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--destination", default=DEFAULT_DESTINATION)
    parser.add_argument("--depart", default=DEFAULT_DEPART)
    parser.add_argument("--return-date", default=DEFAULT_RETURN)
    parser.add_argument("--result-timeout", type=int, default=30)
    parser.add_argument("--artifact-dir", default="artifacts/naver-flight-poc")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
