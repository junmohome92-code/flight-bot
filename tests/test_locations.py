from flight_bot.locations import (
    display_location,
    exact_location_options,
    is_known_location,
    location_type,
    resolve_code_token,
    suggest_locations,
)


def _codes(options):
    return [option.code for option in options]


def test_real_iata_catalogue_accepts_known_airports_and_rejects_fake_code():
    assert is_known_location("CJJ")
    assert is_known_location("NRT")
    # CJX is the representative user typo we explicitly want to catch.
    assert resolve_code_token("CJX") is None


def test_tokyo_name_returns_city_wide_and_individual_airport_choices():
    options = exact_location_options("도쿄")
    assert _codes(options)[:3] == ["TYO", "NRT", "HND"]
    assert options[0].location_type == "city"
    assert all(option.location_type == "airport" for option in options[1:3])


def test_seoul_and_osaka_city_codes_are_explicit_city_options():
    assert resolve_code_token("SEL", expected_type="city").location_type == "city"
    assert resolve_code_token("TYO", expected_type="city").location_type == "city"
    assert resolve_code_token("OSA", expected_type="city").location_type == "city"
    assert location_type("ICN") == "airport"
    assert "서울" in display_location("SEL", "city")


def test_korean_airport_name_resolves_to_single_real_airport():
    options = exact_location_options("청주")
    assert len(options) == 1
    assert options[0].code == "CJJ"
    assert options[0].location_type == "airport"


def test_worldwide_multilingual_search_surfaces_hiroshima_hij():
    # GeoNames-backed airportsearch may resolve the Korean alternate name as an
    # exact alias; if a particular dataset build treats it as fuzzy, it must at
    # least be offered as an explicit selectable suggestion rather than vanish.
    korean = exact_location_options("히로시마") or suggest_locations("히로시마")
    assert "HIJ" in _codes(korean)

    english = exact_location_options("Hiroshima") or suggest_locations("Hiroshima")
    assert "HIJ" in _codes(english)
    assert resolve_code_token("HIJ", expected_type="airport").code == "HIJ"


def test_worldwide_city_search_builds_metro_choice_from_multilingual_index():
    options = exact_location_options("New York")
    codes = _codes(options)
    assert "NYC" in codes
    assert {"JFK", "LGA", "EWR"} & set(codes)
    city = next(option for option in options if option.code == "NYC")
    assert city.location_type == "city"


def test_typo_is_not_auto_saved_and_gets_real_suggestions():
    assert exact_location_options("CJX") == []
    suggestions = suggest_locations("CJX")
    assert suggestions
    assert all(option.code != "CJX" for option in suggestions)
    assert all(len(option.code) == 3 for option in suggestions)
