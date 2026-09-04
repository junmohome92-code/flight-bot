from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from fast_flights import FlightQuery, Passengers, create_query, get_flights


PRICE_RE = re.compile(r"([0-9][0-9,]*)")


def price_to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = PRICE_RE.search(str(value))
    return int(match.group(1).replace(",", "")) if match else None


def result_items(result: Any) -> list[Any]:
    flights = getattr(result, "flights", None)
    if flights is not None:
        return list(flights)
    try:
        return list(result)
    except TypeError:
        return []


def compact(item: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if is_dataclass(item):
        try:
            data = asdict(item)
        except Exception:
            data = {}
    if not data:
        for name in (
            "price", "airlines", "name", "departure", "arrival", "duration",
            "stops", "is_best", "delay", "flight_number", "flight_numbers",
        ):
            if hasattr(item, name):
                try:
                    data[name] = getattr(item, name)
                except Exception:
                    pass
    if not data:
        data["repr"] = repr(item)
    return data


def search(flights: list[FlightQuery], trip: str) -> tuple[list[Any], list[tuple[int, Any]]]:
    query = create_query(
        flights=flights,
        seat="economy",
        trip=trip,
        passengers=Passengers(adults=1),
        language="ko-KR",
        currency="KRW",
        checked_bags=0,
        hide_separate_and_self_transfer=False,
    )
    result = get_flights(query)
    items = result_items(result)
    priced: list[tuple[int, Any]] = []
    for item in items:
        price = price_to_int(getattr(item, "price", None))
        if price is not None:
            priced.append((price, item))
    priced.sort(key=lambda x: x[0])
    return items, priced


def show(title: str, items: list[Any], priced: list[tuple[int, Any]]) -> None:
    print(f"\n=== {title} ===")
    print(f"results={len(items)} priced={len(priced)}")
    if not priced:
        print("NO PRICE RETURNED")
        if items:
            print("first raw item:")
            print(compact(items[0]))
        return
    print(f"lowest={priced[0][0]:,} KRW")
    for index, (price, item) in enumerate(priced[:5], start=1):
        print(f"#{index} {price:,} KRW | {compact(item)}")


def main() -> None:
    outbound = FlightQuery(
        date="2026-09-18",
        from_airport="CJJ",
        to_airport="TPE",
    )
    inbound = FlightQuery(
        date="2026-09-20",
        from_airport="TPE",
        to_airport="CJJ",
    )

    print("CJJ <-> TPE price probe")
    print("2026-09-18 ~ 2026-09-20 / 1 adult / Economy / KRW")
    print("separate ticket / self-transfer: allowed")

    rt_items, rt_priced = search([outbound, inbound], "round-trip")
    show("ROUND TRIP", rt_items, rt_priced)

    out_items, out_priced = search([outbound], "one-way")
    show("ONE WAY CJJ -> TPE", out_items, out_priced)

    in_items, in_priced = search([inbound], "one-way")
    show("ONE WAY TPE -> CJJ", in_items, in_priced)

    print("\n=== SUMMARY ===")
    if rt_priced:
        print(f"round_trip_lowest={rt_priced[0][0]:,} KRW")
    else:
        print("round_trip_lowest=NONE")

    if out_priced and in_priced:
        split = out_priced[0][0] + in_priced[0][0]
        print(f"split_one_way_sum={split:,} KRW")
    else:
        print("split_one_way_sum=NONE")

    if not rt_priced and not (out_priced and in_priced):
        raise SystemExit("No usable KRW price was returned by fast-flights")


if __name__ == "__main__":
    main()
