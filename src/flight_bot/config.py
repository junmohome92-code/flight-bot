from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"
    http_port: int = 8080
    database_path: str = "/data/flight_bot.db"
    timezone: str = "Asia/Seoul"
    check_hours: str = "8,20"

    # Google Flights / Playwright
    browser_headless: bool = True
    browser_timeout_ms: int = 45_000
    browser_block_assets: bool = True
    browser_debug_dir: str = ""
    browser_profile_dir: str = ""
    google_language: str = "en"
    google_currency: str = "KRW"
    google_gl: str = "kr"

    # Product alert policy.
    # Alerts are based on the prices Google Flights actually displays on the
    # round-trip result page. Checkout/OTA verification is intentionally not
    # required for the current product scope.
    require_verified_alerts: bool = False
    alert_nonstop_only: bool = True
    alert_max_offers: int = Field(default=4, ge=1, le=10)

    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""

    discord_bot_token: str = ""
    discord_allowed_channel_ids: str = ""

    kakao_skill_secret: str = ""
    kakao_allowed_user_ids: str = ""

    admin_secret: str = ""

    @staticmethod
    def _csv_set(value: str) -> set[str]:
        return {item.strip() for item in value.split(",") if item.strip()}

    @property
    def telegram_chat_ids(self) -> set[str]:
        return self._csv_set(self.telegram_allowed_chat_ids)

    @property
    def discord_channel_ids(self) -> set[str]:
        return self._csv_set(self.discord_allowed_channel_ids)

    @property
    def kakao_user_ids(self) -> set[str]:
        return self._csv_set(self.kakao_allowed_user_ids)

    @property
    def scheduled_hours(self) -> list[int]:
        try:
            hours = sorted({int(x.strip()) for x in self.check_hours.split(",") if x.strip()})
        except ValueError as exc:
            raise ValueError("CHECK_HOURS must be comma-separated integers 0-23") from exc
        if any(hour < 0 or hour > 23 for hour in hours):
            raise ValueError("CHECK_HOURS must contain 0-23 only")
        return hours

    def runtime_security_errors(self) -> list[str]:
        """Return unsafe production channel combinations.

        Bot credentials without allowlists are fail-open by nature. Production
        startup rejects those combinations instead of silently exposing all
        commands to anyone who can reach the bot/channel.
        """
        if self.app_env.lower() != "production":
            return []
        errors: list[str] = []
        if self.telegram_bot_token and not self.telegram_chat_ids:
            errors.append("TELEGRAM_BOT_TOKEN requires TELEGRAM_ALLOWED_CHAT_IDS in production")
        if self.discord_bot_token and not self.discord_channel_ids:
            errors.append("DISCORD_BOT_TOKEN requires DISCORD_ALLOWED_CHANNEL_IDS in production")
        if self.kakao_skill_secret and not self.kakao_user_ids:
            errors.append("KAKAO_SKILL_SECRET requires KAKAO_ALLOWED_USER_IDS in production")
        if self.kakao_user_ids and not self.kakao_skill_secret:
            errors.append("KAKAO_ALLOWED_USER_IDS requires KAKAO_SKILL_SECRET")
        return errors

    def validate_runtime_security(self) -> None:
        errors = self.runtime_security_errors()
        if errors:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()
