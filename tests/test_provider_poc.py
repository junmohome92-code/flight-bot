from flight_bot.naver_api import (
    build_payload,
    build_result_url,
    parse_sse_events,
    rows_from_payload,
    select_best_payload,
)


def test_naver_result_url_is_direct_round_trip_search():
    url = build_result_url("CJJ", "TPE", "2026-09-18", "2026-09-20")
    assert url.startswith("https://flight.naver.com/flights/international/")
    assert "CJJ:airport-TPE:airport-20260918" in url
    assert "TPE:airport-CJJ:airport-20260920" in url
    assert "adult=1" in url
    assert "fareType=Y" in url
    assert "isDirect=true" in url


def test_naver_api_payload_matches_verified_direct_round_trip_shape():
    payload = build_payload("CJJ", "TPE", "2026-09-18", "2026-09-20")
    assert payload["adultCount"] == 1
    assert payload["isNonstop"] is True
    assert payload["seatClass"] == "Y"
    assert payload["tripType"] == "RT"
    assert payload["itineraries"][0]["departureLocationCode"] == "CJJ"
    assert payload["itineraries"][0]["arrivalLocationCode"] == "TPE"
    assert payload["itineraries"][0]["departureDate"] == "20260918"
    assert payload["itineraries"][1]["departureLocationCode"] == "TPE"
    assert payload["itineraries"][1]["arrivalLocationCode"] == "CJJ"
    assert payload["itineraries"][1]["departureDate"] == "20260920"
    assert payload["flightFilter"]["sort"] == {"adultMinFare": 1}


def _fixture_payload(price: int = 319620, *, completed: bool = True) -> dict:
    return {
        "status": {
            "isCompleted": completed,
            "lowestFare": {"direct": price},
            "airlinesCodeMap": {"ZE": "이스타항공", "RF": "에어로케이"},
        },
        "itineraries": [
            {
                "itineraryId": "OUT-1",
                "duration": 9000,
                "segments": [
                    {
                        "departure": {"airportCode": "CJJ", "date": "20260918", "time": "2340"},
                        "arrival": {"airportCode": "TPE", "date": "20260919", "time": "0110"},
                        "marketingCarrier": {"airlineCode": "ZE", "flightNumber": "781"},
                    }
                ],
            },
            {
                "itineraryId": "RET-1",
                "duration": 8700,
                "segments": [
                    {
                        "departure": {"airportCode": "TPE", "date": "20260920", "time": "1315"},
                        "arrival": {"airportCode": "CJJ", "date": "20260920", "time": "1640"},
                        "marketingCarrier": {"airlineCode": "RF", "flightNumber": "322"},
                    }
                ],
            },
        ],
        "fareMappings": [
            {
                "itineraryIds": "OUT-1-RET-1",
                "fares": [
                    {
                        "partnerCode": "TEST",
                        "fareType": "A01",
                        "adult": {"totalFare": price},
                        "isConfirmed": True,
                    }
                ],
            }
        ],
    }


def test_sse_parser_prefers_completed_payload_with_more_real_data():
    import json

    incomplete = _fixture_payload(350000, completed=False)
    complete = _fixture_payload(319620, completed=True)
    text = "\n".join(
        [
            "event: message",
            "data: " + json.dumps(incomplete, ensure_ascii=False),
            "",
            "data: " + json.dumps(complete, ensure_ascii=False),
        ]
    )
    selected = select_best_payload(parse_sse_events(text))
    assert selected is not None
    assert selected["status"]["lowestFare"]["direct"] == 319620


def test_payload_builds_named_round_trip_row_even_when_itinerary_ids_have_hyphens():
    rows = rows_from_payload(_fixture_payload())
    assert len(rows) == 1
    row = rows[0]
    assert row["price"] == 319620
    assert row["times"] == ["23:40", "01:10", "13:15", "16:40"]
    assert row["outbound_flight"] == "ZE781"
    assert row["return_flight"] == "RF322"
    assert row["outbound_airline"] == "이스타항공"
    assert row["return_airline"] == "에어로케이"
    assert row["nonstop"] is True


def test_same_flight_pair_keeps_cheapest_seller_fare():
    payload = _fixture_payload(330000)
    payload["fareMappings"][0]["fares"].append(
        {
            "partnerCode": "CHEAPER",
            "fareType": "A01",
            "adult": {"totalFare": 319620},
            "isConfirmed": True,
        }
    )
    rows = rows_from_payload(payload)
    assert len(rows) == 1
    assert rows[0]["price"] == 319620
    assert rows[0]["partner_code"] == "CHEAPER"


def test_connection_itinerary_is_rejected_in_direct_only_product():
    payload = _fixture_payload()
    payload["itineraries"][0]["segments"].append(
        {
            "departure": {"airportCode": "XXX", "date": "20260918", "time": "1200"},
            "arrival": {"airportCode": "TPE", "date": "20260918", "time": "1300"},
            "marketingCarrier": {"airlineCode": "ZE", "flightNumber": "999"},
        }
    )
    assert rows_from_payload(payload) == []
