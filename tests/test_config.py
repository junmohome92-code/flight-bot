import pytest
from pydantic import ValidationError

from flight_bot.config import CURRENT_SLOT_LIMIT, SLOT_DESIGN_CAPACITY, Settings


def test_default_search_cadence_naver_policy_and_slot_policy():
    settings = Settings(_env_file=None)
    assert settings.search_interval_hours == 2
    assert settings.scheduled_search_hours == list(range(0, 24, 2))
    assert settings.daily_summary_hour == 8
    assert settings.slot_active_limit == 10
    assert CURRENT_SLOT_LIMIT == 10
    assert SLOT_DESIGN_CAPACITY == 10
    assert settings.naver_api_url.endswith("/flight/international/searchFlights")
    assert settings.naver_api_timeout_seconds == 30
    assert settings.naver_api_attempts == 3
    assert settings.naver_min_request_interval_seconds == 3.0
    assert settings.alert_nonstop_only is True
    assert settings.alert_max_offers == 5
    assert settings.require_verified_alerts is False


def test_runtime_slot_limit_can_be_lowered_but_not_exceed_ten():
    assert Settings(_env_file=None, slot_active_limit=5).slot_active_limit == 5
    assert Settings(_env_file=None, slot_active_limit=10).slot_active_limit == 10
    with pytest.raises(ValidationError):
        Settings(_env_file=None, slot_active_limit=11)


def test_naver_runtime_limits_are_validated():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, naver_api_timeout_seconds=2)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, naver_api_attempts=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, alert_max_offers=11)


def test_daily_summary_hour_must_reuse_a_scheduled_search():
    settings = Settings(_env_file=None, search_interval_hours=2, daily_summary_hour=9)
    with pytest.raises(RuntimeError, match="DAILY_SUMMARY_HOUR"):
        settings.validate_runtime_security()


def test_production_token_requires_allowlist():
    settings = Settings(
        _env_file=None,
        app_env="production",
        telegram_bot_token="secret",
        telegram_allowed_chat_ids="",
    )
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
        settings.validate_runtime_security()


def test_production_discord_token_requires_allowlist():
    settings = Settings(
        _env_file=None,
        app_env="production",
        discord_bot_token="secret",
        discord_allowed_channel_ids="",
    )
    with pytest.raises(RuntimeError, match="DISCORD_ALLOWED_CHANNEL_IDS"):
        settings.validate_runtime_security()


def test_kakao_secret_and_allowlist_must_be_paired():
    settings = Settings(_env_file=None, app_env="production", kakao_skill_secret="secret", kakao_allowed_user_ids="")
    assert settings.runtime_security_errors()
    settings = Settings(_env_file=None, app_env="production", kakao_skill_secret="", kakao_allowed_user_ids="user")
    assert settings.runtime_security_errors()


def test_development_can_use_open_channel_configuration_for_local_testing():
    settings = Settings(_env_file=None, app_env="development", telegram_bot_token="secret")
    settings.validate_runtime_security()


def test_valid_production_channel_configuration_passes():
    settings = Settings(
        _env_file=None,
        app_env="production",
        telegram_bot_token="secret",
        telegram_allowed_chat_ids="123",
        discord_bot_token="secret",
        discord_allowed_channel_ids="456",
        kakao_skill_secret="secret",
        kakao_allowed_user_ids="user",
    )
    settings.validate_runtime_security()
