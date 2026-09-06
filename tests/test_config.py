import pytest

from flight_bot.config import Settings


def test_production_token_requires_allowlist():
    settings = Settings(app_env="production", telegram_bot_token="secret", telegram_allowed_chat_ids="")
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
        settings.validate_runtime_security()


def test_production_discord_token_requires_allowlist():
    settings = Settings(app_env="production", discord_bot_token="secret", discord_allowed_channel_ids="")
    with pytest.raises(RuntimeError, match="DISCORD_ALLOWED_CHANNEL_IDS"):
        settings.validate_runtime_security()


def test_kakao_secret_and_allowlist_must_be_paired():
    settings = Settings(app_env="production", kakao_skill_secret="secret", kakao_allowed_user_ids="")
    assert settings.runtime_security_errors()
    settings = Settings(app_env="production", kakao_skill_secret="", kakao_allowed_user_ids="user")
    assert settings.runtime_security_errors()


def test_development_can_use_open_channel_configuration_for_local_testing():
    settings = Settings(app_env="development", telegram_bot_token="secret")
    settings.validate_runtime_security()


def test_valid_production_channel_configuration_passes():
    settings = Settings(
        app_env="production",
        telegram_bot_token="secret",
        telegram_allowed_chat_ids="123",
        discord_bot_token="secret",
        discord_allowed_channel_ids="456",
        kakao_skill_secret="secret",
        kakao_allowed_user_ids="user",
    )
    settings.validate_runtime_security()
