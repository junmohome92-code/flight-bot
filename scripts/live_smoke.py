from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict

from flight_bot.config import Settings
from flight_bot.models import WatchSlot
from flight_bot.providers import GoogleFlightsPlaywrightProvider


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def main() -> None:
    settings = Settings(
        browser_headless=env_bool("BROWSER_HEADLESS", True),
        browser_debug_dir=os.getenv("BROWSER_DEBUG_DIR", "artifacts/live-smoke"),
        google_language="en",
        google_currency="KRW",
        google_gl="kr",
    )
    slot = WatchSlot(
        id=1,
        owner_platform="smoke",
        owner_id="smoke",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        nonstop=False,
        checked_bag=0,
        enabled=True,
        target_price=500_000,
    )
    offer = await GoogleFlightsPlaywrightProvider(settings).search(slot, verify_below_price=500_000)
    payload = asdict(offer)
    if payload.get("fetched_at"):
        payload["fetched_at"] = payload["fetched_at"].isoformat()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not 50_000 <= offer.total_price <= 1_500_000:
        raise SystemExit(f"implausible KRW price: {offer.total_price}")


if __name__ == "__main__":
    asyncio.run(main())
