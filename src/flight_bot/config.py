from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"
    http_port: int = 8080
    database_path: str = "/data/flight_bot.db"
    timezone: str = "Asia/Seoul"
    check_hours: str = "8,20"
    max_slots: int = 3
    cache_minutes: int = 20

    # Preferred: comma-separated N keys. The legacy single-key variable remains
    # supported so a one-key test deployment can be upgraded without code changes.
    serpapi_api_keys: str = ""
    serpapi_api_key: str = ""
    serpapi_base_url: str = "https://serpapi.com/search.json"

    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4.1-mini"

    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""

    discord_bot_token: str = ""
    discord_guild_id: str = ""
    discord_allowed_channel_ids: str = ""

    kakao_skill_secret: str = ""
    kakao_allowed_user_ids: str = ""

    @staticmethod
    def _csv_set(value: str) -> set[str]:
        return {item.strip() for item in value.split(",") if item.strip()}

    @staticmethod
    def _csv_list(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def serpapi_keys(self) -> list[str]:
        keys = self._csv_list(self.serpapi_api_keys)
        if not keys and self.serpapi_api_key.strip():
            keys = [self.serpapi_api_key.strip()]
        # Preserve order while silently removing duplicate keys.
        return list(dict.fromkeys(keys))

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
        return sorted({int(x.strip()) for x in self.check_hours.split(",") if x.strip()})


@lru_cache
def get_settings() -> Settings:
    return Settings()
