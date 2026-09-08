# Flight Bot v0.6.0 Release Notes

Date: 2026-09-08

## Summary

v0.6.0 keeps the browserless Naver Flights SSE price pipeline and focuses on Telegram group operation, worldwide location input, and safe evolution of the existing production SQLite database.

## Telegram / group changes

- One bot process can serve multiple allowed Telegram chats.
- Each conversation gets its own visible slot namespace `#1 .. #20`.
- Internal DB IDs remain global and are not exposed as the user-facing slot number.
- Registration/search flow state is isolated by chat so the same user can work in multiple groups without state collision.
- Free-text steps use `ForceReply` for group Privacy Mode compatibility.
- Unrelated group text is ignored instead of triggering HELP replies.
- Telegram command menu now exposes only `/start` and `/help`; legacy `/flight ...` commands remain compatibility-only.
- Help text was shortened to the button-first product surface.

## Location changes

- Removed fixed origin/destination quick buttons that implied a small route whitelist.
- Input prompt now explicitly supports Korean, English and IATA worldwide.
- Exact IATA validation continues to use `airportsdata`.
- Multilingual name search uses the offline `airportsearch` dataset pinned to immutable upstream commit `74ee42e242837ad247f9c94aa56bde184fa96dbf`.
- Fuzzy/ambiguous text is never silently saved; the user must choose a candidate.
- Multi-airport metropolitan choices and individual airports are distinguished by explicit `city` / `airport` type.
- `origin_type` and `destination_type` are persisted in SQLite and sent directly to Naver.

## Alert lifecycle changes

After a new watch is confirmed:

1. save the slot,
2. run one immediate TOP 5 baseline lookup,
3. keep the target latch ARMED because that baseline uses `notify_target=False`,
4. on a later scheduled scan, send one target alert if the target is met,
5. do not repeat that target alert for the same target setting,
6. continue the daily aggregated report.

Changing the target rearms the latch.

## Database / migration

Production DB remains:

```text
/data/flight-bot/data/flight_bot.db
```

Compose remains:

```yaml
volumes:
  - ./data:/data
```

v0.6 migration is additive. It adds/backfills `slot_no`, `origin_type`, and `destination_type`, plus owner-local indexes. Existing watch rows, internal IDs, offers, alert history, search history, generations/revisions and observed prices are preserved.

No DB reset/delete/truncate operation is part of this release.

## CI gate

Required release validation includes:

- Linux full pytest suite
- Windows Naver SSE harness
- per-conversation 20-slot tests
- additive legacy SQLite migration
- Korean/English/IATA worldwide location contracts
- `히로시마 -> HIJ` regression
- Telegram flow isolation and compact-help contracts
- FastAPI v0.6 health flags
- browserless policy checks
- Docker image build
- real Compose startup and `/health`
- host bind-mounted SQLite persistence after Compose teardown

## Unchanged boundaries

- Adult 1 / economy / direct / round trip / KRW
- Naver Flights SSE is the sole price source
- no browser/DOM fallback
- no reservation/payment automation
- no external checkout final-price verification
