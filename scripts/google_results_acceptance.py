from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

from flight_bot.google_query import QUERY_CONTRACT, build_google_flights_search_url
from flight_bot.google_results_flow import prepare_cheapest_surface
from flight_bot.providers import rank_alert_candidates

try:  # direct Windows execution from scripts/
    import google_booking_acceptance as acceptance
    import google_booking_pointer_probe as base
    import google_cheapest_capture as cheapest
except ImportError:  # pytest/import from repository root
    from scripts import google_booking_acceptance as acceptance
    from scripts import google_booking_pointer_probe as base
    from scripts import google_cheapest_capture as cheapest


async def _run_session(playwright) -> None:
    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    selection_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_SELECTION_WAIT_MS", "25000")))
    departure_capture_ms = max(1500, int(os.getenv("GOOGLE_UI_DEPARTURE_CAPTURE_MS", "3500")))
    ready_wait_ms = max(2500, int(os.getenv("GOOGLE_UI_PRICE_READY_WAIT_MS", "8000")))
    recovery_reloads = max(0, int(os.getenv("GOOGLE_UI_PRICE_RELOADS", "2")))
    max_offers = max(1, int(os.getenv("ALERT_MAX_OFFERS", "4")))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "8"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))

    canonical_url = build_google_flights_search_url(
        origin=base.ORIGIN,
        destination=base.DESTINATION,
        depart_date="2026-09-18",
        return_date="2026-09-20",
        language="en",
        gl="kr",
        currency="KRW",
    )
    supplied_url = os.getenv("GOOGLE_UI_SEARCH_URL", "").strip()
    if supplied_url and supplied_url != canonical_url:
        raise RuntimeError(
            "GOOGLE_UI_SEARCH_URL does not match the production accepted-tfs-v1 query contract"
        )
    search_url = canonical_url

    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = base.free_local_port()
    edge_process = None
    browser = None
    page: Page | None = None

    try:
        edge_process = base.launch_edge_blank(profile_dir, port)
        await base.wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]

        dom_capture = base._DOM_CAPTURE_PATH.read_text(encoding="utf-8")
        init_script = (
            "window.__flightBotInitConfig = "
            + json.dumps({"origin": base.ORIGIN, "destination": base.DESTINATION})
            + ";\n"
            + dom_capture
        )
        await context.add_init_script(init_script)

        page = await acceptance.claim_initial_page(context, timeout_ms)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"query_contract={QUERY_CONTRACT}")
        print(f"selection_url={page.url}")

        async def reload_adapter(current: Page, url: str, timeout: int) -> Page:
            return await acceptance.reload_or_reopen(context, current, url, timeout)

        print("\n=== CHEAPEST WARM-UP + FULL REFRESH ===")
        page, recovery_count = await prepare_cheapest_surface(
            page,
            search_url,
            reload_page=reload_adapter,
            timeout_ms=timeout_ms,
            selection_wait_ms=selection_wait_ms,
            ready_wait_ms=ready_wait_ms,
            recovery_reloads=recovery_reloads,
            ensure_selected=cheapest.ensure_cheapest_selected,
        )

        print("\n=== DIRECT GOOGLE RESULTS ===")
        best, state, policy = await cheapest.wait_for_candidate(
            page,
            phase="departure",
            origin=base.ORIGIN,
            destination=base.DESTINATION,
            timeout_ms=selection_wait_ms,
            capture_window_ms=departure_capture_ms,
            allow_missing_route=True,
            min_price=base.MIN_KRW_PRICE,
        )
        if not best:
            await base.save_debug(page, artifact_dir, "direct-results-capture-failed")
            raise RuntimeError("Cheapest loaded but no trustworthy departure result row was captured")

        raw_rows = cheapest.phase_candidates(state, "departure")
        candidates = [
            {"price": item.get("price"), "text": item.get("rowText") or "", "source": item.get("sourceText")}
            for item in raw_rows
            if item.get("price") is not None
        ]
        direct_rows = rank_alert_candidates(candidates, nonstop_only=True, limit=max_offers)
        if not direct_rows:
            await base.save_debug(page, artifact_dir, "direct-results-none")
            raise RuntimeError("Google results loaded but no explicit nonstop/direct rows were captured")

        await base.save_json(artifact_dir / "snapshot-direct-offers.json", direct_rows)
        print(f"departure_selection_policy={policy}")
        print(f"price_recovery_reload_count={recovery_count}")
        print("alert_nonstop_only=True")
        print(f"alert_max_offers={max_offers}")
        print(f"direct_offer_count={len(direct_rows)}")
        for index, row in enumerate(direct_rows, start=1):
            times = row.get("times") or []
            time_text = f"{times[0]} -> {times[1]}" if len(times) >= 2 else "time unknown"
            print(
                f"direct_offer_{index}={int(row['price']):,} KRW | "
                f"{row.get('airline') or 'airline unknown'} | {time_text}"
            )

        print("\n=== SUMMARY ===")
        print(f"query_contract={QUERY_CONTRACT}")
        print(f"lowest_direct_round_trip={int(direct_rows[0]['price']):,} KRW")
        print(f"displayed_direct_offers={len(direct_rows)}")
        print("connections_in_alert=0")
        print("booking_navigation_performed=False")
        print("external_checkout_navigation_performed=False")
        print(f"google_flights_result_url={search_url}")
        print("acceptance=GOOGLE_RESULTS_DIRECT_ONLY_SINGLE_LINK")
        print(f"artifact_dir={artifact_dir.resolve()}")

        if keep_open_seconds > 0:
            await page.wait_for_timeout(keep_open_seconds * 1000)
    except Exception:
        if page is not None and not page.is_closed():
            try:
                await base.save_debug(page, artifact_dir, "snapshot-results-probe-error")
            except Exception:
                pass
        raise
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if edge_process is not None and edge_process.poll() is None:
            try:
                edge_process.terminate()
                edge_process.wait(timeout=5)
            except Exception:
                pass


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("This acceptance probe is Windows-only")
    if base.env_bool("BROWSER_HEADLESS", False):
        raise SystemExit("This acceptance probe must run visible; BROWSER_HEADLESS=false")

    print("Google Flights direct-results alert acceptance")
    print(f"  production query contract: {QUERY_CONTRACT}")
    print("  Cheapest-first forced refresh: YES")
    print("  round-trip displayed price source: YES")
    print("  connections/stops excluded from alert: YES")
    print("  alert offer count configurable: YES")
    print("  Booking navigation: NO")
    print("  external checkout navigation: NO")
    print("  user-facing URL count: 1 (Google Flights results only)")

    playwright = await async_playwright().start()
    try:
        await _run_session(playwright)
    except Exception as exc:
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        raise SystemExit(2) from exc
    finally:
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())
