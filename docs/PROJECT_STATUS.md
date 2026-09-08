# Project Status

## Release

- Current release target: **v0.6.0**
- Runtime price provider: **Naver Flights SSE API only**
- Browser automation / Playwright / DOM scraping: **retired from production runtime**

## Current production scope

- Search shape: adult 1 / economy / direct / round trip / KRW
- Ranked result output: price-sorted TOP 5 unique round-trip combinations
- Flight detail output: outbound/return airline, flight number, time, and actual departure/arrival airport
- Persistent watch capacity: **20 slots per conversation/chat**
- One Telegram bot process can serve multiple allowed private/group chats
- Ad-hoc one-time search: supported without creating or consuming a slot
- Per-slot immediate search: supported from Telegram UI
- Telegram: button-first add/search/manage UI
- User-facing help: compact/button-first; legacy `/flight ...` commands are hidden compatibility paths
- Location input: Korean / English / IATA
- Exact IATA validation: `airportsdata`
- Worldwide multilingual name search: offline `airportsearch` data pinned to immutable upstream commit `74ee42e242837ad247f9c94aa56bde184fa96dbf`
- Ambiguous/fuzzy location input: never auto-saved; user must choose a candidate
- Multi-airport city search: explicit `city` type and individual `airport` type
- `origin_type` / `destination_type`: persisted in SQLite and sent explicitly to Naver
- Registration: save slot, then run one immediate baseline TOP 5 search without consuming target-alert latch
- Scheduled scans: default every 2 hours
- Target alert: one-shot latch per target setting (`ARMED -> SENDING -> ALERTED`)
- Daily summary: **one aggregated message per conversation**, not one message per slot
- Daily rows: current lowest fare + previous-observation delta (`▼/▲/─`) + target marker (`🎯`)
- Telegram summary buttons: `#N 상세` triggers a fresh per-slot TOP 5 search
- Paused slots: excluded from scheduled scans and daily summary
- Docker: browserless Python 3.12 slim runtime
- SQLite persistence: **host bind mount `./data:/data`**
- Production DB path on home server: `/data/flight-bot/data/flight_bot.db`
- Installer: `bash install.sh`

## v0.6 slot ownership model

`watch_slots.id` remains the internal database primary key so existing history/foreign keys are preserved. User-visible slot numbering is separated into `slot_no`.

Uniqueness contract:

```text
(owner_platform, owner_id, slot_no)
```

Therefore:

```text
Telegram group A: #1 .. #20
Telegram group B: #1 .. #20
private chat      : #1 .. #20
```

A group can fill all 20 slots without consuming another group's namespace. Internal IDs may be greater than 20; Telegram callback payloads use the internal ID while UI/report labels use local `slot_no`.

## v0.6 additive DB migration — no reset

Existing production DB contents must be preserved. Startup migration only adds/backfills columns/indexes:

- `slot_no`
- `origin_type`
- `destination_type`
- unique owner-local slot index

Existing `id`, offers, alert history, search history, generation/revision and observed prices remain in place. Previously supported city codes such as `SEL`/`TYO` are backfilled to `city`; existing airport slots remain `airport`.

## Telegram group-safety invariants

- Allowed chats are controlled by comma-separated `TELEGRAM_ALLOWED_CHAT_IDS`.
- Flow state is keyed by chat ID inside Telegram user state, preventing the same person from overwriting an in-progress flow in another group.
- Free-text location/date/price steps use `ForceReply` for group Privacy Mode compatibility.
- Arbitrary normal group messages are ignored; they do not trigger HELP spam.
- Slot operations verify ownership before changes.
- Scheduled report/target notifications use the slot's owning chat ID.

## Persistence invariant

The SQLite database is production state and must never be deleted or reinitialized during code updates.

Required Compose contract:

```yaml
volumes:
  - ./data:/data
```

- Container path: `/data/flight_bot.db`
- Repository-relative host path: `./data/flight_bot.db`
- Home-server path: `/data/flight-bot/data/flight_bot.db`
- `docker compose up -d --build` must preserve the existing host DB.
- `install.sh` may create/fix permissions on `data/` but must not delete/truncate/replace an existing DB.
- Docker image runs as non-root UID `10001`.
- Do not switch back to Docker named-volume persistence without an explicit migration plan.

## Notification lifecycle

Required behavior:

```text
slot registration
  -> immediate baseline TOP 5 result (notify_target=False)
  -> scheduled scans continue
  -> first target hit sends one 🔥 alert
  -> same target does not alert again
  -> daily summary continues once/day
```

Changing the target rearms the one-shot target alert.

## Confirmed live Naver evidence — 2026-09-07

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
- Result: **PASS**

## CI / release gate

Before merging v0.6 to `main`, require success for:

- Python compile
- Linux full pytest suite
- Windows Naver SSE harness
- owner-local 20-slot DB contracts
- additive legacy-DB migration
- worldwide Korean/English/IATA search contracts, including `히로시마 -> HIJ`
- explicit airport/city type contracts
- Telegram group-flow isolation and compact-help contracts
- FastAPI v0.6 health contracts
- install/Compose validation
- browserless dependency policy
- Docker image build
- actual `docker compose up -d --build` startup and `/health`
- bind-mounted SQLite persistence before/after Compose teardown

## Runtime boundaries

- Reservation/payment navigation: out of scope
- External seller checkout final-price verification: out of scope
- DOM/browser fallback: intentionally absent
- Naver internal SSE contract is private/undocumented and must be revalidated if upstream schema changes
