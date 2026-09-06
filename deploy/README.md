# Ubuntu / Docker deployment

The production runtime uses the same `accepted-tfs-v1` Google Flights query contract and Cheapest-first state machine as the Windows acceptance probe.

## First deployment

The Ubuntu host needs Docker Engine and the Docker Compose plugin. From the repository root:

```bash
cp .env.example .env
nano .env
```

At minimum fill:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=...
ADMIN_SECRET=...
```

Then run:

```bash
bash deploy/ubuntu-deploy.sh
```

The script validates `.env`, validates Compose, builds the production image, starts the container, waits for health, and verifies:

```text
provider = google-playwright-results-observed-accepted-flow
query contract = accepted-tfs-v1
slots = 10
search interval = 2 hours
search concurrency = 2
fresh BrowserContext storage isolation = enabled
asset blocking = disabled
Cheapest forced reload = enabled
Price unavailable recovery reloads = 2
Telegram = connected
admin API = enabled
```

The named Docker volume keeps the SQLite database across image rebuilds and ordinary `docker compose down/up` cycles.

## Real Google + Telegram verification

After the bot is running, add a slot in Telegram, for example:

```text
/flight add CJJ TPE 2026-09-18 2026-09-20 999999
```

Then on Ubuntu:

```bash
bash deploy/ubuntu-live-check.sh 1 target
```

This runs the same production search path used by the two-hour scheduler. It does not use a separate acceptance URL or a separate provider.

To force the regular daily-summary notification without consuming/rearming the target latch:

```bash
bash deploy/ubuntu-live-check.sh 1 daily
```

## Normal operation

```bash
# container state
docker compose ps

# logs
docker compose logs -f --tail 120 flight-bot

# rebuild/update after pulling new code
bash deploy/ubuntu-deploy.sh

# stop container; data volume remains
docker compose down
```

## Search behavior

Ten slots may exist, but Google is never hit by ten simultaneous searches. The default scheduler runs at most two slot searches concurrently with a five-second launch stagger. Every search receives its own fresh BrowserContext, so cookies, HTTP cache, localStorage, IndexedDB, and service-worker state are not inherited from another observation.

Direct-only is a result policy, not a special Google query variant. The bot opens the normal accepted round-trip result surface, selects Cheapest, performs the required full reload/recovery sequence, captures concrete result rows, and only then keeps rows explicitly marked `Nonstop`/direct.
