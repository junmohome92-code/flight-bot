from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from functools import lru_cache
import re

import airportsdata


@dataclass(frozen=True, slots=True)
class LocationOption:
    code: str
    location_type: str  # airport | city
    name: str
    city: str = ""
    country: str = ""

    @property
    def compact_label(self) -> str:
        kind = "전체" if self.location_type == "city" else "공항"
        return f"{self.name} {self.code} · {kind}"


# Naver accepts metropolitan IATA city codes in URLs such as SEL:city and
# TYO:city. Keep only city codes that do not collide with an airport code so a
# persisted three-letter code remains unambiguous without a schema migration.
CITY_GROUPS: dict[str, dict[str, object]] = {
    "SEL": {
        "name": "서울 전체",
        "aliases": ("서울", "서울전체", "seoul", "sel"),
        "airports": ("ICN", "GMP"),
    },
    "TYO": {
        "name": "도쿄 전체",
        "aliases": ("도쿄", "동경", "도쿄전체", "tokyo", "tyo"),
        "airports": ("NRT", "HND"),
    },
    "OSA": {
        "name": "오사카 전체",
        "aliases": ("오사카", "오사카전체", "osaka", "osa"),
        "airports": ("KIX", "ITM", "UKB"),
    },
    "SPK": {
        "name": "삿포로 전체",
        "aliases": ("삿포로", "삿포로전체", "sapporo", "spk"),
        "airports": ("CTS", "OKD"),
    },
    "NYC": {
        "name": "뉴욕 전체",
        "aliases": ("뉴욕", "뉴욕전체", "newyork", "new york", "nyc"),
        "airports": ("JFK", "LGA", "EWR"),
    },
    "LON": {
        "name": "런던 전체",
        "aliases": ("런던", "런던전체", "london", "lon"),
        "airports": ("LHR", "LGW", "LCY", "LTN", "STN"),
    },
    "PAR": {
        "name": "파리 전체",
        "aliases": ("파리", "파리전체", "paris", "par"),
        "airports": ("CDG", "ORY", "BVA"),
    },
    "ROM": {
        "name": "로마 전체",
        "aliases": ("로마", "로마전체", "rome", "rom"),
        "airports": ("FCO", "CIA"),
    },
    "MIL": {
        "name": "밀라노 전체",
        "aliases": ("밀라노", "밀라노전체", "milan", "milano", "mil"),
        "airports": ("MXP", "LIN", "BGY"),
    },
    "WAS": {
        "name": "워싱턴 전체",
        "aliases": ("워싱턴", "워싱턴전체", "washington", "was"),
        "airports": ("DCA", "IAD", "BWI"),
    },
    "BJS": {
        "name": "베이징 전체",
        "aliases": ("베이징", "북경", "베이징전체", "beijing", "bjs"),
        "airports": ("PEK", "PKX"),
    },
}


# Friendly Korean aliases for airports users of this bot are likely to type.
# The full IATA catalogue still comes from airportsdata, so exact codes outside
# this table remain valid.
AIRPORT_ALIASES: dict[str, tuple[str, ...]] = {
    "CJJ": ("청주", "청주공항", "청주국제공항"),
    "ICN": ("인천", "인천공항", "인천국제공항"),
    "GMP": ("김포", "김포공항", "김포국제공항"),
    "PUS": ("부산", "김해", "김해공항", "김해국제공항"),
    "CJU": ("제주", "제주공항", "제주국제공항"),
    "NRT": ("나리타", "나리타공항"),
    "HND": ("하네다", "하네다공항"),
    "KIX": ("간사이", "간사이공항", "간사이국제공항"),
    "ITM": ("이타미", "이타미공항"),
    "UKB": ("고베", "고베공항"),
    "FUK": ("후쿠오카", "후쿠오카공항"),
    "TPE": ("타이베이", "타오위안", "타오위안공항", "타오위안국제공항"),
    "TSA": ("송산", "쑹산", "타이베이송산"),
    "CTS": ("신치토세", "신치토세공항"),
}


FRIENDLY_NAMES: dict[str, str] = {
    "CJJ": "청주",
    "ICN": "인천",
    "GMP": "김포",
    "PUS": "김해",
    "CJU": "제주",
    "NRT": "나리타",
    "HND": "하네다",
    "KIX": "간사이",
    "ITM": "이타미",
    "UKB": "고베",
    "FUK": "후쿠오카",
    "TPE": "타오위안",
    "TSA": "송산",
    "CTS": "신치토세",
}


_TOKEN_RE = re.compile(r"[^0-9a-z가-힣]+", re.IGNORECASE)


def _norm(value: str) -> str:
    return _TOKEN_RE.sub("", (value or "").strip().casefold())


@lru_cache(maxsize=1)
def airport_catalogue() -> dict[str, dict]:
    # airportsdata ships its catalogue inside the Python package; no network
    # request is performed at runtime.
    data = airportsdata.load("IATA")
    return {str(code).upper(): value for code, value in data.items() if len(str(code)) == 3}


def _airport_option(code: str) -> LocationOption | None:
    code = code.upper()
    row = airport_catalogue().get(code)
    if not row:
        return None
    name = FRIENDLY_NAMES.get(code) or str(row.get("name") or row.get("city") or code)
    return LocationOption(
        code=code,
        location_type="airport",
        name=name,
        city=str(row.get("city") or ""),
        country=str(row.get("country") or ""),
    )


def _city_option(code: str) -> LocationOption | None:
    data = CITY_GROUPS.get(code.upper())
    if not data:
        return None
    return LocationOption(code=code.upper(), location_type="city", name=str(data["name"]))


def location_type(code: str) -> str:
    """Infer the Naver location type for a persisted unambiguous code."""
    code = (code or "").strip().upper()
    return "city" if code in CITY_GROUPS else "airport"


def is_known_location(code: str) -> bool:
    code = (code or "").strip().upper()
    return code in CITY_GROUPS or code in airport_catalogue()


def display_location(code: str) -> str:
    code = (code or "").strip().upper()
    city = _city_option(code)
    if city:
        return f"{city.name}({code})"
    airport = _airport_option(code)
    if airport:
        return f"{airport.name}({code})"
    return code


def _dedupe(options: list[LocationOption], limit: int = 6) -> list[LocationOption]:
    seen: set[tuple[str, str]] = set()
    out: list[LocationOption] = []
    for option in options:
        key = (option.code, option.location_type)
        if key in seen:
            continue
        seen.add(key)
        out.append(option)
        if len(out) >= limit:
            break
    return out


def exact_location_options(text: str, *, limit: int = 6) -> list[LocationOption]:
    """Return exact semantic matches. City names may intentionally return a
    city-wide option plus its individual airports.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    normalized = _norm(raw)
    upper = raw.upper()
    options: list[LocationOption] = []

    # Exact 3-letter code. Airport wins when a code exists in the airport
    # catalogue; city groups in this module deliberately avoid collisions.
    if len(upper) == 3 and upper.isalpha():
        airport = _airport_option(upper)
        city = _city_option(upper)
        if airport:
            options.append(airport)
        elif city:
            options.append(city)
        return _dedupe(options, limit)

    # Friendly airport aliases.
    for code, aliases in AIRPORT_ALIASES.items():
        if normalized in {_norm(alias) for alias in aliases}:
            option = _airport_option(code)
            if option:
                options.append(option)

    # Metropolitan city aliases: return overall city first, followed by its
    # individual airports so users can choose the exact airport if preferred.
    for code, data in CITY_GROUPS.items():
        aliases = tuple(data.get("aliases") or ())
        if normalized in {_norm(str(alias)) for alias in aliases}:
            city = _city_option(code)
            if city:
                options.insert(0, city)
            for airport_code in tuple(data.get("airports") or ()):
                airport = _airport_option(str(airport_code))
                if airport:
                    options.append(airport)

    # Exact airport name/city from the full catalogue. This gives useful
    # behaviour for airports not present in the Korean alias table.
    if not options:
        matches: list[LocationOption] = []
        for code, row in airport_catalogue().items():
            values = (str(row.get("name") or ""), str(row.get("city") or ""))
            if normalized and any(_norm(value) == normalized for value in values):
                option = _airport_option(code)
                if option:
                    matches.append(option)
        options.extend(matches)

    return _dedupe(options, limit)


def suggest_locations(text: str, *, limit: int = 6) -> list[LocationOption]:
    """Suggest close real locations for typos such as CJX.

    Suggestions never turn into a saved value automatically; Telegram asks the
    user to choose one explicitly.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    upper = raw.upper()
    options: list[LocationOption] = []

    if len(upper) == 3 and upper.isalpha():
        # Put familiar Korean airports first when prefixes are close, then use
        # difflib over the complete IATA code catalogue.
        familiar = list(AIRPORT_ALIASES)
        all_codes = list(dict.fromkeys(familiar + list(CITY_GROUPS) + list(airport_catalogue())))
        for code in get_close_matches(upper, all_codes, n=max(limit * 2, 10), cutoff=0.5):
            option = _city_option(code) or _airport_option(code)
            if option:
                options.append(option)
        return _dedupe(options, limit)

    normalized = _norm(raw)
    alias_pairs: list[tuple[str, LocationOption]] = []
    for code, aliases in AIRPORT_ALIASES.items():
        option = _airport_option(code)
        if option:
            for alias in aliases:
                alias_pairs.append((_norm(alias), option))
    for code, data in CITY_GROUPS.items():
        option = _city_option(code)
        if option:
            for alias in tuple(data.get("aliases") or ()):
                alias_pairs.append((_norm(str(alias)), option))

    keys = [alias for alias, _ in alias_pairs if alias]
    for match in get_close_matches(normalized, keys, n=max(limit * 2, 10), cutoff=0.45):
        for alias, option in alias_pairs:
            if alias == match:
                options.append(option)
                break
    return _dedupe(options, limit)


def resolve_code_token(token: str) -> LocationOption | None:
    """Resolve a command/API three-letter token deterministically."""
    token = (token or "").strip().upper()
    if len(token) != 3 or not token.isalpha():
        return None
    airport = _airport_option(token)
    if airport:
        return airport
    return _city_option(token)
