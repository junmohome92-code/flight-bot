from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "flight-bot - test win"
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src" / "flight_bot"


def test_windows_has_naver_and_telegram_launchers():
    naver = (WIN / "02-NAVER-flight-test.bat").read_text(encoding="utf-8")
    e2e = (WIN / "03-NAVER-TELEGRAM-E2E.bat").read_text(encoding="utf-8")

    assert "scripts\\naver_flight_probe.py" in naver
    assert "scripts\\naver_telegram_e2e.py" in e2e
    assert "no browser" in naver.lower()
    assert "no browser" in e2e.lower()
    assert "edge" not in e2e.lower()


def test_windows_launchers_self_bootstrap_isolated_venv():
    for name in ("02-NAVER-flight-test.bat", "03-NAVER-TELEGRAM-E2E.bat"):
        launcher = (WIN / name).read_text(encoding="utf-8")
        assert ".venv-provider-poc\\Scripts\\python.exe" in launcher
        assert "setup-and-unit-test.ps1" in launcher

    setup = (WIN / "setup-and-unit-test.ps1").read_text(encoding="utf-8")
    assert ".venv-provider-poc" in setup
    assert "windows-test-requirements.txt" in setup


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
    search_pos = source.index("await collect_naver_api_results")
    send_pos = source.index('"sendMessage"')
    assert search_pos < send_pos
    assert "TOP 5" in source


def test_retired_browser_assets_are_absent():
    assert not (SRC / "browser_session.py").exists()
    assert not (SRC / "runtime_results_provider.py").exists()
    assert not (SRC / "google_ui_contract.py").exists()
    assert not list(SCRIPTS.glob("google_*"))
    assert not list(SCRIPTS.glob("*edge*"))
    assert not list((ROOT / "tests").glob("test_google_*"))
    assert not (WIN / "02A-NAVER-API-SSE-test.bat").exists()


def test_runtime_has_no_browser_automation_dependency():
    runtime = "\n".join(path.read_text(encoding="utf-8").lower() for path in SRC.glob("*.py"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8").lower()
    assert "playwright" not in runtime
    assert "playwright" not in pyproject
    assert "playwright" not in dockerfile
    assert "chromium" not in dockerfile
