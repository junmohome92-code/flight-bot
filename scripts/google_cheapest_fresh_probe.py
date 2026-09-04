from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import warnings
from pathlib import Path


warnings.filterwarnings("ignore", category=SyntaxWarning, message="invalid escape sequence.*")
_SCRIPT = Path(__file__).with_name("google_ui_probe.py")
_SPEC = importlib.util.spec_from_file_location("google_ui_probe_cheapest_fresh", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Could not load google_ui_probe.py")
probe = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = probe
_SPEC.loader.exec_module(probe)


ACCEPTANCE_SEARCH_URL = (
    "https://www.google.com/travel/flights/search?"
    "tfs=CBwQAhoeEgoyMDI2LTA5LTE4agcIARIDQ0pKcgcIARIDVFBFGh4SCjIwMjYtMDktMjBqBwgBEgNUUEVyBwgBEgNDSkpAAUgBcAGCAQsI____________AZgBAQ"
    "&hl=en&gl=kr&curr=KRW"
)


async def wait_for_origin_input(page, timeout_ms: int) -> None:
    try:
        await page.locator("input[aria-label='Where from?']").first.wait_for(
            state="visible", timeout=timeout_ms
        )
    except Exception:
        # Let the existing generator produce the detailed failure/artifact.
        pass


async def open_cheapest_fresh(
    context,
    search_url: str,
    *,
    attempt: int,
    timeout_ms: int,
    price_wait_ms: int,
    artifact_dir: Path,
):
    print(f"\n=== BASE FRESH TAB ATTEMPT {attempt} ===")
    transition_page = await context.new_page()
    transition_page.set_default_timeout(timeout_ms)
    await transition_page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
    await probe.wait_for_results(transition_page, timeout_ms)
    print(f"base_fresh_url={transition_page.url}")

    cheapest_state = await probe.select_cheapest(transition_page)
    await transition_page.wait_for_timeout(700)
    cheapest_url = transition_page.url
    print(f"cheapest_transition_url={cheapest_url}")
    print(f"cheapest_transition_price_unavailable={'price unavailable' in (await transition_page.locator('body').inner_text()).lower()}")
    await probe.save_debug(transition_page, artifact_dir, f"cheapest-transition-{attempt}")

    if not cheapest_state.found or not cheapest_state.clicked:
        return transition_page, None, [], cheapest_state, cheapest_url, "CHEAPEST_TAB_NOT_READY"
    if cheapest_url == search_url:
        return transition_page, None, [], cheapest_state, cheapest_url, "CHEAPEST_URL_DID_NOT_CHANGE"

    print(f"\n=== CHEAPEST URL FRESH TAB {attempt} ===")
    page = await context.new_page()
    page.set_default_timeout(timeout_ms)
    await page.goto(cheapest_url, wait_until="domcontentloaded", timeout=timeout_ms)
    print(f"cheapest_fresh_url={page.url}")
    await probe.wait_for_results(page, timeout_ms)
    await probe.expand_results(page)
    prices = await probe.wait_for_price_candidates(page, price_wait_ms)
    body = await page.locator("body").inner_text()
    await probe.save_debug(page, artifact_dir, f"cheapest-fresh-{attempt}")
    await probe.print_session_diagnostics(page, f"CHEAPEST FRESH {attempt}")

    print(f"cheapest_fresh_price_unavailable={'price unavailable' in body.lower()}")
    print(f"price_candidates={len(prices)}")
    for index, candidate in enumerate(prices[:20], start=1):
        row = " | ".join(line.strip() for line in candidate.row_text.splitlines() if line.strip())[:850]
        print(f"#{index} {candidate.price:,} KRW | {row}")

    row_lowest = prices[0].price if prices else None
    price_match = probe.cheapest_price_consistent(cheapest_state.advertised_price, row_lowest)
    print(f"cheapest_price_match={price_match}")
    if cheapest_state.advertised_price is not None:
        print(f"cheapest_advertised={cheapest_state.advertised_price:,} KRW")
    if row_lowest is not None:
        print(f"cheapest_row_lowest={row_lowest:,} KRW")

    status = "OK" if prices and price_match else "NO_MATCHING_CHEAPEST_ROWS"
    return transition_page, page, prices, cheapest_state, cheapest_url, status


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("This acceptance probe is Windows-only")
    if probe.env_bool("BROWSER_HEADLESS", False):
        raise SystemExit("This acceptance probe must run visible; BROWSER_HEADLESS=false")

    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    price_wait_ms = int(os.getenv("GOOGLE_UI_PRICE_WAIT_MS", "20000"))
    max_attempts = max(1, min(int(os.getenv("GOOGLE_UI_MAX_ATTEMPTS", "3")), 5))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "8"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    direct_url = os.getenv("GOOGLE_UI_SEARCH_URL", "").strip()

    print("Google Flights two-stage fresh-tab Cheapest probe")
    print("  stage 1: fresh generated search URL")
    print("  stage 2: click Cheapest, capture tfu URL")
    print("  stage 3: open that Cheapest URL in ANOTHER fresh tab")
    print("  accept only flight-row scoped KRW prices")
    print(f"  direct generated URL supplied: {bool(direct_url)}")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = probe.free_local_port()
    edge_process = None
    playwright = await probe.async_playwright().start()
    browser = None
    last_page = None

    try:
        edge_process = probe.launch_native_edge(profile_dir, port)
        await probe.wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]

        if direct_url:
            search_url = direct_url
            print(f"generated_search_url={search_url}")
        else:
            generator = context.pages[0] if context.pages else await context.new_page()
            generator.set_default_timeout(timeout_ms)
            last_page = generator
            await generator.goto(probe.GOOGLE_FLIGHTS_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            await wait_for_origin_input(generator, min(timeout_ms, 15000))
            # generate_search_url intentionally reopens the landing page; the wait above
            # warms the first document and protects slower Edge/GitHub sessions.
            search_url = await probe.generate_search_url(generator, timeout_ms, artifact_dir)

        for attempt in range(1, max_attempts + 1):
            transition, page, prices, cheapest_state, cheapest_url, status = await open_cheapest_fresh(
                context,
                search_url,
                attempt=attempt,
                timeout_ms=timeout_ms,
                price_wait_ms=price_wait_ms,
                artifact_dir=artifact_dir,
            )
            last_page = page or transition
            if status == "OK":
                print("\n=== SUMMARY ===")
                print(f"fresh_tab_attempt={attempt}")
                print(f"generated_search_url={search_url}")
                print(f"cheapest_transition_url={cheapest_url}")
                print(f"ui_lowest={prices[0].price:,} KRW")
                print("acceptance=CHEAPEST_PRICE_VISIBLE_AFTER_SECOND_FRESH_TAB")
                print(f"artifact_dir={artifact_dir.resolve()}")
                if keep_open_seconds > 0 and page is not None:
                    await page.wait_for_timeout(keep_open_seconds * 1000)
                return

            print(f"attempt_status={status}")
            if page is not None:
                await page.close()
            if transition is not None:
                await transition.close()
            await asyncio.sleep(1.0)

        raise RuntimeError(
            "Cheapest transition URL was obtained, but no matching flight-row price appeared after second fresh navigation"
        )
    except Exception as exc:
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        if last_page is not None:
            await probe.save_debug(last_page, artifact_dir, "second-fresh-final-error")
        raise SystemExit(2) from exc
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        await playwright.stop()
        if edge_process is not None and edge_process.poll() is None:
            try:
                edge_process.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
