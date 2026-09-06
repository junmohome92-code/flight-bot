from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

try:  # direct Windows execution from scripts/
    import google_booking_pointer_probe as base
    import google_cheapest_capture as cheapest
except ImportError:  # pytest/import from repository root
    from scripts import google_booking_pointer_probe as base
    from scripts import google_cheapest_capture as cheapest


_PRICE_UNAVAILABLE_RE = re.compile(
    r"price(?:s)? unavailable|"
    r"가격\s*표시\s*불가|"
    r"가격\s*정보\s*없음|"
    r"가격\s*정보를\s*이용할\s*수\s*없|"
    r"가격을\s*이용할\s*수\s*없",
    re.I,
)
_KRW_READY_RE = re.compile(
    r"₩\s*[0-9][0-9,]*|[0-9][0-9,]*\s+(?:South Korean won|Korean won|KRW)",
    re.I,
)
_BLANK_URLS = {"", "about:blank", "edge://newtab/", "chrome://newtab/"}


class RecoverablePriceUnavailable(RuntimeError):
    """Google returned a transient no-price surface that merits a bounded retry."""


def is_target_closed_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = f"{type(current).__name__}: {current}".lower()
        if "targetclosederror" in text or "target page, context or browser has been closed" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_blankish(page: Page) -> bool:
    if page.is_closed():
        return False
    return page.url in _BLANK_URLS or page.url.startswith("edge://newtab") or page.url.startswith("chrome://newtab")


async def claim_initial_page(context: BrowserContext, timeout_ms: int) -> Page:
    """Reuse Edge's startup tab instead of creating an unnecessary second tab."""
    live = [page for page in context.pages if not page.is_closed()]
    chosen: Page | None = None

    for page in reversed(live):
        if "google.com/travel/flights" in page.url:
            chosen = page
            break
    if chosen is None:
        chosen = next((page for page in live if _is_blankish(page)), None)
    if chosen is None and live:
        chosen = live[0]
    if chosen is None:
        chosen = await context.new_page()
        print("initial_page_claim=opened-new-tab")
    else:
        print(f"initial_page_claim=reused-existing-tab url={chosen.url}")

    chosen.set_default_timeout(timeout_ms)

    # The acceptance profile is bot-dedicated. Close only redundant blank/newtab
    # pages; never close an unrelated non-blank page.
    closed_blanks = 0
    for other in list(context.pages):
        if other is chosen or other.is_closed() or not _is_blankish(other):
            continue
        try:
            await other.close()
            closed_blanks += 1
        except Exception:
            pass
    print(f"redundant_blank_tabs_closed={closed_blanks}")
    print(f"browser_tab_count_after_claim={len([p for p in context.pages if not p.is_closed()])}")
    return chosen


async def search_surface_state(page: Page) -> tuple[str, str]:
    """Classify readiness only; body-wide prices are never used as candidates."""
    if page.is_closed():
        return "closed", ""
    try:
        body = await page.locator("body").inner_text(timeout=2500)
    except Exception as exc:
        if is_target_closed_error(exc) or page.is_closed():
            return "closed", ""
        return "loading", ""

    text = body[:40000]
    if _KRW_READY_RE.search(text):
        return "ready", text
    if _PRICE_UNAVAILABLE_RE.search(text):
        return "unavailable", text
    return "loading", text


async def reopen_search_page(
    context: BrowserContext,
    previous: Page | None,
    search_url: str,
    timeout_ms: int,
) -> Page:
    """Recover into an existing tab whenever possible; open a new tab last."""
    for candidate in reversed(context.pages):
        if candidate.is_closed():
            continue
        if "google.com/travel/flights" in candidate.url:
            candidate.set_default_timeout(timeout_ms)
            if candidate.url != search_url:
                await candidate.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
            print("page_recovery=reused-live-google-flights-tab")
            return candidate

    for candidate in context.pages:
        if _is_blankish(candidate):
            candidate.set_default_timeout(timeout_ms)
            await candidate.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
            print("page_recovery=reused-blank-tab")
            return candidate

    if previous is not None and not previous.is_closed():
        previous.set_default_timeout(timeout_ms)
        await previous.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print("page_recovery=reused-active-tab")
        return previous

    replacement = await context.new_page()
    replacement.set_default_timeout(timeout_ms)
    await replacement.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
    print("page_recovery=opened-replacement-tab")
    return replacement


async def reload_or_reopen(
    context: BrowserContext,
    page: Page,
    search_url: str,
    timeout_ms: int,
) -> Page:
    if page.is_closed():
        return await reopen_search_page(context, page, search_url, timeout_ms)
    try:
        await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        return page
    except Exception as exc:
        if not is_target_closed_error(exc):
            raise
        return await reopen_search_page(context, page, search_url, timeout_ms)


async def ensure_search_price_ready(
    context: BrowserContext,
    page: Page,
    search_url: str,
    *,
    timeout_ms: int,
    ready_wait_ms: int = 8000,
    max_reloads: int = 2,
    artifact_dir: Path | None = None,
) -> tuple[Page, int]:
    reloads = 0
    cycle = 0
    while True:
        cycle += 1
        deadline = asyncio.get_running_loop().time() + max(1000, ready_wait_ms) / 1000
        unavailable_since: float | None = None

        while asyncio.get_running_loop().time() < deadline:
            state, _ = await search_surface_state(page)
            if state == "ready":
                print(f"price_surface_state=ready recovery_reloads={reloads}")
                return page, reloads
            if state == "closed":
                print("price_surface_state=target-closed")
                page = await reopen_search_page(context, page, search_url, timeout_ms)
                break
            if state == "unavailable":
                if unavailable_since is None:
                    unavailable_since = time.monotonic()
                    print(f"price_unavailable_detected=True cycle={cycle}")
                    if artifact_dir is not None and not page.is_closed():
                        await base.save_debug(page, artifact_dir, f"price-unavailable-before-reload-{reloads + 1}")
                if time.monotonic() - unavailable_since >= 0.45:
                    break
            else:
                unavailable_since = None
            await asyncio.sleep(0.10)

        if reloads >= max_reloads:
            raise RecoverablePriceUnavailable(
                f"Google Flights still has no usable KRW price after {reloads} recovery reload(s)"
            )
        reloads += 1
        print(f"price_unavailable_recovery_reload={reloads}/{max_reloads}")
        page = await reload_or_reopen(context, page, search_url, timeout_ms)
        await asyncio.sleep(0.35)


async def prepare_cheapest_surface(
    context: BrowserContext,
    page: Page,
    search_url: str,
    *,
    timeout_ms: int,
    selection_wait_ms: int,
    ready_wait_ms: int,
    recovery_reloads: int,
    artifact_dir: Path | None = None,
) -> tuple[Page, int]:
    """Enter Cheapest first, then perform the user's proven full-refresh recovery."""
    print("\n=== CHEAPEST WARM-UP + FULL REFRESH ===")
    _, warm_clicked = await cheapest.ensure_cheapest_selected(page, selection_wait_ms)
    print("cheapest_warmup_selected=True")
    print(f"cheapest_warmup_clicked={warm_clicked}")
    if artifact_dir is not None and not page.is_closed():
        await base.save_debug(page, artifact_dir, "cheapest-before-forced-refresh")

    # This refresh is intentional and unconditional. The live Windows behavior
    # showed that Google can populate Cheapest controls yet leave prices
    # unavailable until the entire selected Cheapest surface is refreshed.
    print("cheapest_selected_full_reload=1")
    page = await reload_or_reopen(context, page, search_url, timeout_ms)
    await asyncio.sleep(0.35)

    page, recovery_count = await ensure_search_price_ready(
        context,
        page,
        search_url,
        timeout_ms=timeout_ms,
        ready_wait_ms=ready_wait_ms,
        max_reloads=recovery_reloads,
        artifact_dir=artifact_dir,
    )
    page.set_default_timeout(timeout_ms)

    # Full reload may preserve Cheapest state or may reset to Best depending on
    # Google's current client state. Re-query strong semantics and click only if
    # Cheapest is no longer selected.
    _, post_clicked = await cheapest.ensure_cheapest_selected(page, selection_wait_ms)
    print("cheapest_post_reload_selected=True")
    print(f"cheapest_post_reload_reclicked={post_clicked}")
    print(f"price_recovery_reload_count={recovery_count}")
    return page, recovery_count


def print_candidate(prefix: str, candidate: dict, state: dict, policy: str) -> None:
    values = [
        int(item["price"])
        for item in cheapest.phase_candidates(state, str(candidate.get("phase")))
        if item.get("price") is not None
    ]
    prices = sorted(set(values))
    print(f"{prefix}_selected={int(candidate['price']):,} KRW")
    print(f"{prefix}_selection_policy={policy}")
    print(f"{prefix}_price_kind={candidate.get('priceKind') or 'displayed'}")
    if prefix == "departure":
        print(f"departure_cheapest_tab_selected={state.get('cheapestSelected')}")
        print(f"departure_cheapest_loading={state.get('cheapestLoading')}")
        print(f"departure_advertised={state.get('advertisedPrice') if state.get('advertisedPrice') is not None else 'unknown'}")
    print(f"{prefix}_candidate_count={len(cheapest.phase_candidates(state, str(candidate.get('phase'))))}")
    print(f"{prefix}_candidate_prices={','.join(f'{value:,}' for value in prices[:24])}")
    print(f"{prefix}_anchor_mode={candidate.get('anchorMode')}")
    print(f"{prefix}_source_text={str(candidate.get('sourceText') or '')[:220]}")
    row = " | ".join(str(candidate.get("rowText") or "").splitlines())[:1100]
    print(f"{prefix}_row={row}")


async def _run_session(playwright, *, session_attempt: int) -> None:
    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    selection_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_SELECTION_WAIT_MS", "25000")))
    booking_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_BOOKING_WAIT_MS", "15000")))
    departure_capture_ms = max(1500, int(os.getenv("GOOGLE_UI_DEPARTURE_CAPTURE_MS", "3500")))
    return_capture_ms = max(300, int(os.getenv("GOOGLE_UI_RETURN_CAPTURE_MS", "900")))
    ready_wait_ms = max(2500, int(os.getenv("GOOGLE_UI_PRICE_READY_WAIT_MS", "8000")))
    recovery_reloads = max(0, int(os.getenv("GOOGLE_UI_PRICE_RELOADS", "2")))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "8"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    search_url = os.getenv("GOOGLE_UI_SEARCH_URL", base.ACCEPTANCE_BASE_URL).strip()

    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = base.free_local_port()
    edge_process = None
    browser = None
    page: Page | None = None

    try:
        print(f"browser_session_attempt={session_attempt}")
        edge_process = base.launch_edge_blank(profile_dir, port)
        await base.wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        browser.on("disconnected", lambda: print("lifecycle_browser_disconnected=True"))
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]
        context.on("page", lambda p: print(f"lifecycle_new_page={p.url[:180]}"))

        dom_capture = base._DOM_CAPTURE_PATH.read_text(encoding="utf-8")
        init_script = (
            "window.__flightBotInitConfig = "
            + json.dumps({"origin": base.ORIGIN, "destination": base.DESTINATION})
            + ";\n"
            + dom_capture
        )
        await context.add_init_script(init_script)

        page = await claim_initial_page(context, timeout_ms)
        page.on("close", lambda: print("lifecycle_active_page_closed=True"))
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"selection_url={page.url}")

        page, _ = await prepare_cheapest_surface(
            context,
            page,
            search_url,
            timeout_ms=timeout_ms,
            selection_wait_ms=selection_wait_ms,
            ready_wait_ms=ready_wait_ms,
            recovery_reloads=recovery_reloads,
            artifact_dir=artifact_dir,
        )

        print("\n=== SETTLED CHEAPEST DEPARTURE ===")
        departure, dep_state, dep_policy = await cheapest.wait_for_candidate(
            page,
            phase="departure",
            origin=base.ORIGIN,
            destination=base.DESTINATION,
            timeout_ms=selection_wait_ms,
            capture_window_ms=departure_capture_ms,
            allow_missing_route=True,
            min_price=base.MIN_KRW_PRICE,
        )
        await base.save_json(artifact_dir / "snapshot-departure-state.json", dep_state)
        if not departure:
            surface, _ = await search_surface_state(page)
            if surface == "unavailable":
                raise RecoverablePriceUnavailable("Google returned Price unavailable after Cheapest refresh")
            advertised = dep_state.get("advertisedPrice")
            eligible = base.eligible_candidates(
                cheapest.phase_candidates(dep_state, "departure"),
                origin=base.ORIGIN,
                destination=base.DESTINATION,
                allow_missing_route=True,
                min_price=base.MIN_KRW_PRICE,
            )
            prices = sorted({int(item["price"]) for item in eligible if item.get("price") is not None})
            print(f"departure_cheapest_tab_selected={dep_state.get('cheapestSelected')}")
            print(f"departure_cheapest_loading={dep_state.get('cheapestLoading')}")
            print(f"departure_advertised={advertised if advertised is not None else 'unknown'}")
            print(f"departure_candidate_prices={prices}")
            await base.save_debug(page, artifact_dir, "departure-capture-failed")
            raise RuntimeError("Cheapest was selected and refreshed, but its settled trustworthy lowest row was not captured")
        print_candidate("departure", departure, dep_state, dep_policy)

        await base.set_phase(page, "returning")
        mode = await base.click_captured_candidate(page, departure)
        print(f"departure_pointer_click_mode={mode}")
        print("departure_pointer_click_sent=True")
        returning_page = await base.wait_for_returning_page(page, selection_wait_ms)
        print(f"departure_navigation_confirmed={returning_page}")
        print(f"current_url_after_departure={page.url}")
        if not returning_page:
            await base.save_debug(page, artifact_dir, "departure-navigation-failed")
            raise RuntimeError("Departure click did not reach Returning flights")

        returning, ret_state, ret_policy = await cheapest.wait_for_candidate(
            page,
            phase="returning",
            origin=base.DESTINATION,
            destination=base.ORIGIN,
            timeout_ms=selection_wait_ms,
            capture_window_ms=return_capture_ms,
            allow_missing_route=True,
            min_price=base.MIN_RETURN_ADJUSTMENT,
        )
        await base.save_json(artifact_dir / "snapshot-return-state.json", ret_state)
        if not returning:
            body = await page.locator("body").inner_text()
            eligible = base.eligible_candidates(
                cheapest.phase_candidates(ret_state, "returning"),
                origin=base.DESTINATION,
                destination=base.ORIGIN,
                allow_missing_route=True,
                min_price=base.MIN_RETURN_ADJUSTMENT,
            )
            print(f"body_has_returning={'returning flights' in body.lower() or '귀국 항공편' in body}")
            print(f"return_candidate_prices={sorted({int(i['price']) for i in eligible if i.get('price') is not None})}")
            await base.save_debug(page, artifact_dir, "return-capture-failed")
            raise RuntimeError("Returning flights loaded, but no trustworthy return price row was captured")
        if not base.flight_card_is_specific(
            str(returning.get("rowText") or ""),
            base.DESTINATION,
            base.ORIGIN,
            allow_missing_route=True,
            min_price=base.MIN_RETURN_ADJUSTMENT,
        ):
            raise RuntimeError("Return snapshot was not one specific return flight card")
        print_candidate("return", returning, ret_state, ret_policy)

        await base.set_phase(page, "done")
        mode = await base.click_captured_candidate(page, returning)
        print(f"return_pointer_click_mode={mode}")
        print("return_pointer_click_sent=True")
        await page.wait_for_timeout(700)

        print("\n=== BOOKING OPTIONS ===")
        deadline = asyncio.get_running_loop().time() + booking_wait_ms / 1000
        options: list[dict] = []
        marker = False
        while asyncio.get_running_loop().time() < deadline:
            marker, options = await base.booking_options(page)
            if marker and options:
                break
            await page.wait_for_timeout(150)
        print(f"booking_options_marker={marker}")
        print(f"booking_option_candidates={len(options)}")
        for index, option in enumerate(options[:10], start=1):
            text = " | ".join(str(option.get("text") or "").splitlines())[:1000]
            print(f"booking_option_{index}={int(option['price']):,} KRW | {text}")
        await base.save_json(artifact_dir / "snapshot-booking-options.json", options)
        await base.save_debug(page, artifact_dir, "snapshot-booking-final")
        if not marker or not options:
            raise RuntimeError("Departure/return selected, but no Booking-options-scoped KRW CTA was confirmed")

        print("\n=== SUMMARY ===")
        print(f"departure_observed={int(departure['price']):,} KRW")
        print(f"return_displayed_price={int(returning['price']):,} KRW")
        print(f"return_price_kind={returning.get('priceKind') or 'displayed'}")
        print(f"google_booking_option={int(options[0]['price']):,} KRW")
        print("observed=True")
        print("booking_option_visible=True")
        print("external_checkout_verified=False")
        print("verified=False")
        print("acceptance=GOOGLE_BOOKING_OPTION_REACHED_WITH_NAVIGATION_SAFE_CAPTURE")
        print(f"artifact_dir={artifact_dir.resolve()}")

        if keep_open_seconds > 0:
            await page.wait_for_timeout(keep_open_seconds * 1000)
    except Exception:
        if page is not None and not page.is_closed():
            try:
                await base.save_json(artifact_dir / "snapshot-error-state.json", await cheapest.capture_state(page))
                await base.save_debug(page, artifact_dir, "snapshot-probe-error")
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
    if not base._DOM_CAPTURE_PATH.is_file():
        raise SystemExit(f"Missing DOM capture script: {base._DOM_CAPTURE_PATH}")

    browser_restarts = max(0, int(os.getenv("GOOGLE_UI_BROWSER_RESTARTS", "1")))

    print("Google Flights canonical Cheapest-first refresh + Booking acceptance")
    print("  canonical live entrypoint: YES")
    print("  V5/V6/V7 monkey-patch chain in active path: NO")
    print("  existing Edge startup tab reused: YES")
    print("  Cheapest selected before forced full refresh: YES")
    print("  forced full refresh after Cheapest: YES")
    print("  extra Price unavailable recovery reloads: YES")
    print("  TargetClosed full browser-session restart: YES")
    print("  same Edge profile retained across retries: YES")
    print("  actual pointer-event boundary: YES")
    print("  advertised + candidate-low stability gate: YES")
    print("  stale pointer coordinate click: NO")
    print("  page-wide price minimum: NO")
    print("  external seller checkout verification: NO")

    playwright = await async_playwright().start()
    last_exc: BaseException | None = None
    try:
        for attempt in range(1, browser_restarts + 2):
            try:
                await _run_session(playwright, session_attempt=attempt)
                return
            except Exception as exc:
                last_exc = exc
                recoverable = is_target_closed_error(exc) or isinstance(exc, RecoverablePriceUnavailable)
                print(f"\nSESSION FAILED: {type(exc).__name__}: {exc}")
                if recoverable and attempt <= browser_restarts:
                    reason = "target-closed" if is_target_closed_error(exc) else "price-unavailable"
                    print(f"browser_session_restart={attempt}/{browser_restarts} reason={reason}")
                    await asyncio.sleep(0.75)
                    continue
                break
    finally:
        await playwright.stop()

    if last_exc is None:
        raise SystemExit(2)
    print(f"\nPROBE FAILED: {type(last_exc).__name__}: {last_exc}")
    raise SystemExit(2) from last_exc


if __name__ == "__main__":
    asyncio.run(main())
