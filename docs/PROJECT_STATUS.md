# Project Status

## Current production direction

- Price source: Naver Flights SSE API only
- Browser automation / DOM scraping: retired
- Search shape: adult 1 / economy / direct / round trip / KRW
- Ranked result output: price-sorted TOP 5
- Persistent watch capacity: 20 slots
- Ad-hoc one-time search: supported without consuming a slot
- Per-slot immediate search: supported
- Telegram: button-first add/search/manage UI plus command fallback
- Help aliases: `/help`, `/?`
- Docker: browserless Python 3.12 slim runtime with SQLite persistent volume

## Validation boundary

CI validates Python compile, full pytest suite, HTTP endpoints, Telegram UI contracts, install/compose contract, browserless dependency policy, Docker build, and live container `/health`.
