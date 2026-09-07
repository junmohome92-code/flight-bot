# Project Status

## Release

- Current release target: **v0.5.0**
- Runtime provider: **Naver Flights SSE API only**
- Browser automation / Playwright / DOM scraping: **retired from production runtime**

## Current production scope

- Search shape: adult 1 / economy / direct / round trip / KRW
- Ranked result output: price-sorted TOP 5 unique round-trip combinations
- Flight detail output: outbound/return airline, flight number, time, and actual departure/arrival airport
- Persistent watch capacity: **20 slots**
- Ad-hoc one-time search: supported without creating or consuming a slot
- Per-slot immediate search: supported from Telegram UI and command fallback
- Telegram: button-first add/search/manage UI
- Help aliases: `/help`, `/?`
- Airport input: IATA code or common airport/city name
- Airport validation: bundled real IATA catalogue via `airportsdata`
- Invalid/typo input: rejected before save/search with close real-location suggestions
- Multi-airport city search: supported with explicit `city` location type, including `SEL`, `TYO`, `OSA` and other configured city groups
- Daily summary: **one aggregated message per user**, regardless of active slot count
- Daily summary rows: current lowest fare + previous-observation delta (`▼/▲/─`) + target-hit marker (`🎯`)
- Telegram daily summary: per-slot `상세` buttons trigger fresh TOP 5 search
- Target alert: one-shot latch remains independent from the daily summary
- Paused slots: excluded from scheduled scans and daily summary
- Docker: browserless Python 3.12 slim runtime with SQLite persistent volume
- Installer: `bash install.sh`

## Live validation evidence — 2026-09-07

### Airport-to-airport

`CJJ → TPE → CJJ`, `2026-09-18 ~ 2026-09-20`:

- HTTP status: 201
- Content-Type: `text/event-stream`
- SSE events: 20
- Lowest direct round-trip fare: **319,620 KRW**
- Matched Naver Flights displayed lowest fare at validation time

### City-to-city

`SEL:city → TYO:city → SEL:city`, `2026-09-22 ~ 2026-09-24`:

- `origin_type=city`
- `destination_type=city`
- Direct candidates built: 20
- Lowest direct round-trip fare: **450,400 KRW**
- Naver advertised direct lowest fare: **450,400 KRW**
- Example resolved itinerary: `ICN → NRT` / `NRT → ICN`
- Live probe result: **PASS**

The one-off live city workflow was removed after the successful validation so it does not generate unnecessary recurring external traffic.

## CI / release gate

Before merging to `main`, require success for:

- Python compile
- full pytest suite
- IATA / city-location contracts
- FastAPI endpoint contracts
- Telegram UI and aggregate-summary button contracts
- Windows Naver SSE harness
- install/Compose validation
- browserless dependency policy
- Docker image build
- actual container startup and `/health` verification

Final branch CI after removing the temporary live workflow passed both Linux and Windows jobs on 2026-09-07.

## Runtime boundaries

- Reservation/payment navigation: out of scope
- External seller checkout final-price verification: out of scope
- DOM/browser fallback: intentionally absent
- Naver internal SSE contract is private/undocumented and must be revalidated if the upstream request or response schema changes
