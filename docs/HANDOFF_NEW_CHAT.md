# Flight Bot handoff

## Current state

Flight Bot v0.5 uses **Naver Flights SSE as the sole production price source**. Playwright/browser/DOM extraction is retired and must not be reintroduced as a fallback unless the project direction is explicitly changed.

## Product scope

- 20 persistent watch slots
- ad-hoc one-time search without slot creation
- per-slot immediate search
- Telegram button-first add/search/manage UI
- `/help` and `/?` help aliases
- direct round-trip TOP 5 with airline / flight number / time / actual airport details
- real IATA validation using the local `airportsdata` catalogue
- typo/invalid airport rejection with close real-location suggestions
- airport-name/city-name input in Telegram
- multi-airport city selection, e.g.:
  - Seoul: `SEL` / `ICN` / `GMP`
  - Tokyo: `TYO` / `NRT` / `HND`
  - Osaka: `OSA` / individual airports
- city searches are sent to Naver as `locationType=city`; individual airports use `locationType=airport`
- daily scheduled report is **one message per user**, not one message per slot
- daily rows include price movement vs previous observation and target marker
- Telegram daily report provides `#N 상세` buttons for a fresh per-slot TOP 5 search
- one-shot target alerts stay separate from the daily summary
- paused slots are excluded from scheduled scans/reports
- Docker-first deployment with `bash install.sh`
- FastAPI health/admin endpoints, including ad-hoc `/admin/search`

## Production persistence — do not regress

Production Compose persistence is a **host bind mount**, not a Docker named volume:

```yaml
volumes:
  - ./data:/data
```

The application still uses `/data/flight_bot.db` inside the container. On the current home server repository at `/data/flight-bot`, the real DB is:

```text
/data/flight-bot/data/flight_bot.db
```

Hard rules for future work:

- Never delete, truncate, reset, replace, or recreate this DB as part of a code update.
- Keep `docker compose up -d --build` as a safe redeploy path.
- `install.sh` may prepare `data/` permissions for the non-root container but must leave existing DB contents untouched.
- CI must validate actual Compose startup, `/health`, and host SQLite persistence.
- Do not switch back to `flight_bot_data:/data` unless an explicit migration plan is approved.
- A legacy named volume may still exist on older installations; switching persistence paths does not itself copy that DB into `./data`.

## Confirmed live SSE results — 2026-09-07

Airport search:

```text
CJJ -> TPE -> CJJ
2026-09-18 ~ 2026-09-20
HTTP 201 / text-event-stream
lowest direct round-trip: 319,620 KRW
PASS
```

City search:

```text
SEL:city -> TYO:city -> SEL:city
2026-09-22 ~ 2026-09-24
origin_type=city
destination_type=city
direct candidates=20
lowest=450,400 KRW
Naver advertised lowest=450,400 KRW
PASS
```

The city result resolved to real airports such as `ICN -> NRT`, proving that city-group requests and itinerary decoding work end-to-end.

## Validation / merge policy

Before merging feature work to `main`, require green CI for:

- Linux full suite
- Windows SSE harness
- IATA/city-location tests
- Telegram UI + aggregate daily-summary contracts
- FastAPI contracts
- install/Compose validation
- browserless runtime policy
- Docker build
- actual Compose container `/health`
- bind-mounted SQLite persistence

Baseline `main` commit before the persistence patch: `26ddbad71e7a328c180a25e2e089b3bd158cdbec`. Its normal CI passed Linux and Windows on 2026-09-07.

## Version / docs

- `VERSION`: `0.5.0`
- `pyproject.toml`: `0.5.0`
- `README.md`: current user/install/runtime guide
- `docs/PROJECT_STATUS.md`: current technical status and validation evidence
- `docs/RELEASE_NOTES_V0.5.md`: v0.5 change summary

## Boundaries

- No reservation/payment automation
- No external seller checkout verification
- No Playwright/DOM fallback
- Naver SSE is an internal upstream contract; if Naver changes the request/response schema, re-run a live probe before changing parser logic
