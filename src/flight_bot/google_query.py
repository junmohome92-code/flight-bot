from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date


QUERY_CONTRACT = "accepted-tfs-v1"


class GoogleQueryError(ValueError):
    pass


def _varint(value: int) -> bytes:
    if value < 0:
        raise GoogleQueryError("varint cannot encode a negative value")
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            return bytes(out)


def _key(field: int, wire_type: int) -> bytes:
    return _varint((field << 3) | wire_type)


def _varint_field(field: int, value: int) -> bytes:
    return _key(field, 0) + _varint(value)


def _bytes_field(field: int, value: bytes) -> bytes:
    return _key(field, 2) + _varint(len(value)) + value


def _airport_message(code: str) -> bytes:
    # This exact small sub-message is what the live Windows acceptance URL used.
    return _varint_field(1, 1) + _bytes_field(2, code.encode("ascii"))


def _leg_message(travel_date: str, origin: str, destination: str) -> bytes:
    return b"".join(
        [
            _bytes_field(2, travel_date.encode("ascii")),
            _bytes_field(13, _airport_message(origin)),
            _bytes_field(14, _airport_message(destination)),
        ]
    )


def _validate_airport(code: str) -> str:
    value = (code or "").strip().upper()
    if len(value) != 3 or not value.isalpha() or not value.isascii():
        raise GoogleQueryError(f"invalid IATA airport code: {code!r}")
    return value


def _validate_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise GoogleQueryError(f"invalid ISO date: {value!r}") from exc
    return value


def build_tfs_token(
    *,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
) -> str:
    """Build the exact round-trip TFS shape proven by the live Windows probe.

    Important product decision: this query intentionally does *not* encode a
    stop-count filter. Google is asked for the normal round-trip result surface,
    then the bot filters explicit Nonstop/direct rows after capture. That keeps
    the production URL shape identical to the accepted live path instead of the
    previous fast-flights-generated URL that repeatedly produced Price
    unavailable.
    """

    origin = _validate_airport(origin)
    destination = _validate_airport(destination)
    depart_date = _validate_date(depart_date)
    return_date = _validate_date(return_date)
    if date.fromisoformat(return_date) < date.fromisoformat(depart_date):
        raise GoogleQueryError("return date cannot be before departure date")
    if origin == destination:
        raise GoogleQueryError("origin and destination must differ")

    payload = b"".join(
        [
            _varint_field(1, 28),
            _varint_field(2, 2),
            _bytes_field(3, _leg_message(depart_date, origin, destination)),
            _bytes_field(3, _leg_message(return_date, destination, origin)),
            _varint_field(8, 1),
            _varint_field(9, 1),
            _varint_field(14, 1),
            _bytes_field(16, _varint_field(1, (1 << 64) - 1)),
            _varint_field(19, 1),
        ]
    )
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def build_google_flights_search_url(
    *,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    language: str = "en",
    gl: str = "kr",
    currency: str = "KRW",
) -> str:
    token = build_tfs_token(
        origin=origin,
        destination=destination,
        depart_date=depart_date,
        return_date=return_date,
    )
    return (
        "https://www.google.com/travel/flights/search"
        f"?tfs={token}&hl={language}&gl={gl}&curr={currency}"
    )
