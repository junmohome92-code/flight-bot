from __future__ import annotations

from typing import Iterable

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.search import SearchFlights


def iata(value) -> str:
    name = getattr(value, "name", None)
    return (name or str(value)).lstrip("_")


def flight_price(itinerary) -> float | None:
    results = list(itinerary) if isinstance(itinerary, tuple) else [itinerary]
    values = [float(item.price) for item in results if item.price is not None]
    return min(values) if values else None


def fmt_price(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    return f"{int(round(value)):,} KRW"


def result_lines(result, label: str) -> list[str]:
    lines = [f"{label}: price={fmt_price(result.price)} stops={result.stops} duration={result.duration}m"]
    for leg in result.legs:
        lines.append(
            "  "
            + f"{iata(leg.airline)} {leg.flight_number} "
            + f"{iata(leg.departure_airport)}->{iata(leg.arrival_airport)} "
            + f"{leg.departure_datetime} -> {leg.arrival_datetime}"
        )
    lines.append(
        "  "
        + f"self_transfer={result.self_transfer} booking_token={'yes' if result.booking_token else 'no'}"
    )
    return lines


def print_itinerary(index: int, itinerary) -> None:
    print(f"\n--- itinerary #{index} observed={fmt_price(flight_price(itinerary))} ---")
    if isinstance(itinerary, tuple):
        for line in result_lines(itinerary[0], "OUT"):
            print(line)
        for line in result_lines(itinerary[1], "BACK"):
            print(line)
    else:
        for line in result_lines(itinerary, "FLIGHT"):
            print(line)


def booking_price(options: Iterable) -> tuple[float | None, object | None]:
    priced = [(float(option.price), option) for option in options if option.price is not None]
    if not priced:
        return None, None
    priced.sort(key=lambda pair: pair[0])
    return priced[0]


def main() -> None:
    print("Fli direct Google Flights service probe")
    print("CJJ <-> TPE / 2026-09-18 ~ 2026-09-20 / 1 adult / Economy / KRW")
    print("sort=CHEAPEST / all stops and mixed airlines allowed")

    filters = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.CJJ, 0]],
                arrival_airport=[[Airport.TPE, 0]],
                travel_date="2026-09-18",
            ),
            FlightSegment(
                departure_airport=[[Airport.TPE, 0]],
                arrival_airport=[[Airport.CJJ, 0]],
                travel_date="2026-09-20",
            ),
        ],
        seat_type=SeatType.ECONOMY,
        sort_by=SortBy.CHEAPEST,
        show_all_results=True,
    )

    search = SearchFlights()
    results = search.search(
        filters,
        top_n=12,
        currency="KRW",
        language="ko-KR",
        country="KR",
    )
    if not results:
        raise SystemExit("Fli returned no round-trip results")

    ordered = sorted(results, key=lambda item: (flight_price(item) is None, flight_price(item) or 10**18))
    print(f"\nround_trip_itineraries={len(ordered)}")
    for index, itinerary in enumerate(ordered[:10], start=1):
        print_itinerary(index, itinerary)

    print("\n=== BOOKING VERIFICATION (top 5) ===")
    verified: list[tuple[float, int, object, object]] = []
    for index, itinerary in enumerate(ordered[:5], start=1):
        try:
            options = search.get_booking_options(
                itinerary,
                filters,
                currency="KRW",
                language="ko-KR",
                country="KR",
            )
        except Exception as exc:
            print(f"itinerary #{index}: booking lookup failed: {type(exc).__name__}: {exc}")
            continue

        low, option = booking_price(options)
        if low is None or option is None:
            print(f"itinerary #{index}: booking options={len(options)} but no priced vendor")
            continue

        verified.append((low, index, itinerary, option))
        print(
            f"itinerary #{index}: BOOKABLE {int(round(low)):,} KRW "
            f"vendor={option.vendor_name or option.vendor_code or 'unknown'} "
            f"airline_direct={option.is_airline_direct} fare={option.fare_name or '-'}"
        )
        if option.booking_url:
            print(f"  booking_url={option.booking_url}")
        elif option.google_click_url:
            print(f"  google_click_url={option.google_click_url}")

    print("\n=== SUMMARY ===")
    observed = [flight_price(item) for item in ordered]
    observed = [price for price in observed if price is not None]
    if observed:
        print(f"observed_lowest={int(round(min(observed))):,} KRW")
    else:
        print("observed_lowest=NONE")

    if verified:
        verified.sort(key=lambda item: item[0])
        low, index, _, option = verified[0]
        print(f"bookable_lowest={int(round(low)):,} KRW")
        print(f"bookable_itinerary=#{index}")
        print(f"bookable_vendor={option.vendor_name or option.vendor_code or 'unknown'}")
    else:
        print("bookable_lowest=NONE")
        raise SystemExit("Search results were found, but no booking price could be verified")


if __name__ == "__main__":
    main()
