from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_install_script_and_env_defaults_are_user_friendly():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "docker compose config" in install
    assert "docker compose up -d --build" in install
    assert "SLOT_ACTIVE_LIMIT=20" in env
    assert "TELEGRAM_BOT_TOKEN=" in env
    assert "TELEGRAM_ALLOWED_CHAT_IDS=" in env
    assert "restart: unless-stopped" in compose
    assert "flight_bot_data:/data" in compose
