# Flight Bot handoff

## Current state

Flight Bot v0.6 uses **Naver Flights SSE as the sole production price source**. Playwright/browser/DOM extraction is retired and must not be reintroduced as a fallback unless project direction is explicitly changed.

## v0.6 product scope

- adult 1 / economy / direct / round trip / KRW
- price-sorted TOP 5 with airline / flight number / time / actual airports
- **20 persistent watch slots per conversation/chat**
- one bot process/token can serve multiple Telegram private/group chats
- ad-hoc one-time search without slot creation
- per-slot immediate search
- Telegram button-first add/search/manage UI
- compact user-facing help; `/flight ...` commands remain compatibility-only and are hidden from the command menu/help
- Korean / English / IATA location input
- exact IATA validation via `airportsdata`
- worldwide multilingual offline name search using `airportsearch`, pinned to upstream commit `74ee42e242837ad247f9c94aa56bde184fa96dbf`
- ambiguous/fuzzy matches require an explicit user button selection before save
- multi-airport city vs individual airport selection
- explicit `origin_type` / `destination_type` persisted and sent to Naver
- registration performs an immediate baseline TOP 5 lookup with target notification disabled
- scheduled search default every 2 hours
- target-hit notification is one-shot per target setting
- daily scheduled report is **one message per conversation**
- daily rows include previous-price movement and target marker
- daily report `#N 상세` buttons run a fresh TOP 5 search
- paused slots excluded from scheduled scans/reports
- Docker-first deployment with `bash install.sh`

## Multi-group ownership model

Do not revert to global slot numbering.

- `watch_slots.id`: internal DB PK, global, retained for history/FKs/callback payloads
- `watch_slots.slot_no`: user-facing 1..20 scoped by `(owner_platform, owner_id)`
- unique contract: `(owner_platform, owner_id, slot_no)`

Example:

```text
group A: #1 .. #20
group B: #1 .. #20
```

Telegram `owner_id` is the chat ID. Slot listing, target alerts and daily reports stay in the owning chat.

Telegram registration/search flow state must also remain chat-isolated. The same user may interact with the bot in two groups at once. Free-text steps use `ForceReply` to work safely with group Privacy Mode. Unrelated group text must be ignored, not answered with HELP.

## DB migration — preserve existing production data

v0.6 migration is additive. It adds/backfills:

- `slot_no`
- `origin_type`
- `destination_type`
- owner-local slot indexes

It must not recreate `watch_slots`, reset IDs, delete offers, delete alert/search history or clear observed prices. Existing v0.5 city codes are backfilled to `city`; existing airport slots stay `airport`.

## Production persistence — do not regress

Production Compose uses a **host bind mount**, not a Docker named volume:

```yaml
volumes:
  - ./data:/data
```

Container DB:

```text
/data/flight_bot.db
```

Current home-server DB:

```text
/data/flight-bot/data/flight_bot.db
```

Hard rules:

- Never delete, truncate, reset, replace, or recreate the production DB as part of a code update.
- Keep `docker compose up -d --build` as a safe redeploy path.
- `install.sh` may prepare `data/` permissions but must leave existing DB contents untouched.
- CI must verify actual Compose startup, `/health`, and host SQLite persistence.
- Do not switch back to `flight_bot_data:/data` without an approved migration plan.

## Notification lifecycle

Required behavior:

```text
registration
  -> immediate TOP 5 baseline result
     (notify_target=False, target latch remains ARMED)
  -> scheduled scans
  -> first price <= target: one 🔥 target alert
  -> no repeat target alert for the same target
  -> daily summary continues once/day
```

Changing the target rearms the target latch.

## Confirmed Naver live results — 2026-09-07

```text
CJJ -> TPE -> CJJ
2026-09-18 ~ 2026-09-20
lowest 319,620 KRW
PASS

SEL:city -> TYO:city -> SEL:city
2026-09-22 ~ 2026-09-24
direct candidates 20
lowest 450,400 KRW
Naver advertised lowest 450,400 KRW
PASS
```

## Validation / merge policy

Before merging feature work to `main`, require green:

- Linux full suite
- Windows SSE harness
- DB additive migration + per-conversation 20-slot tests
- worldwide multilingual location tests (`히로시마 -> HIJ` included)
- explicit city/airport type tests
- Telegram group-flow/help/UI contracts
- FastAPI contracts
- install/Compose validation
- browserless runtime policy
- Docker build
- real Compose `/health`
- bind-mounted SQLite persistence

## Version / docs

- `VERSION`: `0.6.0`
- `pyproject.toml`: `0.6.0`
- `README.md`: user/install/runtime guide
- `docs/PROJECT_STATUS.md`: technical status/invariants
- `docs/RELEASE_NOTES_V0.6.md`: v0.6 change summary

## Boundaries

- No reservation/payment automation
- No external seller checkout verification
- No Playwright/DOM fallback
- Naver SSE is an internal upstream contract; schema changes require a live revalidation before parser changes
