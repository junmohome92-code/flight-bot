from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

MIN_KRW_PRICE = 50_000
MAX_KRW_PRICE = 1_500_000
MIN_RETURN_ADJUSTMENT = 0

_KRW_SYMBOL_RE = re.compile(r"₩\s*([0-9][0-9,]*)")
_KRW_WORD_RE = re.compile(r"([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b", re.I)
_FLIGHT_SHAPE_RE = re.compile(r"nonstop|stops?|직항|경유|\bhr\b|시간", re.I)
_BROAD_MARKERS = (
    "flight search",
    "search results",
    "all filters",
    "top departing flights",
    "other departing flights",
    "sorted by",
    "checking prices from multiple sources",
    "searching nearby airports",
    "checking online travel agencies",
    "finding the cheapest booking options",
)


@dataclass(frozen=True, slots=True)
class UiFlightCandidate:
    price: int
    row_text: str
    seen_at_ms: float = 0.0
    candidate_id: str | None = None


def parse_krw_prices(
    text: str | None,
    *,
    min_price: int = MIN_KRW_PRICE,
    max_price: int = MAX_KRW_PRICE,
) -> list[int]:
    """Return KRW amounts in the requested semantic range.

    Departure/Booking totals use the normal 50k+ plausibility floor.  Returning
    flight selectors may show a *price adjustment* such as +₩0 or +₩25,000,
    so callers for that phase explicitly pass ``min_price=0``.
    """
    if not text:
        return []
    values = [int(raw.replace(",", "")) for raw in _KRW_SYMBOL_RE.findall(text)]
    values.extend(int(raw.replace(",", "")) for raw in _KRW_WORD_RE.findall(text))
    return sorted({value for value in values if min_price <= value <= max_price})


def normalize_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("–", "-").replace("—", "-")).strip()


def _route_count(text: str, origin: str, destination: str) -> int:
    token = f"{origin.upper()}-{destination.upper()}"
    return normalize_text(text).upper().count(token)


def flight_card_is_specific(
    text: str | None,
    origin: str,
    destination: str,
    *,
    allow_missing_route: bool = False,
    min_price: int = MIN_KRW_PRICE,
) -> bool:
    """Accept one compact flight card and reject page/list containers."""
    if not text or len(text) > 1800:
        return False
    lowered = normalize_text(text).lower()
    if any(marker in lowered for marker in _BROAD_MARKERS):
        return False

    times = _TIME_RE.findall(text)
    if not 2 <= len(times) <= 4:
        return False
    if not _FLIGHT_SHAPE_RE.search(text):
        return False

    prices = parse_krw_prices(text, min_price=min_price)
    if not 1 <= len(prices) <= 3:
        return False

    forward = _route_count(text, origin, destination)
    reverse = _route_count(text, destination, origin)
    if reverse:
        return False
    if allow_missing_route:
        return forward in {0, 1}
    return forward == 1


def candidate_from_mapping(
    value: Mapping[str, object],
    *,
    min_price: int = MIN_KRW_PRICE,
) -> UiFlightCandidate | None:
    try:
        price = int(value.get("price"))
    except (TypeError, ValueError):
        return None
    if not min_price <= price <= MAX_KRW_PRICE:
        return None
    row_text = str(value.get("rowText") or "").strip()
    try:
        seen_at_ms = float(value.get("seenAtMs") or 0.0)
    except (TypeError, ValueError):
        seen_at_ms = 0.0
    candidate_id = str(value.get("id")) if value.get("id") else None
    return UiFlightCandidate(price=price, row_text=row_text, seen_at_ms=seen_at_ms, candidate_id=candidate_id)


def choose_lowest_candidate(
    candidates: Sequence[Mapping[str, object]] | Iterable[Mapping[str, object]],
    *,
    origin: str,
    destination: str,
    advertised_price: int | None = None,
    allow_missing_route: bool = False,
    min_price: int = MIN_KRW_PRICE,
) -> Mapping[str, object] | None:
    """Choose the lowest preserved snapshot and fail closed on a cheaper hint."""
    eligible: list[tuple[int, float, Mapping[str, object]]] = []
    for raw in candidates:
        candidate = candidate_from_mapping(raw, min_price=min_price)
        if candidate is None:
            continue
        if not flight_card_is_specific(
            candidate.row_text,
            origin,
            destination,
            allow_missing_route=allow_missing_route,
            min_price=min_price,
        ):
            continue
        if advertised_price is not None and candidate.price > advertised_price:
            continue
        eligible.append((candidate.price, candidate.seen_at_ms, raw))
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item[0], item[1]))
    return eligible[0][2]


def departure_capture_ready(
    *,
    candidate_count: int,
    elapsed_ms: float,
    advertised_stable_ms: float,
    loading: bool,
    capture_window_ms: int,
) -> bool:
    """Prevent an early one-row loading snapshot from becoming the cheapest.

    While Google is still fetching, require at least two concrete flight rows.
    If fetching has finished, one row is enough (important for thin routes).
    In both cases the advertised Cheapest value must have stopped changing for
    a short debounce period.
    """
    if candidate_count < 1 or elapsed_ms < capture_window_ms:
        return False
    if advertised_stable_ms < 250:
        return False
    if loading and candidate_count < 2:
        return False
    return True
