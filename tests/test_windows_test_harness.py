from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "flight-bot - test win"
SCRIPTS = ROOT / "scripts"


def test_windows_has_naver_and_telegram_launchers():
    naver = (WIN / "02-NAVER-flight-test.bat").read_text(encoding="utf-8")
    e2e = (WIN / "03-NAVER-TELEGRAM-E2E.bat").read_text(encoding="utf-8")

    assert "scripts\\naver_flight_probe.py" in naver
    assert "scripts\\naver_telegram_e2e.py" in e2e
    assert "skyscanner" not in naver.lower()
    assert "skyscanner" not in e2e.lower()


def test_windows_launchers_self_bootstrap_isolated_venv():
    for name in ("02-NAVER-flight-test.bat", "03-NAVER-TELEGRAM-E2E.bat"):
        launcher = (WIN / name).read_text(encoding="utf-8")
        assert ".venv-provider-poc\\Scripts\\python.exe" in launcher
        assert "setup-and-unit-test.ps1" in launcher
        assert ".venv-win\\Scripts\\python.exe" not in launcher

    setup = (WIN / "setup-and-unit-test.ps1").read_text(encoding="utf-8")
    assert ".venv-provider-poc" in setup
    assert "provider-poc-requirements.txt" in setup
    assert "-e '.[dev]'" not in setup


def test_telegram_e2e_uses_dedicated_credential_file():
    launcher = (WIN / "03-NAVER-TELEGRAM-E2E.bat").read_text(encoding="utf-8")
    template = (WIN / "telegram-test.env.example").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "telegram-test.env.example" in launcher
    assert "telegram-test.env" in launcher
    assert "TELEGRAM_BOT_TOKEN=" in template
    assert "TELEGRAM_ALLOWED_CHAT_IDS=" in template
    assert "flight-bot - test win/telegram-test.env" in gitignore


def test_e2e_searches_before_it_sends_telegram():
    source = (SCRIPTS / "naver_telegram_e2e.py").read_text(encoding="utf-8")
    search_pos = source.index("await collect_naver_visible_results")
    send_pos = source.index('"sendMessage"')
    assert search_pos < send_pos
    assert "booking_navigation_performed=False" in source


def test_retired_provider_assets_are_absent():
    assert not list(SCRIPTS.glob("google_*"))
    assert not list(SCRIPTS.glob("skyscanner_*"))
    assert not list((ROOT / "tests").glob("test_google_*"))
    assert not (WIN / "02-live-cjj-tpe-visible.cmd").exists()
    assert not (WIN / "03-notification-test-menu.cmd").exists()
    assert not (WIN / "03-SKYSCANNER-flight-test.bat").exists()
    assert not (WIN / "live-cjj-tpe.ps1").exists()
    assert not (WIN / "notification-test-menu.ps1").exists()


def test_naver_poc_stops_at_results_page():
    source = (SCRIPTS / "naver_flight_probe.py").read_text(encoding="utf-8")
    assert "booking_navigation=False" in source
    assert "booking_navigation_performed=False" in source
    assert "checkout" not in source.lower()
