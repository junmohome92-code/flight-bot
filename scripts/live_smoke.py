from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from flight_bot.config import Settings
from flight_bot.models import WatchSlot
from flight_bot.providers import NaverFlightsSSEProvider


async def main() -> None:
    settings = Settings(app_env="development")
    slot = WatchSlot(
        id=1,
        owner_platform="smoke",
        owner_id="smoke",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        nonstop=True,
        checked_bag=0,
        enabled=True,
        target_price=500_000,
    )
    provider = NaverFlightsSSEProvider(settings)
    offer = await provider.search(slot)
    payload = asdict(offer)
    if payload.get("fetched_at"):
        payload["fetched_at"] = payload["fetched_at"].isoformat()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not 50_000 <= offer.observed_price <= 1_500_000:
        raise SystemExit(f"implausible KRW observed price: {offer.observed_price}")
    if offer.provider != "naver-flights-sse":
        raise SystemExit(f"unexpected provider: {offer.provider}")
    if not offer.nonstop:
        raise SystemExit("live smoke must remain direct-only")


if __name__ == "__main__":
    asyncio.run(main())
