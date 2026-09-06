import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NAVER = _load("naver_flight_probe", "scripts/naver_flight_probe.py")
SKY = _load("skyscanner_flight_probe", "scripts/skyscanner_flight_probe.py")


def test_naver_poc_url_is_direct_round_trip_search():
    url = NAVER.build_naver_url("CJJ", "TPE", "2026-09-18", "2026-09-20")
    assert url.startswith("https://flight.naver.com/flights/international/")
    assert "CJJ:airport-TPE:airport-20260918" in url
    assert "TPE:airport-CJJ:airport-20260920" in url
    assert "adult=1" in url
    assert "fareType=Y" in url
    assert "isDirect=true" in url


def test_skyscanner_poc_url_is_direct_round_trip_search():
    url = SKY.build_skyscanner_url("CJJ", "TPE", "2026-09-18", "2026-09-20")
    assert url.startswith("https://www.skyscanner.co.kr/transport/flights/cjj/tpe/260918/260920/")
    assert "adultsv2=1" in url
    assert "cabinclass=economy" in url
    assert "preferdirects=true" in url
    assert "stops=direct" in url


def test_provider_pocs_are_independent_modules():
    assert NAVER.build_naver_url is not SKY.build_skyscanner_url
