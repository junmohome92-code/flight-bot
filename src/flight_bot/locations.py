from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

import airportsdata
import airportsearch


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


# Compatibility aliases keep the familiar Korean UX deterministic. They are no
# longer the worldwide data source: airportsearch's bundled GeoNames/OpenTravelData
# index supplies multilingual names and metropolitan city codes globally.
LEGACY_CITY_GROUPS: dict[str, dict[str, object]] = {
    "SEL": {"name": "서울", "aliases": ("서울", "서울전체", "seoul", "sel"), "airports": ("ICN", "GMP")},
    "TYO": {"name": "도쿄", "aliases": ("도쿄", "동경", "도쿄전체", "tokyo", "tyo"), "airports": ("NRT", "HND")},
    "OSA": {"name": "오사카", "aliases": ("오사카", "오사카전체", "osaka", "osa"), "airports": ("KIX", "ITM", "UKB")},
    "SPK": {"name": "삿포로", "aliases": ("삿포로", "삿포로전체", "sapporo", "spk"), "airports": ("CTS", "OKD")},
    "NYC": {"name": "뉴욕", "aliases": ("뉴욕", "뉴욕전체", "newyork", "new york", "nyc"), "airports": ("JFK", "LGA", "EWR")},
    "LON": {"name": "런던", "aliases": ("런던", "런던전체", "london", "lon"), "airports": ("LHR", "LGW", "LCY", "LTN", "STN")},
    "PAR": {"name": "파리", "aliases": ("파리", "파리전체", "paris", "par"), "airports": ("CDG", "ORY", "BVA")},
    "ROM": {"name": "로마", "aliases": ("로마", "로마전체", "rome", "rom"), "airports": ("FCO", "CIA")},
    "MIL": {"name": "밀라노", "aliases": ("밀라노", "밀라노전체", "milan", "milano", "mil"), "airports": ("MXP", "LIN", "BGY")},
    "WAS": {"name": "워싱턴", "aliases": ("워싱턴", "워싱턴전체", "washington", "was"), "airports": ("DCA", "IAD", "BWI")},
    "BJS": {"name": "베이징", "aliases": ("베이징", "북경", "베이징전체", "beijing", "bjs"), "airports": ("PEK", "PKX")},
}


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
_HANGUL_RE = re.compile(r"[가-힣]")


def _norm(value: str) -> str:
    return _TOKEN_RE.sub("", (value or "").strip().casefold())


def _has_hangul(value: str) -> bool:
    return bool(_HANGUL_RE.search(value or ""))


@lru_cache(maxsize=1)
def airport_catalogue() -> dict[str, dict]:
    # airportsdata remains the authoritative exact-IATA validation fallback.
    data = airportsdata.load("IATA")
    return {str(code).upper(): value for code, value in data.items() if len(str(code)) == 3}


def _airport_option(code: str, *, preferred_name: str | None = None) -> LocationOption | None:
    code = (code or "").upper()
    airport = None
    try:
        airport = airportsearch.get_index().get(code)
    except Exception:
        airport = None

    row = airport_catalogue().get(code)
    if airport is None and row is None:
        return None

    name = preferred_name or FRIENDLY_NAMES.get(code)
    if not name:
        name = str(getattr(airport, "name", "") or (row or {}).get("name") or (row or {}).get("city") or code)
    city = str(getattr(airport, "city_name", "") or (row or {}).get("city") or "")
    country = str(getattr(airport, "country_name", "") or (row or {}).get("country") or "")
    return LocationOption(code=code, location_type="airport", name=name, city=city, country=country)


def _city_option(code: str, name: str, *, country: str = "") -> LocationOption:
    clean = (name or code).strip()
    if clean.endswith(" 전체"):
        clean = clean[:-3].strip()
    return LocationOption(code=code.upper(), location_type="city", name=clean or code.upper(), country=country)


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


def _search(text: str, *, limit: int, nearest_fallback: bool) -> list:
    try:
        return list(
            airportsearch.search(
                text,
                k=max(limit, 8),
                nearest_fallback=nearest_fallback,
            )
        )
    except Exception:
        return []


def _options_from_hits(text: str, hits: list, *, limit: int, exact_only: bool) -> list[LocationOption]:
    query_norm = airportsearch.normalize(text)
    selected = []
    for hit in hits:
        if exact_only:
            matched_norm = airportsearch.normalize(str(getattr(hit, "matched", "") or ""))
            if matched_norm != query_norm:
                continue
        selected.append(hit)

    if not selected:
        return []

    # A metropolitan code is useful only when it actually represents multiple
    # airports. Group matching hits by city_iata and place the city-wide choice
    # before its airport choices.
    by_city: dict[str, list] = {}
    for hit in selected:
        airport = hit.airport
        city_code = str(airport.city_iata or "").upper()
        if city_code and city_code != airport.iata.upper():
            by_city.setdefault(city_code, []).append(hit)

    options: list[LocationOption] = []
    inserted_cities: set[str] = set()
    for hit in selected:
        airport = hit.airport
        city_code = str(airport.city_iata or "").upper()
        members = by_city.get(city_code, []) if city_code else []
        if city_code and city_code not in inserted_cities and len({m.airport.iata for m in members}) >= 2:
            legacy = LEGACY_CITY_GROUPS.get(city_code)
            if legacy:
                city_name = str(legacy["name"])
            elif _has_hangul(text):
                city_name = text.strip()
            else:
                city_name = str(airport.city_name or city_code)
            options.append(_city_option(city_code, city_name, country=str(airport.country_name or "")))
            inserted_cities.add(city_code)

        preferred_name = None
        matched = str(getattr(hit, "matched", "") or "").strip()
        if _has_hangul(matched) and len(matched) <= 40:
            preferred_name = matched
        option = _airport_option(airport.iata, preferred_name=preferred_name)
        if option:
            options.append(option)

    return _dedupe(options, limit)


def _legacy_exact(text: str, *, limit: int) -> list[LocationOption]:
    normalized = _norm(text)
    options: list[LocationOption] = []
    for code, aliases in AIRPORT_ALIASES.items():
        if normalized in {_norm(alias) for alias in aliases}:
            option = _airport_option(code)
            if option:
                options.append(option)

    for code, data in LEGACY_CITY_GROUPS.items():
        if normalized in {_norm(str(alias)) for alias in tuple(data.get("aliases") or ())}:
            options.insert(0, _city_option(code, str(data["name"])))
            for airport_code in tuple(data.get("airports") or ()):
                option = _airport_option(str(airport_code))
                if option:
                    options.append(option)
    return _dedupe(options, limit)


def exact_location_options(text: str, *, limit: int = 6) -> list[LocationOption]:
    """Resolve exact airport/city input without silently accepting a typo.

    Full multilingual matching comes from airportsearch's bundled offline index.
    Fuzzy-only matches are intentionally left to ``suggest_locations`` so the
    user must tap the intended airport/city before it is saved.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    upper = raw.upper()

    if len(upper) == 3 and upper.isalpha():
        airport = _airport_option(upper)
        hits = _search(upper, limit=max(limit * 2, 10), nearest_fallback=False)
        city_members = [hit for hit in hits if str(hit.airport.city_iata or "").upper() == upper]
        options: list[LocationOption] = []
        unique_member_codes = {hit.airport.iata.upper() for hit in city_members}
        if airport:
            options.append(airport)
        if len(unique_member_codes) >= 2:
            legacy = LEGACY_CITY_GROUPS.get(upper)
            city_name = str(legacy["name"]) if legacy else str(city_members[0].airport.city_name or upper)
            options.append(_city_option(upper, city_name, country=str(city_members[0].airport.country_name or "")))
            for hit in city_members:
                member = _airport_option(hit.airport.iata)
                if member:
                    options.append(member)
        elif not airport and upper in LEGACY_CITY_GROUPS:
            data = LEGACY_CITY_GROUPS[upper]
            options.append(_city_option(upper, str(data["name"])))
            for member_code in tuple(data.get("airports") or ()):
                member = _airport_option(str(member_code))
                if member:
                    options.append(member)
        return _dedupe(options, limit)

    legacy = _legacy_exact(raw, limit=limit)
    if legacy:
        return legacy

    hits = _search(raw, limit=max(limit * 2, 10), nearest_fallback=False)
    return _options_from_hits(raw, hits, limit=limit, exact_only=True)


def suggest_locations(text: str, *, limit: int = 6) -> list[LocationOption]:
    """Return fuzzy multilingual suggestions without auto-saving them."""
    raw = (text or "").strip()
    if not raw:
        return []

    upper = raw.upper()
    if len(upper) == 3 and upper.isalpha():
        # An invalid IATA token must never silently turn into a different code.
        # Search the full catalogue for close codes and present choices instead.
        from difflib import get_close_matches

        all_codes = list(airport_catalogue())
        options: list[LocationOption] = []
        for code in get_close_matches(upper, all_codes, n=max(limit * 2, 10), cutoff=0.5):
            option = _airport_option(code)
            if option:
                options.append(option)
        return _dedupe(options, limit)

    hits = _search(raw, limit=max(limit * 3, 12), nearest_fallback=True)
    options = _options_from_hits(raw, hits, limit=limit, exact_only=False)
    if options:
        return options

    # Last compatibility fallback for familiar aliases if the third-party index
    # ever fails to initialize; exact-IATA validation still stays available.
    return _legacy_exact(raw, limit=limit)


def resolve_code_token(token: str, *, expected_type: str | None = None) -> LocationOption | None:
    """Resolve a three-letter code deterministically for API/command callers."""
    token = (token or "").strip().upper()
    if len(token) != 3 or not token.isalpha():
        return None
    options = exact_location_options(token, limit=12)
    if expected_type in {"airport", "city"}:
        return next((option for option in options if option.code == token and option.location_type == expected_type), None)
    # Preserve airport semantics for an exact airport code. A city-only code such
    # as TYO/SEL falls through to its city option.
    airport = next((option for option in options if option.code == token and option.location_type == "airport"), None)
    if airport:
        return airport
    return next((option for option in options if option.code == token and option.location_type == "city"), None)


def location_type(code: str) -> str:
    option = resolve_code_token(code)
    return option.location_type if option else "airport"


def is_known_location(code: str) -> bool:
    return resolve_code_token(code) is not None


def display_location(code: str, expected_type: str | None = None) -> str:
    code = (code or "").strip().upper()
    option = resolve_code_token(code, expected_type=expected_type) if code else None
    if option:
        suffix = " 전체" if option.location_type == "city" else ""
        return f"{option.name}{suffix}({code})"
    airport = _airport_option(code)
    if airport:
        return f"{airport.name}({code})"
    return code
