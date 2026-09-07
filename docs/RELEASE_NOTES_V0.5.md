# Flight Bot v0.5.0 Release Notes

Date: 2026-09-07

## Summary

v0.5.0 keeps the production runtime fully browserless and extends the Naver Flights SSE implementation with safer location input, multi-airport city search, a cleaner Telegram daily-report experience, and an explicit host-mounted SQLite persistence contract.

## User-facing changes

- Watch capacity remains 20 slots.
- Each slot can be searched immediately from Telegram.
- One-time search works without registering a slot.
- Telegram registration/search accepts airport codes and common airport/city names.
- Invalid IATA codes are rejected before persistence/search and close real locations are suggested.
- Multi-airport cities can be searched as a whole or by individual airport.
  - Seoul: `SEL` / `ICN` / `GMP`
  - Tokyo: `TYO` / `NRT` / `HND`
  - Osaka: `OSA` / individual airports
- Daily scheduled reporting is aggregated to one message per user.
- Daily rows show current lowest fare, movement from the previous observation, and target-hit state.
- Telegram daily summary includes per-slot `상세` buttons that run a fresh TOP 5 search.
- Target-price alerts remain separate one-shot alerts.

## Provider / data changes

- Production source remains `https://flight-api.naver.com/flight/international/searchFlights`.
- Airport searches use `locationType=airport`.
- City-group searches use `locationType=city`.
- IATA validation uses the bundled `airportsdata` catalogue.
- Output keeps price-sorted unique direct round-trip combinations and includes actual airports, airline, flight number, and times.
- No Playwright, Chromium, DOM selector, or browser fallback is used by the production runtime.

## Live validation

### CJJ ↔ TPE

- Dates: 2026-09-18 ~ 2026-09-20
- HTTP: 201
- Content-Type: `text/event-stream`
- SSE events: 20
- Lowest direct round-trip fare: 319,620 KRW
- Result: PASS

### SEL city ↔ TYO city

- Dates: 2026-09-22 ~ 2026-09-24
- Origin type: city
- Destination type: city
- Direct candidate count: 20
- Lowest direct round-trip fare: 450,400 KRW
- Naver advertised direct lowest fare: 450,400 KRW
- Example resolved route: ICN → NRT / NRT → ICN
- Result: PASS

## Deployment / persistence

- Python 3.12 slim Docker runtime
- `bash install.sh` remains the recommended install/update path
- IATA catalogue is installed inside the image; no separate airport-data download is required
- SQLite persistence uses host bind mount `./data:/data`
- Container DB path: `/data/flight_bot.db`
- Current home-server DB path: `/data/flight-bot/data/flight_bot.db`
- `docker compose up -d --build` preserves the DB across image rebuild/container recreation
- `install.sh` prepares the host data directory for the non-root container without deleting or recreating an existing DB

## CI gate

Validated by the repository CI contract:

- full pytest suite
- source/script compile
- Windows SSE harness
- IATA and city-location contracts
- Telegram UI and daily-summary contracts
- FastAPI endpoint contracts
- install/Compose validation
- browserless policy checks
- Docker image build
- actual Compose startup and `/health` check
- bind-mounted SQLite creation and persistence after Compose teardown

## Known boundaries

- Adult 1 / economy / direct / round trip is the current search product shape.
- Reservation/payment navigation is not implemented.
- External seller checkout final-price verification is not implemented.
- Naver SSE is an internal upstream interface; upstream schema changes require revalidation.
