from flight_bot.google_query import QUERY_CONTRACT, build_google_flights_search_url, build_tfs_token


EXPECTED_TOKEN = (
    "CBwQAhoeEgoyMDI2LTA5LTE4agcIARIDQ0pKcgcIARIDVFBFGh4SCjIwMjYtMDktMjBqBwgBEgNUUEVyBwgBEgNDSkpAAUgBcAGCAQsI____________AZgBAQ"
)
EXPECTED_URL = (
    "https://www.google.com/travel/flights/search?"
    f"tfs={EXPECTED_TOKEN}&hl=en&gl=kr&curr=KRW"
)


def test_cjj_tpe_token_exactly_matches_live_accepted_probe():
    assert QUERY_CONTRACT == "accepted-tfs-v1"
    assert build_tfs_token(
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
    ) == EXPECTED_TOKEN


def test_production_url_exactly_matches_live_accepted_probe():
    assert build_google_flights_search_url(
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        language="en",
        gl="kr",
        currency="KRW",
    ) == EXPECTED_URL


def test_query_builder_changes_route_and_dates_without_fast_flights():
    url = build_google_flights_search_url(
        origin="ICN",
        destination="NRT",
        depart_date="2026-10-01",
        return_date="2026-10-03",
    )
    assert url.startswith("https://www.google.com/travel/flights/search?tfs=")
    assert url.endswith("&hl=en&gl=kr&curr=KRW")
    assert url != EXPECTED_URL
