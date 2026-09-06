from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "flight-bot - test win"


def test_notification_menu_is_ascii_only_for_windows_powershell_51():
    data = (WIN / "notification-test-menu.ps1").read_bytes()
    assert all(byte < 128 for byte in data), (
        "notification-test-menu.ps1 must stay ASCII-only because Windows "
        "PowerShell 5.1 misdecodes BOM-less UTF-8 source files"
    )


def test_notification_launcher_points_to_single_canonical_menu():
    cmd = (WIN / "03-notification-test-menu.cmd").read_text(encoding="utf-8")
    assert "notification-test-menu.ps1" in cmd
    assert "notification-test-menu-v2.ps1" not in cmd
    assert not (WIN / "notification-test-menu-v2.ps1").exists()


def test_docker_pins_container_specific_browser_and_storage_settings():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "DATABASE_PATH: /data/flight_bot.db" in compose
    assert 'BROWSER_HEADLESS: "true"' in compose
    assert "BROWSER_DEBUG_DIR: /debug" in compose
