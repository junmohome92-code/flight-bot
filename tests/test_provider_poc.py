from scripts.naver_flight_probe import build_naver_url
from scripts.skyscanner_flight_probe import build_skyscanner_url


def test_naver_poc_url_is_direct_round_trip_search():
    url = build_naver_url("CJJ", "TPE", "2026-09-18", "2026-09-20")
    assert url.startswith("https://flight.naver.com/flights/international/")
    assert "CJJ%" not in url  # path remains human-readable, not query encoded
    assert "CJJ:airport-TPE:airport-20260918" in url
    assert "TPE:airport-CJJ:airport-20260920" in url
    assert "adult=1" in url
    assert "fareType=Y" in url
    assert "isDirect=true" in url


def test_skyscanner_poc_url_is_direct_round_trip_search():
    url = build_skyscanner_url("CJJ", "TPE", "2026-09-18", "2026-09-20")
    assert url.startswith("https://www.skyscanner.co.kr/transport/flights/cjj/tpe/260918/260920/")
    assert "adultsv2=1" in url
    assert "cabinclass=economy" in url
    assert "preferdirects=true" in url
    assert "stops=direct" in url


def test_provider_pocs_are_independent_modules():
    assert build_naver_url is not build_skyscanner_url
