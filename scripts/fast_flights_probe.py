from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fast_flights import FlightQuery, Passengers, create_query
from fast_flights.fetcher import fetch_flights_html
from selectolax.lexbor import LexborHTMLParser


ARTIFACT_DIR = Path("artifacts/fast-flights-probe")


def nested_get(value: Any, path: list[int]) -> Any:
    current = value
    for index in path:
        current = current[index]
    return current


def collect_ints(value: Any, out: list[int]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if 10_000 <= value <= 5_000_000:
            out.append(value)
        return
    if isinstance(value, float):
        ivalue = int(value)
        if 10_000 <= ivalue <= 5_000_000:
            out.append(ivalue)
        return
    if isinstance(value, list):
        for item in value:
            collect_ints(item, out)
    elif isinstance(value, dict):
        for item in value.values():
            collect_ints(item, out)


def shape(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, list):
        return [shape(item, depth + 1) for item in value[:6]]
    if isinstance(value, dict):
        return {str(k): shape(v, depth + 1) for k, v in list(value.items())[:6]}
    return type(value).__name__


def extract_payload(html: str) -> Any:
    parser = LexborHTMLParser(html)
    script = parser.css_first(r"script.ds\:1")
    if script is None:
        raise RuntimeError("Google response did not contain script.ds:1")
    js = script.text()
    if "data:" not in js:
        raise RuntimeError("Google script did not contain data: payload")
    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    return json.loads(data)


def row_summary(row: Any, index: int) -> dict[str, Any]:
    summary: dict[str, Any] = {"index": index}

    try:
        flight = row[0]
        summary["type"] = flight[0]
        summary["airlines"] = flight[1]
        segments = flight[2] or []
        summary["segments"] = [
            {
                "from": segment[3] if len(segment) > 3 else None,
                "to": segment[6] if len(segment) > 6 else None,
                "duration_min": segment[11] if len(segment) > 11 else None,
            }
            for segment in segments[:4]
        ]
    except Exception as exc:
        summary["flight_parse_error"] = repr(exc)

    price = None
    try:
        price = nested_get(row, [1, 0, 1])
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            price = None
    except Exception:
        price = None

    try:
        price_tree = row[1]
    except Exception:
        price_tree = None

    candidates: list[int] = []
    collect_ints(price_tree, candidates)
    candidates = sorted(set(candidates))

    summary["price"] = int(price) if price is not None else None
    summary["price_candidates"] = candidates[:20]
    summary["price_shape"] = shape(price_tree)
    summary["price_repr"] = repr(price_tree)[:1200]
    return summary


def search(label: str, flights: list[FlightQuery], trip: str) -> dict[str, Any]:
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

    html = fetch_flights_html(query)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = label.lower().replace(" ", "-").replace("->", "to")
    (ARTIFACT_DIR / f"{safe_name}.html").write_text(html, encoding="utf-8")

    payload = extract_payload(html)
    try:
        rows = payload[3][0] or []
    except Exception as exc:
        raise RuntimeError(f"Google payload flight rows missing: {exc}") from exc

    summaries = [row_summary(row, i) for i, row in enumerate(rows)]
    (ARTIFACT_DIR / f"{safe_name}.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    priced = [item for item in summaries if item.get("price") is not None]
    priced.sort(key=lambda item: item["price"])
    malformed = [item for item in summaries if item.get("price") is None]

    print(f"\n=== {label} ===")
    print(f"rows={len(summaries)} priced_rows={len(priced)} malformed_price_rows={len(malformed)}")
    if priced:
        print(f"lowest={priced[0]['price']:,} KRW")
        for item in priced[:5]:
            print(
                f"row#{item['index']} price={item['price']:,} KRW "
                f"airlines={item.get('airlines')} segments={item.get('segments')}"
            )
    else:
        print("NO DIRECT PRICE PATH SURVIVED")

    if malformed:
        print("malformed examples:")
        for item in malformed[:3]:
            print(
                f"row#{item['index']} candidates={item['price_candidates']} "
                f"shape={item['price_shape']}"
            )
            print(f"  price_repr={item['price_repr']}")

    return {"all": summaries, "priced": priced, "malformed": malformed}


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

    print("CJJ <-> TPE raw Google payload probe")
    print("2026-09-18 ~ 2026-09-20 / 1 adult / Economy / KRW")
    print("fast-flights fetcher: YES / fast-flights parser: BYPASSED")

    round_trip = search("ROUND TRIP", [outbound, inbound], "round-trip")
    one_way_out = search("ONE WAY CJJ -> TPE", [outbound], "one-way")
    one_way_in = search("ONE WAY TPE -> CJJ", [inbound], "one-way")

    print("\n=== SUMMARY ===")
    if round_trip["priced"]:
        print(f"round_trip_lowest={round_trip['priced'][0]['price']:,} KRW")
    else:
        print("round_trip_lowest=NONE")

    if one_way_out["priced"] and one_way_in["priced"]:
        split = one_way_out["priced"][0]["price"] + one_way_in["priced"][0]["price"]
        print(f"split_one_way_sum={split:,} KRW")
    else:
        print("split_one_way_sum=NONE")

    print(f"artifacts={ARTIFACT_DIR.resolve()}")

    if not round_trip["priced"] and not (one_way_out["priced"] and one_way_in["priced"]):
        print("No stable price path found yet. Use malformed row output to update the parser safely.")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
