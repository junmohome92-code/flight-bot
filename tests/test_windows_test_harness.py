from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "flight-bot - test win"
SCRIPTS = ROOT / "scripts"


def test_windows_has_two_independent_provider_launchers():
    naver = (WIN / "02-NAVER-flight-test.bat").read_text(encoding="utf-8")
    sky = (WIN / "03-SKYSCANNER-flight-test.bat").read_text(encoding="utf-8")

    assert "scripts\\naver_flight_probe.py" in naver
    assert "scripts\\skyscanner_flight_probe.py" in sky
    assert "skyscanner_flight_probe.py" not in naver
    assert "naver_flight_probe.py" not in sky


def test_windows_provider_launchers_self_bootstrap_isolated_venv():
    for name in ("02-NAVER-flight-test.bat", "03-SKYSCANNER-flight-test.bat"):
        launcher = (WIN / name).read_text(encoding="utf-8")
        assert ".venv-provider-poc\\Scripts\\python.exe" in launcher
        assert "setup-and-unit-test.ps1" in launcher
        assert ".venv-win\\Scripts\\python.exe" not in launcher

    setup = (WIN / "setup-and-unit-test.ps1").read_text(encoding="utf-8")
    assert ".venv-provider-poc" in setup
    assert "provider-poc-requirements.txt" in setup
    assert "-e '.[dev]'" not in setup


def test_retired_google_windows_launchers_are_absent():
    assert not (WIN / "02-live-cjj-tpe-visible.cmd").exists()
    assert not (WIN / "03-notification-test-menu.cmd").exists()
    assert not (WIN / "live-cjj-tpe.ps1").exists()
    assert not (WIN / "notification-test-menu.ps1").exists()


def test_provider_pocs_stop_at_results_page():
    naver = (SCRIPTS / "naver_flight_probe.py").read_text(encoding="utf-8")
    sky = (SCRIPTS / "skyscanner_flight_probe.py").read_text(encoding="utf-8")

    for source in (naver, sky):
        assert "booking_navigation=False" in source
        assert "booking_navigation_performed=False" in source
        assert "checkout" not in source.lower()


def test_legacy_google_probe_scripts_are_absent():
    assert not list(SCRIPTS.glob("google_*"))
