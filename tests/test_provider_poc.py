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


def test_naver_poc_url_is_direct_round_trip_search():
    url = NAVER.build_naver_url("CJJ", "TPE", "2026-09-18", "2026-09-20")
    assert url.startswith("https://flight.naver.com/flights/international/")
    assert "CJJ:airport-TPE:airport-20260918" in url
    assert "TPE:airport-CJJ:airport-20260920" in url
    assert "adult=1" in url
    assert "fareType=Y" in url
    assert "isDirect=true" in url


def test_naver_extractor_is_semantic_and_diagnostic():
    source = NAVER._COLLECT_ROWS_JS
    assert "price_anchors" in source
    assert "allElements" in source
    assert "round_trip_evidence" in source
    assert "body-wide" not in source.lower()


def test_naver_probe_collects_every_frame_and_saves_diagnostics():
    source = (ROOT / "scripts/naver_flight_probe.py").read_text(encoding="utf-8")
    assert "for index, frame in enumerate(page.frames)" in source
    assert 'artifact_dir / "diagnostics.json"' in source
    assert 'artifact_dir / "page.html"' in source
