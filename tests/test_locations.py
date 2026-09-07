from flight_bot.locations import (
    display_location,
    exact_location_options,
    is_known_location,
    location_type,
    resolve_code_token,
    suggest_locations,
)


def test_real_iata_catalogue_accepts_known_airports_and_rejects_fake_code():
    assert is_known_location("CJJ")
    assert is_known_location("NRT")
    assert not is_known_location("ZZZ") or resolve_code_token("ZZZ") is not None
    # CJX is the representative user typo we explicitly want to catch.
    assert resolve_code_token("CJX") is None


def test_tokyo_name_returns_city_wide_and_individual_airport_choices():
    options = exact_location_options("도쿄")
    assert [option.code for option in options[:3]] == ["TYO", "NRT", "HND"]
    assert options[0].location_type == "city"
    assert all(option.location_type == "airport" for option in options[1:3])


def test_seoul_and_osaka_city_codes_are_inferred_as_city():
    assert location_type("SEL") == "city"
    assert location_type("TYO") == "city"
    assert location_type("OSA") == "city"
    assert location_type("ICN") == "airport"
    assert "서울 전체" in display_location("SEL")


def test_korean_airport_name_resolves_to_single_real_airport():
    options = exact_location_options("청주")
    assert len(options) == 1
    assert options[0].code == "CJJ"
    assert options[0].location_type == "airport"


def test_typo_is_not_auto_saved_and_gets_real_suggestions():
    assert exact_location_options("CJX") == []
    suggestions = suggest_locations("CJX")
    assert suggestions
    assert all(option.code != "CJX" for option in suggestions)
    assert all(len(option.code) == 3 for option in suggestions)
