import importlib
import sys

from fastapi.testclient import TestClient


def test_http_endpoints_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite"))
    monkeypatch.setenv("ADMIN_SECRET", "admin-secret")
    monkeypatch.setenv("KAKAO_SKILL_SECRET", "kakao-secret")
    monkeypatch.setenv("KAKAO_ALLOWED_USER_IDS", "allowed-user")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    import flight_bot.config as config

    config.get_settings.cache_clear()
    sys.modules.pop("flight_bot.__main__", None)
    runtime = importlib.import_module("flight_bot.__main__")

    async def fake_search_now(origin, destination, depart_date, return_date):
        return f"SEARCH {origin}->{destination} {depart_date}~{return_date}"

    async def fake_check_slot(slot_id, *, notify_target=False, notify_daily_summary=False):
        return f"SLOT {slot_id} target={notify_target} daily={notify_daily_summary}"

    async def fake_check_all(*, notify_target=True, notify_daily_summary=False):
        return True

    async def fake_command(platform, owner_id, text):
        return f"CMD {platform} {owner_id} {text}"

    monkeypatch.setattr(runtime.service, "search_now", fake_search_now)
    monkeypatch.setattr(runtime.service, "check_slot", fake_check_slot)
    monkeypatch.setattr(runtime.service, "check_all", fake_check_all)
    monkeypatch.setattr(runtime.service, "command", fake_command)

    headers = {"X-Flight-Bot-Secret": "admin-secret"}

    with TestClient(runtime.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["ok"] is True
        assert body["version"] == "0.6.0"
        assert body["provider"] == "naver-flights-sse"
        assert body["browser_required"] is False
        assert body["slots_max"] == 20
        assert body["slot_limit_scope"] == "per-conversation"
        assert body["slots_design_capacity"] == 20
        assert body["ad_hoc_search_enabled"] is True
        assert body["city_search_enabled"] is True
        assert body["worldwide_location_search_enabled"] is True
        assert body["multilingual_location_search_enabled"] is True
        assert body["iata_validation_enabled"] is True
        assert body["daily_summary_mode"] == "one-message-per-conversation"

        unauthorized = client.post("/admin/check-all")
        assert unauthorized.status_code == 401

        search = client.post(
            "/admin/search",
            params={
                "origin": "CJJ",
                "destination": "TPE",
                "depart_date": "2026-09-18",
                "return_date": "2026-09-20",
            },
            headers=headers,
        )
        assert search.status_code == 200
        assert search.json()["persisted"] is False
        assert "SEARCH CJJ->TPE" in search.json()["result"]

        city_search = client.post(
            "/admin/search",
            params={
                "origin": "SEL",
                "destination": "TYO",
                "depart_date": "2026-09-22",
                "return_date": "2026-09-24",
            },
            headers=headers,
        )
        assert city_search.status_code == 200
        assert "SEARCH SEL->TYO" in city_search.json()["result"]

        check_all = client.post("/admin/check-all", headers=headers)
        assert check_all.status_code == 200
        assert check_all.json()["mode"] == "target-check-all"

        daily_all = client.post("/admin/daily-summary", headers=headers)
        assert daily_all.status_code == 200
        assert daily_all.json()["mode"] == "daily-summary-all"
        assert daily_all.json()["summary_mode"] == "one-message-per-conversation"
        assert daily_all.json()["target_alerts"] is False

        check_slot = client.post("/admin/check-slot/7", headers=headers)
        assert check_slot.status_code == 200
        assert check_slot.json()["slot_id"] == 7
        assert "target=True" in check_slot.json()["result"]

        daily_slot = client.post("/admin/daily-summary/7", headers=headers)
        assert daily_slot.status_code == 200
        assert daily_slot.json()["slot_id"] == 7
        assert "daily=True" in daily_slot.json()["result"]

        kakao_unauthorized = client.post(
            "/kakao/skill",
            json={"userRequest": {"utterance": "/?", "user": {"id": "allowed-user"}}},
        )
        assert kakao_unauthorized.status_code == 401

        kakao_allowed = client.post(
            "/kakao/skill",
            headers={"X-Flight-Bot-Secret": "kakao-secret"},
            json={"userRequest": {"utterance": "/?", "user": {"id": "allowed-user"}}},
        )
        assert kakao_allowed.status_code == 200
        assert "CMD kakao allowed-user /?" in str(kakao_allowed.json())

        kakao_denied_user = client.post(
            "/kakao/skill",
            headers={"X-Flight-Bot-Secret": "kakao-secret"},
            json={"userRequest": {"utterance": "/?", "user": {"id": "other-user"}}},
        )
        assert kakao_denied_user.status_code == 200
        assert "허용되지 않은 사용자" in str(kakao_denied_user.json())

    config.get_settings.cache_clear()
