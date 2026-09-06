from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


SLOT_DESIGN_CAPACITY = 10


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"
    http_port: int = 8080
    database_path: str = "/data/flight_bot.db"
    timezone: str = "Asia/Seoul"

    # Runtime cadence. Price scans happen every N hours; only one of those
    # scans per day also emits the regular price summary.
    search_interval_hours: int = Field(default=2, ge=1, le=24)
    daily_summary_hour: int = Field(default=8, ge=0, le=23)

    # The storage/domain layout is intentionally safe up to ten fixed IDs, but
    # the current product release exposes only five active slots. Raising this
    # later does not require a DB schema migration.
    slot_active_limit: int = Field(default=5, ge=1, le=SLOT_DESIGN_CAPACITY)

    # Google Flights / Playwright
    browser_headless: bool = True
    browser_timeout_ms: int = 45_000
    browser_block_assets: bool = True
    browser_debug_dir: str = ""
    # Kept for config compatibility only. Runtime price searches use an
    # isolated BrowserContext per search so cookies/cache/site storage do not
    # carry over between two-hour observations.
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
    def scheduled_search_hours(self) -> list[int]:
        """Return deterministic wall-clock search hours for the configured cadence.

        The default is every two hours: 00,02,...,22. The daily summary hour
        must be one of those search hours so the summary can reuse that scan
        instead of creating an extra Google request.
        """
        return list(range(0, 24, self.search_interval_hours))

    def runtime_security_errors(self) -> list[str]:
        """Return unsafe production channel combinations."""
        errors: list[str] = []
        if self.daily_summary_hour not in self.scheduled_search_hours:
            errors.append(
                "DAILY_SUMMARY_HOUR must align with SEARCH_INTERVAL_HOURS so the daily summary reuses a scheduled scan"
            )
        if self.app_env.lower() != "production":
            return errors
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
