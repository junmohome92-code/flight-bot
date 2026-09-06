import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


NAVER = _load("naver_flight_probe", "scripts/naver_flight_probe.py")


def test_naver_result_url_is_direct_round_trip_search():
    url = NAVER.build_naver_url("CJJ", "TPE", "2026-09-18", "2026-09-20")
    assert url.startswith("https://flight.naver.com/flights/international/")
    assert "CJJ:airport-TPE:airport-20260918" in url
    assert "TPE:airport-CJJ:airport-20260920" in url
    assert "adult=1" in url
    assert "fareType=Y" in url
    assert "isDirect=true" in url


def test_naver_api_payload_matches_verified_direct_round_trip_shape():
    payload = NAVER.build_naver_api_payload("CJJ", "TPE", "2026-09-18", "2026-09-20")
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


def _fixture_payload(price: int = 319620) -> dict:
    return {
        "status": {"isCompleted": True, "lowestFare": {"direct": price}},
        "itineraries": [
            {
                "itineraryId": "OUT1",
                "duration": 9000,
                "segments": [
                    {
                        "departure": {"airportCode": "CJJ", "date": "20260918", "time": "0305"},
                        "arrival": {"airportCode": "TPE", "date": "20260918", "time": "0440"},
                        "marketingCarrier": {"airlineCode": "ZE", "flightNumber": "781"},
                    }
                ],
            },
            {
                "itineraryId": "RET1",
                "duration": 9000,
                "segments": [
                    {
                        "departure": {"airportCode": "TPE", "date": "20260920", "time": "1950"},
                        "arrival": {"airportCode": "CJJ", "date": "20260920", "time": "2320"},
                        "marketingCarrier": {"airlineCode": "ZE", "flightNumber": "782"},
                    }
                ],
            },
        ],
        "fareMappings": [
            {
                "itineraryIds": "OUT1-RET1",
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


def test_naver_sse_parser_prefers_completed_valid_payload():
    incomplete = _fixture_payload(350000)
    incomplete["status"]["isCompleted"] = False
    complete = _fixture_payload(319620)
    text = "\n".join(
        [
            "event: message",
            "data: " + __import__("json").dumps(incomplete),
            "",
            "data: " + __import__("json").dumps(complete),
        ]
    )
    events = NAVER._parse_sse_events(text)
    selected = NAVER._select_api_payload(events)
    assert selected is not None
    assert selected["status"]["lowestFare"]["direct"] == 319620


def test_naver_api_payload_builds_round_trip_rows():
    rows = NAVER._rows_from_payload(_fixture_payload())
    assert len(rows) == 1
    row = rows[0]
    assert row["price"] == 319620
    assert row["times"] == ["03:05", "04:40", "19:50", "23:20"]
    assert row["outbound_flight"] == "ZE781"
    assert row["return_flight"] == "ZE782"
    assert row["partner_code"] == "TEST"


def test_naver_probe_saves_sse_diagnostics_not_browser_dom_artifacts():
    source = (ROOT / "scripts/naver_flight_probe.py").read_text(encoding="utf-8")
    assert "text/event-stream" in source
    assert 'artifact_dir / "response.sse.txt"' in source
    assert 'artifact_dir / "response.json"' in source
    assert 'artifact_dir / "diagnostics.json"' in source
    assert 'artifact_dir / "result.json"' in source
    assert "page.frames" not in source
    assert "querySelector" not in source
