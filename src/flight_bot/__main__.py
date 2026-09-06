from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Header, HTTPException, Request

from .channels import MultiNotifier, build_telegram, start_discord
from .config import SLOT_DESIGN_CAPACITY, get_settings
from .db import Database
from .service import FlightService

settings = get_settings()
db = Database(settings.database_path, slot_limit=settings.slot_active_limit)
service = FlightService(settings, db)
notifier = MultiNotifier()
service.set_notifier(notifier)
scheduler = AsyncIOScheduler(timezone=settings.timezone)
telegram_app = None
discord_client = None


def kakao_response(text: str) -> dict:
    return {"version": "2.0", "template": {"outputs": [{"simpleText": {"text": text[:1000]}}]}}


def _secret_matches(expected: str, supplied: str | None) -> bool:
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def _require_admin(supplied: str | None) -> None:
    if not settings.admin_secret:
        raise HTTPException(status_code=404, detail="admin endpoint is disabled")
    if not _secret_matches(settings.admin_secret, supplied):
        raise HTTPException(status_code=401, detail="invalid admin secret")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app, discord_client
    settings.validate_runtime_security()

    # One scheduled scan every configured interval. Exactly one of those scans
    # also emits the regular daily price summary, so no extra Google request is
    # created just for the summary.
    for hour in settings.scheduled_search_hours:
        scheduler.add_job(
            service.check_all,
            "cron",
            hour=hour,
            minute=0,
            kwargs={"notify_target": True, "notify_daily_summary": hour == settings.daily_summary_hour},
            id=f"price-scan-{hour:02d}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    telegram_app = await build_telegram(settings, service, notifier)
    discord_client = await start_discord(settings, service, notifier)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        if telegram_app:
            await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()
        if discord_client:
            await discord_client.close()
        await service.close()


app = FastAPI(title="Flight Bot", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health():
    discord_ready = bool(notifier.discord_client and notifier.discord_client.is_ready())
    return {
        "ok": True,
        "provider": service.provider.name,
        "provider_accepted_for_alerts": bool(getattr(service.provider, "accepted_for_alerts", True)),
        "require_verified_alerts": settings.require_verified_alerts,
        "browser_headless": settings.browser_headless,
        "search_interval_hours": settings.search_interval_hours,
        "daily_summary_hour": settings.daily_summary_hour,
        "browser_search_storage_isolated": True,
        "telegram_connected": notifier.telegram_app is not None,
        "discord_connected": discord_ready,
        "kakao_skill_enabled": bool(settings.kakao_skill_secret),
        "admin_endpoint_enabled": bool(settings.admin_secret),
        "scan_active": service.scan_active,
        "slots_used": len(db.list_slots()),
        "slots_max": settings.slot_active_limit,
        "slots_design_capacity": SLOT_DESIGN_CAPACITY,
    }


@app.post("/kakao/skill")
async def kakao_skill(request: Request, x_flight_bot_secret: str | None = Header(default=None)):
    if not settings.kakao_skill_secret:
        raise HTTPException(status_code=404, detail="Kakao skill is disabled")
    if not _secret_matches(settings.kakao_skill_secret, x_flight_bot_secret):
        raise HTTPException(status_code=401, detail="invalid skill secret")
    payload = await request.json()
    user_request = payload.get("userRequest") or {}
    utterance = str(user_request.get("utterance") or "").strip()
    user = user_request.get("user") or {}
    user_id = str(user.get("id") or "unknown")
    if user_id not in settings.kakao_user_ids:
        return kakao_response("허용되지 않은 사용자입니다.")
    return kakao_response(await service.command("kakao", user_id, utterance))


@app.post("/admin/check-all")
async def check_all(x_flight_bot_secret: str | None = Header(default=None)):
    """Start the normal all-slot scan now, including one-shot target alerts."""
    _require_admin(x_flight_bot_secret)
    if service.scan_active:
        return {"accepted": False, "reason": "scan already active"}
    asyncio.create_task(service.check_all(notify_target=True, notify_daily_summary=False))
    return {"accepted": True, "mode": "target-check-all"}


@app.post("/admin/daily-summary")
async def daily_summary(x_flight_bot_secret: str | None = Header(default=None)):
    """Force the regular summary now without consuming a target-alert latch."""
    _require_admin(x_flight_bot_secret)
    if service.scan_active:
        return {"accepted": False, "reason": "scan already active"}
    asyncio.create_task(service.check_all(notify_target=False, notify_daily_summary=True))
    return {"accepted": True, "mode": "daily-summary-all", "target_alerts": False}


@app.post("/admin/check-slot/{slot_id}")
async def check_slot(slot_id: int, x_flight_bot_secret: str | None = Header(default=None)):
    """Run one real slot search and exercise its one-shot target alert."""
    _require_admin(x_flight_bot_secret)
    if service.scan_active:
        return {"accepted": False, "reason": "all-slot scan already active"}
    result = await service.check_slot(
        slot_id,
        notify_target=True,
        notify_daily_summary=False,
    )
    return {"accepted": True, "mode": "target-check-slot", "slot_id": slot_id, "result": result}


@app.post("/admin/daily-summary/{slot_id}")
async def daily_summary_slot(slot_id: int, x_flight_bot_secret: str | None = Header(default=None)):
    """Force one slot's regular summary without changing target-alert state."""
    _require_admin(x_flight_bot_secret)
    if service.scan_active:
        return {"accepted": False, "reason": "all-slot scan already active"}
    result = await service.check_slot(
        slot_id,
        notify_target=False,
        notify_daily_summary=True,
    )
    return {"accepted": True, "mode": "daily-summary-slot", "slot_id": slot_id, "target_alerts": False, "result": result}


def main():
    uvicorn.run(app, host="0.0.0.0", port=settings.http_port, log_level="info")


if __name__ == "__main__":
    main()
