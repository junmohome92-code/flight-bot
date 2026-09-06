from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "flight-bot - test win"
SCRIPTS = ROOT / "scripts"


def test_google_msedge_probe_is_one_click_and_uses_production_provider():
    bat = (WIN / "04-test-google-msedge.cmd").read_text(encoding="utf-8")
    script = (SCRIPTS / "google_msedge_probe.py").read_text(encoding="utf-8")

    assert "google_msedge_probe.py" in bat
    assert 'channel="msedge"' in script
    assert "RuntimeGoogleResultsProvider" in script
    assert "QUERY_CONTRACT" in script
    assert "booking_navigation=NO" in script


def test_naver_probe_uses_direct_results_url_and_never_opens_detail_or_booking():
    bat = (WIN / "05-test-naver-flights.cmd").read_text(encoding="utf-8")
    script = (SCRIPTS / "naver_flights_probe.py").read_text(encoding="utf-8")

    assert "naver_flights_probe.py" in bat
    assert 'channel="msedge"' in script
    assert "CJJ:airport-TPE:airport-20260918" in script
    assert "TPE:airport-CJJ:airport-20260920" in script
    assert "isDirect=true" in script
    assert "/international/detail/" not in script
    assert "booking_navigation_performed=False" in script
    assert ".click(" not in script
