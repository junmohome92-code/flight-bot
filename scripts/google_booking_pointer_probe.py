from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import Locator, Page, async_playwright

from flight_bot.google_ui_contract import (
    MAX_KRW_PRICE,
    MIN_KRW_PRICE,
    MIN_RETURN_ADJUSTMENT,
    choose_lowest_candidate,
    departure_capture_ready,
    eligible_candidates,
    flight_card_is_specific,
)


ACCEPTANCE_BASE_URL = (
    "https://www.google.com/travel/flights/search?"
    "tfs=CBwQAhoeEgoyMDI2LTA5LTE4agcIARIDQ0pKcgcIARIDVFBFGh4SCjIwMjYtMDktMjBqBwgBEgNUUEVyBwgBEgNDSkpAAUgBcAGCAQsI____________AZgBAQ"
    "&hl=en&gl=kr&curr=KRW"
)
ORIGIN = "CJJ"
DESTINATION = "TPE"
_CHEAPEST_RE = re.compile(r"(?:Cheapest|최저가)", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b", re.I)
_DOM_CAPTURE_PATH = Path(__file__).with_name("google_dom_capture.js")


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_windows_edge() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def launch_edge_blank(profile_dir: Path, port: int) -> subprocess.Popen:
    edge = find_windows_edge()
    if edge is None:
        raise RuntimeError("Microsoft Edge executable was not found")
    args = [
        str(edge),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=ko-KR",
        "about:blank",
    ]
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


async def wait_for_cdp(port: int, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.2)
    raise RuntimeError(f"Edge remote debugging port {port} did not open")


async def save_debug(page: Page, artifact_dir: Path, stem: str) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(artifact_dir / f"{stem}.png"), full_page=True)
    except Exception:
        pass
    try:
        (artifact_dir / f"{stem}.txt").write_text(await page.locator("body").inner_text(), encoding="utf-8")
    except Exception:
        pass
    try:
        (artifact_dir / f"{stem}.html").write_text(await page.content(), encoding="utf-8")
    except Exception:
        pass


async def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def first_visible(locator: Locator) -> Locator | None:
    for index in range(await locator.count()):
        item = locator.nth(index)
        try:
            if await item.is_visible():
                return item
        except Exception:
            pass
    return None


async def capture_state(page: Page) -> dict:
    try:
        value = await page.evaluate(
            """() => {
                const s = window.__flightBotCaptureV4;
                if (!s) return {phase: 'missing', candidates: []};
                return {
                    phase: s.phase,
                    phaseStartedAtMs: s.phaseStartedAtMs,
                    advertisedPrice: s.advertisedPrice,
                    advertisedChangedAtMs: s.advertisedChangedAtMs,
                    cheapestRequestedAtMs: s.cheapestRequestedAtMs,
                    cheapestSelected: s.cheapestSelected,
                    cheapestSelectedAtMs: s.cheapestSelectedAtMs,
                    cheapestText: s.cheapestText,
                    cheapestLoading: s.cheapestLoading,
                    returningMarker: s.returningMarker,
                    returningMarkerAtMs: s.returningMarkerAtMs,
                    candidates: (s.candidates || []).map(item => ({...item})),
                    rejectedBroad: s.rejectedBroad || 0,
                    rejectedSource: s.rejectedSource || 0,
                    nowMs: Math.round(performance.now() * 10) / 10,
                    url: location.href
                };
            }"""
        )
        return value if isinstance(value, dict) else {"phase": "invalid", "candidates": []}
    except Exception:
        return {"phase": "unavailable", "candidates": []}


async def set_phase(page: Page, phase: str, *, cheapest_requested: bool = False) -> None:
    await page.evaluate(
        """({phase, requested}) => {
            try { sessionStorage.setItem('__flightBotPointerPhaseV4', phase); } catch (_) {}
            const s = window.__flightBotCaptureV4;
            if (!s) return;
            s.phase = phase;
            s.phaseStartedAtMs = performance.now();
            if (requested) s.cheapestRequestedAtMs = performance.now();
            if (phase === 'returning') {
                s.returningMarker = false;
                s.returningMarkerAtMs = null;
            }
        }""",
        {"phase": phase, "requested": cheapest_requested},
    )


async def select_cheapest_tab(page: Page, timeout_ms: int) -> dict:
    # Start the departure phase *before* the click. Capture is always active, so
    # a price that appears during the tab transition cannot be missed.
    await set_phase(page, "departure", cheapest_requested=True)

    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    control: Locator | None = None
    while asyncio.get_running_loop().time() < deadline and control is None:
        for locator in (
            page.get_by_role("tab", name=_CHEAPEST_RE),
            page.get_by_role("button", name=_CHEAPEST_RE),
            page.get_by_text(_CHEAPEST_RE),
        ):
            control = await first_visible(locator)
            if control is not None:
                break
        if control is None:
            await page.wait_for_timeout(50)
    if control is None:
        raise RuntimeError("Cheapest/최저가 tab was not found")

    text_before = (await control.inner_text()).strip()
    await control.click(timeout=5000)
    clicked_at = time.monotonic()
    state: dict = {}
    while time.monotonic() - clicked_at < 5.0:
        try:
            state = await control.evaluate(
                """el => {
                    const host = el.closest('[role="tab"], button, [role="button"]') || el;
                    return {
                        selected: host.getAttribute('aria-selected'),
                        pressed: host.getAttribute('aria-pressed'),
                        text: (host.innerText || host.textContent || '').trim()
                    };
                }"""
            )
        except Exception:
            state = {}
        if state.get("selected") == "true" or state.get("pressed") == "true":
            break
        await page.wait_for_timeout(25)

    if state.get("selected") != "true" and state.get("pressed") != "true":
        raise RuntimeError("Cheapest/최저가 control was clicked but never became selected")

    # The MutationObserver normally sees aria-selected. Explicitly stamp the
    # boundary too, so a replaced tab DOM node cannot erase the transition.
    await page.evaluate(
        """() => {
            const s = window.__flightBotCaptureV4;
            if (!s) return;
            if (!s.cheapestSelected) {
                s.cheapestSelected = true;
                s.cheapestSelectedAtMs = performance.now();
            }
        }"""
    )
    print("cheapest_tab_found=True")
    print("cheapest_tab_clicked=True")
    print("cheapest_tab_selected=True")
    print(f"cheapest_tab_text_before={text_before[:300]}")
    print(f"cheapest_tab_text_after={str(state.get('text') or '')[:300]}")
    return state


def phase_candidates(state: dict, phase: str) -> list[dict]:
    raw = [
        item for item in (state.get("candidates") or [])
        if isinstance(item, dict) and item.get("phase") == phase
    ]
    if phase == "departure":
        requested = float(state.get("cheapestRequestedAtMs") or 0.0)
        selected = float(state.get("cheapestSelectedAtMs") or 0.0)
        boundary = max(requested, max(0.0, selected - 350.0))
        return [item for item in raw if float(item.get("seenAtMs") or 0.0) >= boundary]
    if phase == "returning":
        marker = float(state.get("returningMarkerAtMs") or 0.0)
        if marker > 0:
            return [item for item in raw if float(item.get("seenAtMs") or 0.0) >= max(0.0, marker - 300.0)]
    return raw


async def wait_for_candidate(
    page: Page,
    *,
    phase: str,
    origin: str,
    destination: str,
    timeout_ms: int,
    capture_window_ms: int,
    allow_missing_route: bool,
    min_price: int,
) -> tuple[dict, dict, str]:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    latest: dict = {"phase": "unknown", "candidates": []}
    last_lowest: int | None = None
    low_changed_at = time.monotonic()

    while asyncio.get_running_loop().time() < deadline:
        latest = await capture_state(page)
        candidates = phase_candidates(latest, phase)
        eligible = eligible_candidates(
            candidates,
            origin=origin,
            destination=destination,
            allow_missing_route=allow_missing_route,
            min_price=min_price,
        )
        current_lowest = int(eligible[0]["price"]) if eligible else None
        if current_lowest != last_lowest:
            last_lowest = current_lowest
            low_changed_at = time.monotonic()
        low_stable_ms = (time.monotonic() - low_changed_at) * 1000

        now_ms = float(latest.get("nowMs") or 0.0)
        if phase == "departure":
            selected_ms = float(latest.get("cheapestSelectedAtMs") or 0.0)
            started_ms = selected_ms or float(latest.get("phaseStartedAtMs") or now_ms)
            elapsed_ms = max(0.0, now_ms - started_ms)
            raw_advertised = latest.get("advertisedPrice")
            advertised = int(raw_advertised) if raw_advertised is not None else None
            changed_ms = float(latest.get("advertisedChangedAtMs") or started_ms)
            advertised_stable_ms = max(0.0, now_ms - changed_ms)
            ready = departure_capture_ready(
                candidate_count=len(eligible),
                elapsed_ms=elapsed_ms,
                advertised_stable_ms=advertised_stable_ms,
                candidate_low_stable_ms=low_stable_ms,
                loading=bool(latest.get("cheapestLoading", True)),
                capture_window_ms=capture_window_ms,
                advertised_price=advertised,
                candidate_lowest=current_lowest,
            )
            if ready:
                chosen = choose_lowest_candidate(
                    candidates,
                    origin=origin,
                    destination=destination,
                    advertised_price=advertised,
                    allow_missing_route=False,
                    min_price=MIN_KRW_PRICE,
                )
                if chosen is not None:
                    return dict(chosen), latest, "explicit-cheapest-settled-lowest"
        else:
            marker_ms = float(latest.get("returningMarkerAtMs") or 0.0)
            started_ms = marker_ms or float(latest.get("phaseStartedAtMs") or now_ms)
            elapsed_ms = max(0.0, now_ms - started_ms)
            if eligible and elapsed_ms >= capture_window_ms and low_stable_ms >= 250:
                chosen = choose_lowest_candidate(
                    candidates,
                    origin=origin,
                    destination=destination,
                    allow_missing_route=allow_missing_route,
                    min_price=min_price,
                )
                if chosen is not None:
                    return dict(chosen), latest, "return-settled-lowest"
        await page.wait_for_timeout(15)
    return {}, latest, "timeout"


def _candidate_signature(row_text: str) -> dict:
    normalized = row_text.replace("–", "-").replace("—", "-").replace("‑", "-").replace("−", "-")
    times = _TIME_RE.findall(normalized)[:2]
    route_match = re.search(r"\b[A-Z]{3}\s*-\s*[A-Z]{3}\b", normalized.upper())
    return {"times": times, "route": route_match.group(0).replace(" ", "") if route_match else ""}


async def _coordinate_still_matches(page: Page, x: float, y: float, row_text: str) -> bool:
    signature = _candidate_signature(row_text)
    if len(signature["times"]) < 2:
        return False
    try:
        return bool(
            await page.evaluate(
                """({x, y, times, route}) => {
                    let node = document.elementFromPoint(x, y);
                    for (let depth = 0; depth < 14 && node; depth += 1, node = node.parentElement) {
                        const text = (node.innerText || node.textContent || '')
                          .replace(/[–—‑−]/g, '-').replace(/\s+/g, ' ').toUpperCase();
                        if (!text || text.length > 1800) continue;
                        const hasTimes = times.every(t => text.includes(String(t).toUpperCase()));
                        const hasRoute = !route || text.includes(route.toUpperCase());
                        const broad = /flight search|search results|all filters|top departing flights|other departing flights/i.test(text);
                        if (hasTimes && hasRoute && !broad) return true;
                    }
                    return false;
                }""",
                {"x": x, "y": y, **signature},
            )
        )
    except Exception:
        return False


async def click_captured_candidate(page: Page, candidate: dict) -> str:
    candidate_id = str(candidate.get("id") or "")
    row_text = str(candidate.get("rowText") or "")
    points: list[tuple[str, float, float]] = []

    if candidate_id:
        locator = page.locator(f'[data-flight-bot-pointer-anchor-id="{candidate_id}"]')
        try:
            if await locator.count():
                box = await locator.first.bounding_box()
                if box and box["width"] > 2 and box["height"] > 2:
                    points.append(("live-marked-anchor", box["x"] + box["width"] / 2, box["y"] + box["height"] / 2))
        except Exception:
            pass

    for mode, value in (
        ("captured-anchor-coordinate", candidate.get("anchorRect") or {}),
        ("captured-price-coordinate", candidate.get("sourceRect") or {}),
    ):
        try:
            x = float(value.get("x") or 0.0)
            y = float(value.get("y") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if x > 0 and y > 0:
            points.append((mode, x, y))

    for mode, x, y in points:
        if await _coordinate_still_matches(page, x, y, row_text):
            await page.mouse.click(x, y, delay=18)
            return mode
    raise RuntimeError("Captured flight pointer no longer resolves to the same flight card; refusing stale-coordinate click")


async def wait_for_returning_page(page: Page, timeout_ms: int) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        try:
            body = await page.locator("body").inner_text()
        except Exception:
            await page.wait_for_timeout(30)
            continue
        if "returning flights" in body.lower() or "귀국 항공편" in body:
            # On a full navigation the init script recreated state automatically
            # with capture active. Stamp the marker as a fallback in case the
            # periodic scanner has not observed the text yet.
            try:
                await page.evaluate(
                    """() => {
                        const s = window.__flightBotCaptureV4;
                        if (!s) return;
                        s.phase = 'returning';
                        if (!s.returningMarker) {
                            s.returningMarker = true;
                            s.returningMarkerAtMs = performance.now();
                        }
                    }"""
                )
            except Exception:
                pass
            return True
        await page.wait_for_timeout(40)
    return False


async def booking_options(page: Page) -> tuple[bool, list[dict]]:
    try:
        body = await page.locator("body").inner_text()
    except Exception:
        return False, []
    marker = "booking options" in body.lower() or "예약 옵션" in body
    if not marker:
        return False, []

    try:
        rows = await page.evaluate(
            r"""() => {
                const symbolRe = /₩\s*([0-9][0-9,]*)/g;
                const wonRe = /([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)/gi;
                const actionRe = /book|continue|select|예약|계속|선택/i;
                const results = [];
                function prices(text) {
                    const found = [];
                    symbolRe.lastIndex = 0; wonRe.lastIndex = 0;
                    let m;
                    while ((m = symbolRe.exec(text || '')) !== null) found.push(Number(m[1].replaceAll(',', '')));
                    while ((m = wonRe.exec(text || '')) !== null) found.push(Number(m[1].replaceAll(',', '')));
                    return [...new Set(found)].filter(v => Number.isFinite(v) && v >= 50000 && v <= 1500000);
                }
                for (const control of document.querySelectorAll('a, button, [role="button"], [role="link"]')) {
                    const controlText = (control.innerText || control.textContent || control.getAttribute('aria-label') || '').trim();
                    if (!actionRe.test(controlText)) continue;
                    let node = control;
                    for (let depth = 0; depth < 8 && node; depth += 1, node = node.parentElement) {
                        const text = (node.innerText || node.textContent || '').trim();
                        if (!text || text.length > 3500) continue;
                        const values = prices(text);
                        if (!values.length) continue;
                        results.push({price: Math.min(...values), text: text.slice(0, 3000), href: control.href || null});
                        break;
                    }
                    if (results.length >= 30) break;
                }
                return results;
            }"""
        )
    except Exception:
        return marker, []

    unique: dict[tuple[int, str, str | None], dict] = {}
    for item in rows if isinstance(rows, list) else []:
        try:
            price = int(item.get("price"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not MIN_KRW_PRICE <= price <= MAX_KRW_PRICE:
            continue
        text = str(item.get("text") or "").strip()
        href = str(item.get("href")) if item.get("href") else None
        unique[(price, text, href)] = item
    return marker, sorted(unique.values(), key=lambda item: int(item["price"]))


def print_candidate(prefix: str, candidate: dict, state: dict, policy: str) -> None:
    values = [
        int(item["price"])
        for item in phase_candidates(state, str(candidate.get("phase")))
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
    print(f"{prefix}_candidate_count={len(phase_candidates(state, str(candidate.get('phase'))))}")
    print(f"{prefix}_candidate_prices={','.join(f'{value:,}' for value in prices[:24])}")
    print(f"{prefix}_anchor_mode={candidate.get('anchorMode')}")
    print(f"{prefix}_source_text={str(candidate.get('sourceText') or '')[:220]}")
    row = " | ".join(str(candidate.get("rowText") or "").splitlines())[:1100]
    print(f"{prefix}_row={row}")


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("This acceptance probe is Windows-only")
    if env_bool("BROWSER_HEADLESS", False):
        raise SystemExit("This acceptance probe must run visible; BROWSER_HEADLESS=false")
    if not _DOM_CAPTURE_PATH.is_file():
        raise SystemExit(f"Missing DOM capture script: {_DOM_CAPTURE_PATH}")

    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    selection_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_SELECTION_WAIT_MS", "25000")))
    booking_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_BOOKING_WAIT_MS", "15000")))
    departure_capture_ms = max(1500, int(os.getenv("GOOGLE_UI_DEPARTURE_CAPTURE_MS", "3500")))
    return_capture_ms = max(300, int(os.getenv("GOOGLE_UI_RETURN_CAPTURE_MS", "900")))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "8"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    search_url = os.getenv("GOOGLE_UI_SEARCH_URL", ACCEPTANCE_BASE_URL).strip()

    print("Google Flights navigation-safe Cheapest + transient snapshot + Booking probe")
    print("  capture active before Cheapest click: YES")
    print("  characterData/text-node mutations captured: YES")
    print("  actual Cheapest/최저가 control click: YES")
    print("  Cheapest selection confirmation: YES")
    print("  advertised + candidate-low stability gate: YES")
    print("  full-navigation Returning capture survives: YES")
    print("  stale pointer coordinate click: NO")
    print("  Booking marker required: YES")
    print("  external seller checkout verification: NO")
    print("  page-wide price minimum: NO")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = free_local_port()
    edge_process: subprocess.Popen | None = None
    playwright = await async_playwright().start()
    browser = None
    page: Page | None = None

    try:
        edge_process = launch_edge_blank(profile_dir, port)
        await wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]
        dom_capture = _DOM_CAPTURE_PATH.read_text(encoding="utf-8")
        init_script = (
            "window.__flightBotInitConfig = "
            + json.dumps({"origin": ORIGIN, "destination": DESTINATION})
            + ";\n"
            + dom_capture
        )
        await context.add_init_script(init_script)

        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"selection_url={page.url}")

        print("\n=== EXPLICIT CHEAPEST SELECTION ===")
        await select_cheapest_tab(page, selection_wait_ms)

        departure, dep_state, dep_policy = await wait_for_candidate(
            page,
            phase="departure",
            origin=ORIGIN,
            destination=DESTINATION,
            timeout_ms=selection_wait_ms,
            capture_window_ms=departure_capture_ms,
            allow_missing_route=False,
            min_price=MIN_KRW_PRICE,
        )
        await save_json(artifact_dir / "snapshot-departure-state.json", dep_state)
        if not departure:
            advertised = dep_state.get("advertisedPrice")
            eligible = eligible_candidates(
                phase_candidates(dep_state, "departure"),
                origin=ORIGIN,
                destination=DESTINATION,
                min_price=MIN_KRW_PRICE,
            )
            prices = sorted({int(item["price"]) for item in eligible if item.get("price") is not None})
            print(f"departure_cheapest_tab_selected={dep_state.get('cheapestSelected')}")
            print(f"departure_cheapest_loading={dep_state.get('cheapestLoading')}")
            print(f"departure_advertised={advertised if advertised is not None else 'unknown'}")
            print(f"departure_candidate_prices={prices}")
            await save_debug(page, artifact_dir, "departure-capture-failed")
            raise RuntimeError("Explicit Cheapest tab was selected, but its settled trustworthy lowest row was not captured")
        print_candidate("departure", departure, dep_state, dep_policy)

        # Persist the next phase before clicking. If Google performs a full
        # navigation, the init script restores 'returning' with capture already
        # active from the first byte of the new document.
        await set_phase(page, "returning")
        mode = await click_captured_candidate(page, departure)
        print(f"departure_pointer_click_mode={mode}")
        print("departure_pointer_click_sent=True")
        returning_page = await wait_for_returning_page(page, selection_wait_ms)
        print(f"departure_navigation_confirmed={returning_page}")
        print(f"current_url_after_departure={page.url}")
        if not returning_page:
            await save_debug(page, artifact_dir, "departure-navigation-failed")
            raise RuntimeError("Departure click did not reach Returning flights")

        returning, ret_state, ret_policy = await wait_for_candidate(
            page,
            phase="returning",
            origin=DESTINATION,
            destination=ORIGIN,
            timeout_ms=selection_wait_ms,
            capture_window_ms=return_capture_ms,
            allow_missing_route=True,
            min_price=MIN_RETURN_ADJUSTMENT,
        )
        await save_json(artifact_dir / "snapshot-return-state.json", ret_state)
        if not returning:
            body = await page.locator("body").inner_text()
            eligible = eligible_candidates(
                phase_candidates(ret_state, "returning"),
                origin=DESTINATION,
                destination=ORIGIN,
                allow_missing_route=True,
                min_price=MIN_RETURN_ADJUSTMENT,
            )
            print(f"body_has_returning={'returning flights' in body.lower() or '귀국 항공편' in body}")
            print(f"return_candidate_prices={sorted({int(i['price']) for i in eligible if i.get('price') is not None})}")
            await save_debug(page, artifact_dir, "return-capture-failed")
            raise RuntimeError("Returning flights loaded, but no trustworthy return price row was captured")
        if not flight_card_is_specific(
            str(returning.get("rowText") or ""),
            DESTINATION,
            ORIGIN,
            allow_missing_route=True,
            min_price=MIN_RETURN_ADJUSTMENT,
        ):
            raise RuntimeError("Return snapshot was not one specific return flight card")
        print_candidate("return", returning, ret_state, ret_policy)

        await set_phase(page, "done")
        mode = await click_captured_candidate(page, returning)
        print(f"return_pointer_click_mode={mode}")
        print("return_pointer_click_sent=True")
        await page.wait_for_timeout(700)

        print("\n=== BOOKING OPTIONS ===")
        deadline = asyncio.get_running_loop().time() + booking_wait_ms / 1000
        options: list[dict] = []
        marker = False
        while asyncio.get_running_loop().time() < deadline:
            marker, options = await booking_options(page)
            if marker and options:
                break
            await page.wait_for_timeout(150)
        print(f"booking_options_marker={marker}")
        print(f"booking_option_candidates={len(options)}")
        for index, option in enumerate(options[:10], start=1):
            text = " | ".join(str(option.get("text") or "").splitlines())[:1000]
            print(f"booking_option_{index}={int(option['price']):,} KRW | {text}")
        await save_json(artifact_dir / "snapshot-booking-options.json", options)
        await save_debug(page, artifact_dir, "snapshot-booking-final")
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
    except Exception as exc:
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        if page is not None:
            try:
                await save_json(artifact_dir / "snapshot-error-state.json", await capture_state(page))
                await save_debug(page, artifact_dir, "snapshot-probe-error")
            except Exception:
                pass
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
