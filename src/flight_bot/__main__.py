from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Header, HTTPException, Request

from .channels import MultiNotifier, build_telegram, start_discord
from .config import get_settings
from .db import Database
from .service import FlightService

settings = get_settings()
db = Database(settings.database_path)
service = FlightService(settings, db)
notifier = MultiNotifier()
service.set_notifier(notifier)
scheduler = AsyncIOScheduler(timezone=settings.timezone)
telegram_app = None
discord_client = None


def kakao_response(text: str) -> dict:
    return {"version": "2.0", "template": {"outputs": [{"simpleText": {"text": text[:1000]}}]}}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app, discord_client
    for hour in settings.scheduled_hours:
        scheduler.add_job(service.check_all, "cron", hour=hour, minute=0, id=f"check-{hour}",
                          replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    telegram_app = await build_telegram(settings, service, notifier)
    discord_client = await start_discord(settings, service, notifier)
    yield
    scheduler.shutdown(wait=False)
    if telegram_app:
        await telegram_app.updater.stop(); await telegram_app.stop(); await telegram_app.shutdown()
    if discord_client:
        await discord_client.close()


app = FastAPI(title="Flight Bot", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True, "provider": "google-playwright", "browser_headless": settings.browser_headless,
            "telegram": bool(settings.telegram_bot_token), "discord": bool(settings.discord_bot_token),
            "kakao_skill": True, "slots_used": len(db.list_slots()), "slots_max": 3}


@app.post("/kakao/skill")
async def kakao_skill(request: Request, x_flight_bot_secret: str | None = Header(default=None)):
    if settings.kakao_skill_secret and x_flight_bot_secret != settings.kakao_skill_secret:
        raise HTTPException(status_code=401, detail="invalid skill secret")
    payload = await request.json()
    user_request = payload.get("userRequest") or {}
    utterance = str(user_request.get("utterance") or "").strip()
    user = user_request.get("user") or {}
    user_id = str(user.get("id") or "unknown")
    if settings.kakao_user_ids and user_id not in settings.kakao_user_ids:
        return kakao_response("허용되지 않은 사용자입니다.")
    return kakao_response(await service.command("kakao", user_id, utterance))


@app.post("/admin/check-all")
async def check_all(x_flight_bot_secret: str | None = Header(default=None)):
    if not settings.kakao_skill_secret or x_flight_bot_secret != settings.kakao_skill_secret:
        raise HTTPException(status_code=401, detail="invalid secret")
    asyncio.create_task(service.check_all())
    return {"accepted": True}


def main():
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
