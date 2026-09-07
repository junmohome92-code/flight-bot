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
- live container `/health`

The temporary workflow used for the one-time live `SEL <-> TYO` probe was removed after PASS. The normal branch CI subsequently passed Linux and Windows.

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
