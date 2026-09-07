from flight_bot.naver_search import build_payload, build_result_url


def test_naver_city_result_url_matches_sel_tyo_shape():
    url = build_result_url("SEL", "TYO", "2026-09-22", "2026-09-24")
    assert "SEL:city-TYO:city-20260922" in url
    assert "TYO:city-SEL:city-20260924" in url
    assert "adult=1" in url
    assert "fareType=Y" in url
    assert "isDirect=true" in url


def test_naver_city_payload_uses_city_location_types_and_no_airport_lock():
    payload = build_payload("SEL", "TYO", "2026-09-22", "2026-09-24")
    outbound, returning = payload["itineraries"]
    assert outbound["departureLocationCode"] == "SEL"
    assert outbound["departureLocationType"] == "city"
    assert outbound["arrivalLocationCode"] == "TYO"
    assert outbound["arrivalLocationType"] == "city"
    assert returning["departureLocationCode"] == "TYO"
    assert returning["arrivalLocationCode"] == "SEL"
    filters = payload["flightFilter"]["filter"]
    assert filters["departureAirports"] == [[], []]
    assert filters["arrivalAirports"] == [[], []]
    assert filters["isSameDepArrAirport"] is False
    assert payload["tripType"] == "RT"
    assert payload["isNonstop"] is True


def test_airport_payload_preserves_existing_airport_contract():
    payload = build_payload("CJJ", "TPE", "2026-09-18", "2026-09-20")
    outbound, returning = payload["itineraries"]
    assert outbound["departureLocationType"] == "airport"
    assert outbound["arrivalLocationType"] == "airport"
    assert returning["departureLocationType"] == "airport"
    assert returning["arrivalLocationType"] == "airport"
    filters = payload["flightFilter"]["filter"]
    assert filters["departureAirports"] == [["CJJ"], []]
    assert filters["arrivalAirports"] == [[], ["CJJ"]]
    assert filters["isSameDepArrAirport"] is True
