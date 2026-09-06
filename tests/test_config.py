import pytest
from pydantic import ValidationError

from flight_bot.config import CURRENT_SLOT_LIMIT, SLOT_DESIGN_CAPACITY, Settings


def test_default_search_cadence_daily_summary_and_slot_policy():
    settings = Settings()
    assert settings.search_interval_hours == 2
    assert settings.scheduled_search_hours == list(range(0, 24, 2))
    assert settings.daily_summary_hour == 8
    assert settings.slot_active_limit == 10
    assert CURRENT_SLOT_LIMIT == 10
    assert SLOT_DESIGN_CAPACITY == 10


def test_runtime_slot_limit_can_be_lowered_but_not_exceed_ten():
    assert Settings(slot_active_limit=5).slot_active_limit == 5
    assert Settings(slot_active_limit=10).slot_active_limit == 10
    with pytest.raises(ValidationError):
        Settings(slot_active_limit=11)


def test_daily_summary_hour_must_reuse_a_scheduled_search():
    settings = Settings(search_interval_hours=2, daily_summary_hour=9)
    with pytest.raises(RuntimeError, match="DAILY_SUMMARY_HOUR"):
        settings.validate_runtime_security()


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
