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
    flight_card_is_specific,
)


ACCEPTANCE_BASE_URL = (
    "https://www.google.com/travel/flights/search?"
    "tfs=CBwQAhoeEgoyMDI2LTA5LTE4agcIARIDQ0pKcgcIARIDVFBFGh4SCjIwMjYtMDktMjBqBwgBEgNUUEVyBwgBEgNDSkpAAUgBcAGCAQsI____________AZgBAQ"
    "&hl=en&gl=kr&curr=KRW"
)
_CHEAPEST_RE = re.compile(r"(?:Cheapest|최저가)", re.I)


_CAPTURE_JS = r"""
(() => {
    if (window.__flightBotCaptureV3) return;

    const PHASE_KEY = '__flightBotPointerPhaseV3';
    let phase = 'departure';
    try {
        const saved = sessionStorage.getItem(PHASE_KEY);
        if (saved === 'returning' || saved === 'done') phase = saved;
    } catch (_) {}

    const state = window.__flightBotCaptureV3 = {
        phase,
        captureEnabled: false,
        captureStartedAtMs: null,
        candidates: [],
        refs: {},
        advertisedPrice: null,
        advertisedChangedAtMs: null,
        cheapestSelected: false,
        cheapestText: '',
        cheapestLoading: true,
        returningMarker: false,
        rejectedBroad: 0,
        rejectedSource: 0,
        seq: 0,
        startedAtMs: performance.now()
    };

    const krwRe = /₩\s*([0-9][0-9,]*)/g;
    const wonRe = /([0-9][0-9,]*)\s+(?:South Korean won|Korean won|KRW)/gi;
    const timeRe = /\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi;
    const flightShapeRe = /nonstop|stops?|직항|경유|\bhr\b|시간/i;
    const cheapestRe = /(?:Cheapest|최저가)/i;
    const loadingRe = /fetching results|checking prices|검색 중|불러오는 중|가격 확인 중/i;
    const returningRe = /returning flights|귀국 항공편/i;
    const semanticSelector = '[role="button"], [role="link"], button, a, [tabindex="0"]';
    const broadMarkerRe = /flight search|search results|all filters|top departing flights|other departing flights|sorted by|checking prices from multiple sources|searching nearby airports|checking online travel agencies|finding the cheapest booking options/i;

    function normalize(text) {
        return (text || '')
            .replace(/[–—]/g, '-')
            .replace(/\s+/g, ' ')
            .trim()
            .toUpperCase();
    }

    function priceFloor() {
        return state.phase === 'returning' ? 0 : 50000;
    }

    function parsePrices(text, minPrice = priceFloor()) {
        const found = [];
        krwRe.lastIndex = 0;
        wonRe.lastIndex = 0;
        let match;
        while ((match = krwRe.exec(text || '')) !== null) {
            const value = Number(match[1].replaceAll(',', ''));
            if (Number.isFinite(value) && value >= minPrice && value <= 1500000) found.push(value);
        }
        while ((match = wonRe.exec(text || '')) !== null) {
            const value = Number(match[1].replaceAll(',', ''));
            if (Number.isFinite(value) && value >= minPrice && value <= 1500000) found.push(value);
        }
        return [...new Set(found)].sort((a, b) => a - b);
    }

    function visible(el) {
        if (!(el instanceof Element) || !el.isConnected) return false;
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 2 && rect.height > 2;
    }

    function directSource(el) {
        if (!(el instanceof Element) || !visible(el)) return null;
        const aria = el.getAttribute('aria-label') || '';
        const directText = Array.from(el.childNodes || [])
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent || '')
            .join(' ')
            .trim();
        const own = `${aria}\n${directText}`.trim();
        if (!own || own.length > 220) {
            state.rejectedSource += 1;
            return null;
        }
        const prices = parsePrices(own);
        if (!prices.length || prices.length > 2) {
            state.rejectedSource += 1;
            return null;
        }
        return {text: own, prices};
    }

    function countToken(text, token) {
        return normalize(text).split(token).length - 1;
    }

    function scanPageMarkers() {
        if (state.phase === 'returning' && !state.returningMarker) {
            const body = (document.body?.innerText || '').slice(0, 16000);
            if (returningRe.test(body)) state.returningMarker = true;
        }

        const controls = document.querySelectorAll('[role="tab"], button, [role="button"]');
        for (const control of controls) {
            const text = `${control.innerText || control.textContent || ''}\n${control.getAttribute('aria-label') || ''}`.trim();
            if (!text || text.length > 900 || !cheapestRe.test(text)) continue;
            const selected = control.getAttribute('aria-selected') === 'true';
            if (!selected) continue;
            state.cheapestSelected = true;
            state.cheapestText = text.slice(0, 900);
            state.cheapestLoading = loadingRe.test(text);
            if (!state.captureEnabled || state.phase !== 'departure') continue;
            const values = parsePrices(text, 50000);
            if (!values.length) continue;
            const next = Math.min(...values);
            if (state.advertisedPrice === null || next < state.advertisedPrice) {
                state.advertisedPrice = next;
                state.advertisedChangedAtMs = performance.now();
            }
        }
    }

    function compactFlightContext(source, price) {
        const forwardToken = state.phase === 'returning' ? 'TPE-CJJ' : 'CJJ-TPE';
        const reverseToken = state.phase === 'returning' ? 'CJJ-TPE' : 'TPE-CJJ';
        let node = source;
        for (let depth = 0; depth < 18 && node; depth += 1, node = node.parentElement) {
            const text = (node.innerText || node.textContent || '').trim();
            if (!text) continue;
            if (text.length > 1800 || broadMarkerRe.test(text)) {
                state.rejectedBroad += 1;
                continue;
            }
            timeRe.lastIndex = 0;
            const times = text.match(timeRe) || [];
            if (times.length < 2 || times.length > 4) continue;
            if (!flightShapeRe.test(text)) continue;
            const rowPrices = parsePrices(text);
            if (!rowPrices.includes(price) || rowPrices.length > 3) continue;

            const forward = countToken(text, forwardToken);
            const reverse = countToken(text, reverseToken);
            if (reverse > 0) continue;
            if (state.phase === 'departure' && forward !== 1) continue;
            if (state.phase === 'returning' && !(forward === 1 || (forward === 0 && state.returningMarker))) continue;

            return {
                row: node,
                rowText: text,
                timeCount: times.length,
                routeCount: forward,
                rowPriceCount: rowPrices.length
            };
        }
        return null;
    }

    function clickAnchor(source, row) {
        let node = source;
        while (node) {
            if (visible(node)) {
                if (node.matches?.(semanticSelector)) return {el: node, mode: 'semantic'};
                if (getComputedStyle(node).cursor === 'pointer') return {el: node, mode: 'cursor-pointer'};
            }
            if (node === row) break;
            node = node.parentElement;
        }
        return visible(row) ? {el: row, mode: 'row-coordinate'} : null;
    }

    function rectOf(el) {
        const rect = el.getBoundingClientRect();
        return {
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2,
            left: rect.left,
            top: rect.top,
            width: rect.width,
            height: rect.height
        };
    }

    function consider(el) {
        if (!state.captureEnabled || state.phase === 'done') return;
        const source = directSource(el);
        if (!source) return;
        const seenAtMs = Math.round(performance.now() * 10) / 10;

        for (const price of source.prices) {
            const context = compactFlightContext(el, price);
            if (!context) continue;
            const anchor = clickAnchor(el, context.row);
            if (!anchor) continue;
            const key = `${state.phase}|${price}|${normalize(context.rowText).slice(0, 900)}`;
            if (state.candidates.some(item => item.key === key)) continue;

            const id = `flight-bot-v3-${state.phase}-${++state.seq}`;
            try { anchor.el.setAttribute('data-flight-bot-pointer-anchor-id', id); } catch (_) {}
            const anchorRect = rectOf(anchor.el);
            const sourceRect = rectOf(el);
            state.refs[id] = {anchor: anchor.el, row: context.row};
            state.candidates.push({
                id,
                key,
                phase: state.phase,
                price,
                rowText: context.rowText.slice(0, 2800),
                sourceText: source.text.slice(0, 350),
                seenAtMs,
                anchorMode: anchor.mode,
                anchorTag: anchor.el.tagName,
                anchorRole: anchor.el.getAttribute('role'),
                anchorRect,
                sourceRect,
                timeCount: context.timeCount,
                routeCount: context.routeCount,
                rowPriceCount: context.rowPriceCount,
                rowLength: context.rowText.length,
                urlSeen: location.href
            });
            if (state.candidates.length > 160) state.candidates.shift();
        }
    }

    function inspect(root) {
        if (!state.captureEnabled || !root) return;
        if (root instanceof Element) consider(root);
        if (!root.querySelectorAll) return;
        let checked = 0;
        for (const el of root.querySelectorAll('*')) {
            if (++checked > 3500) break;
            const aria = el.getAttribute?.('aria-label') || '';
            let likely = /₩|South Korean won|Korean won|\bKRW\b/i.test(aria);
            if (!likely) {
                for (const child of el.childNodes || []) {
                    if (child.nodeType === Node.TEXT_NODE && /₩|South Korean won|Korean won|\bKRW\b/i.test(child.textContent || '')) {
                        likely = true;
                        break;
                    }
                }
            }
            if (likely) consider(el);
        }
    }

    const observer = new MutationObserver(mutations => {
        scanPageMarkers();
        if (!state.captureEnabled) return;
        for (const mutation of mutations) {
            if (mutation.target instanceof Element) consider(mutation.target);
            for (const node of mutation.addedNodes || []) inspect(node);
        }
    });
    observer.observe(document, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ['aria-label', 'aria-selected']
    });

    let scans = 0;
    const scanTimer = setInterval(() => {
        scanPageMarkers();
        if (state.captureEnabled) inspect(document.documentElement);
        scans += 1;
        if (scans >= 180 || state.phase === 'done') clearInterval(scanTimer);
    }, 40);
})();
"""


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


async def first_visible(locator: Locator) -> Locator | None:
    for index in range(await locator.count()):
        item = locator.nth(index)
        try:
            if await item.is_visible():
                return item
        except Exception:
            pass
    return None


async def select_cheapest_tab(page: Page, timeout_ms: int) -> dict:
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
    print("cheapest_tab_found=True")
    print("cheapest_tab_clicked=True")
    print(f"cheapest_tab_selected=True")
    print(f"cheapest_tab_text_before={text_before[:300]}")
    print(f"cheapest_tab_text_after={str(state.get('text') or '')[:300]}")
    return state


async def arm_capture(page: Page, phase: str) -> None:
    await page.evaluate(
        """phase => {
            try { sessionStorage.setItem('__flightBotPointerPhaseV3', phase); } catch (_) {}
            const s = window.__flightBotCaptureV3;
            if (!s) return;
            s.phase = phase;
            s.captureEnabled = true;
            s.captureStartedAtMs = performance.now();
            s.candidates = [];
            s.refs = {};
            s.advertisedPrice = null;
            s.advertisedChangedAtMs = performance.now();
            s.returningMarker = false;
            s.rejectedBroad = 0;
            s.rejectedSource = 0;
        }""",
        phase,
    )


async def capture_state(page: Page) -> dict:
    try:
        value = await page.evaluate(
            """() => {
                const s = window.__flightBotCaptureV3;
                if (!s) return {phase: 'missing', candidates: []};
                return {
                    phase: s.phase,
                    captureStartedAtMs: s.captureStartedAtMs,
                    advertisedPrice: s.advertisedPrice,
                    advertisedChangedAtMs: s.advertisedChangedAtMs,
                    cheapestSelected: s.cheapestSelected,
                    cheapestText: s.cheapestText,
                    cheapestLoading: s.cheapestLoading,
                    returningMarker: s.returningMarker,
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


def phase_candidates(state: dict, phase: str) -> list[dict]:
    return [
        item for item in (state.get("candidates") or [])
        if isinstance(item, dict) and item.get("phase") == phase
    ]


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

    while asyncio.get_running_loop().time() < deadline:
        latest = await capture_state(page)
        candidates = phase_candidates(latest, phase)
        now_ms = float(latest.get("nowMs") or 0.0)
        started_ms = float(latest.get("captureStartedAtMs") or now_ms)
        elapsed_ms = max(0.0, now_ms - started_ms)

        if phase == "departure":
            raw = latest.get("advertisedPrice")
            advertised = int(raw) if raw is not None else None
            changed_ms = float(latest.get("advertisedChangedAtMs") or started_ms)
            stable_ms = max(0.0, now_ms - changed_ms)
            ready = departure_capture_ready(
                candidate_count=len(candidates),
                elapsed_ms=elapsed_ms,
                advertised_stable_ms=stable_ms,
                loading=bool(latest.get("cheapestLoading", True)),
                capture_window_ms=capture_window_ms,
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
                    return dict(chosen), latest, "explicit-cheapest-stable-lowest"
        elif candidates and elapsed_ms >= capture_window_ms:
            chosen = choose_lowest_candidate(
                candidates,
                origin=origin,
                destination=destination,
                allow_missing_route=allow_missing_route,
                min_price=min_price,
            )
            if chosen is not None:
                return dict(chosen), latest, "return-adjustment-lowest"
        await page.wait_for_timeout(10)
    return {}, latest, "timeout"


async def click_captured_candidate(page: Page, candidate: dict) -> str:
    candidate_id = str(candidate.get("id") or "")
    rect = candidate.get("anchorRect") or {}
    x = float(rect.get("x") or 0.0)
    y = float(rect.get("y") or 0.0)
    mode = "captured-coordinate"

    if candidate_id:
        locator = page.locator(f'[data-flight-bot-pointer-anchor-id="{candidate_id}"]')
        try:
            if await locator.count():
                box = await locator.first.bounding_box()
                if box and box["width"] > 2 and box["height"] > 2:
                    x = float(box["x"] + box["width"] / 2)
                    y = float(box["y"] + box["height"] / 2)
                    mode = "live-marked-anchor"
        except Exception:
            pass
    if x <= 0 or y <= 0:
        source = candidate.get("sourceRect") or {}
        x = float(source.get("x") or 0.0)
        y = float(source.get("y") or 0.0)
        mode = "captured-price-coordinate"
    if x <= 0 or y <= 0:
        raise RuntimeError("Captured candidate has no usable pointer coordinate")
    await page.mouse.click(x, y, delay=18)
    return mode


async def wait_for_returning_page(page: Page, timeout_ms: int) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        try:
            body = await page.locator("body").inner_text()
        except Exception:
            await page.wait_for_timeout(30)
            continue
        if "returning flights" in body.lower() or "귀국 항공편" in body:
            return True
        await page.wait_for_timeout(40)
    return False


async def booking_options(page: Page) -> list[dict]:
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
                    let node = control;
                    for (let depth = 0; depth < 8 && node; depth += 1, node = node.parentElement) {
                        const text = (node.innerText || node.textContent || '').trim();
                        if (!text || text.length > 4500 || !actionRe.test(`${controlText}\n${text}`)) continue;
                        const values = prices(text);
                        if (!values.length) continue;
                        results.push({price: Math.min(...values), text: text.slice(0,3200), href: control.href || null});
                        break;
                    }
                    if (results.length >= 30) break;
                }
                return results;
            }"""
        )
    except Exception:
        return []
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
    return sorted(unique.values(), key=lambda item: int(item["price"]))


async def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def print_candidate(prefix: str, candidate: dict, state: dict, policy: str) -> None:
    values = []
    for item in phase_candidates(state, str(candidate.get("phase"))):
        if item.get("price") is not None:
            values.append(int(item["price"]))
    prices = sorted(set(values))
    print(f"{prefix}_selected={int(candidate['price']):,} KRW")
    print(f"{prefix}_selection_policy={policy}")
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

    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    selection_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_SELECTION_WAIT_MS", "20000")))
    booking_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_BOOKING_WAIT_MS", "15000")))
    departure_capture_ms = max(700, int(os.getenv("GOOGLE_UI_DEPARTURE_CAPTURE_MS", "1500")))
    return_capture_ms = max(200, int(os.getenv("GOOGLE_UI_RETURN_CAPTURE_MS", "650")))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "8"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    search_url = os.getenv("GOOGLE_UI_SEARCH_URL", ACCEPTANCE_BASE_URL).strip()

    print("Google Flights explicit Cheapest-tab + transient snapshot + Booking probe")
    print("  actual Cheapest/최저가 control click: YES")
    print("  aria-selected confirmation: YES")
    print("  ignore pre-Cheapest Best-tab rows: YES")
    print("  disappearing snapshots preserved: YES")
    print("  loading one-row premature selection: NO")
    print("  return price adjustment floor: 0 KRW")
    print("  page-wide price minimum: NO")
    print("  external seller checkout verification: NO")

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
        await context.add_init_script(_CAPTURE_JS)

        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"selection_url={page.url}")

        print("\n=== EXPLICIT CHEAPEST SELECTION ===")
        await select_cheapest_tab(page, selection_wait_ms)
        await arm_capture(page, "departure")

        departure, dep_state, dep_policy = await wait_for_candidate(
            page,
            phase="departure",
            origin="CJJ",
            destination="TPE",
            timeout_ms=selection_wait_ms,
            capture_window_ms=departure_capture_ms,
            allow_missing_route=False,
            min_price=MIN_KRW_PRICE,
        )
        await save_json(artifact_dir / "snapshot-departure-state.json", dep_state)
        if not departure:
            advertised = dep_state.get("advertisedPrice")
            prices = sorted({int(i["price"]) for i in phase_candidates(dep_state, "departure") if i.get("price") is not None})
            print(f"departure_cheapest_tab_selected={dep_state.get('cheapestSelected')}")
            print(f"departure_cheapest_loading={dep_state.get('cheapestLoading')}")
            print(f"departure_advertised={advertised if advertised is not None else 'unknown'}")
            print(f"departure_candidate_prices={prices}")
            raise RuntimeError("Explicit Cheapest tab was selected, but its trustworthy lowest row was not captured")
        print_candidate("departure", departure, dep_state, dep_policy)

        await arm_capture(page, "returning")
        mode = await click_captured_candidate(page, departure)
        print(f"departure_pointer_click_mode={mode}")
        print("departure_pointer_click_sent=True")
        returning_page = await wait_for_returning_page(page, selection_wait_ms)
        print(f"departure_navigation_confirmed={returning_page}")
        print(f"current_url_after_departure={page.url}")
        if not returning_page:
            raise RuntimeError("Departure click did not reach Returning flights")

        returning, ret_state, ret_policy = await wait_for_candidate(
            page,
            phase="returning",
            origin="TPE",
            destination="CJJ",
            timeout_ms=selection_wait_ms,
            capture_window_ms=return_capture_ms,
            allow_missing_route=True,
            min_price=MIN_RETURN_ADJUSTMENT,
        )
        await save_json(artifact_dir / "snapshot-return-state.json", ret_state)
        if not returning:
            body = await page.locator("body").inner_text()
            print(f"body_has_returning={'returning flights' in body.lower() or '귀국 항공편' in body}")
            print(f"return_candidate_prices={sorted({int(i['price']) for i in phase_candidates(ret_state, 'returning') if i.get('price') is not None})}")
            raise RuntimeError("Returning flights loaded, but no trustworthy return adjustment row was captured")
        if not flight_card_is_specific(
            str(returning.get("rowText") or ""), "TPE", "CJJ",
            allow_missing_route=True, min_price=MIN_RETURN_ADJUSTMENT,
        ):
            raise RuntimeError("Return snapshot was not one specific return flight card")
        print_candidate("return", returning, ret_state, ret_policy)

        await arm_capture(page, "done")
        mode = await click_captured_candidate(page, returning)
        print(f"return_pointer_click_mode={mode}")
        print("return_pointer_click_sent=True")
        await page.wait_for_timeout(700)

        print("\n=== BOOKING OPTIONS ===")
        deadline = asyncio.get_running_loop().time() + booking_wait_ms / 1000
        options: list[dict] = []
        marker = False
        while asyncio.get_running_loop().time() < deadline:
            options = await booking_options(page)
            body = await page.locator("body").inner_text()
            marker = "booking options" in body.lower() or "예약 옵션" in body
            if options:
                break
            await page.wait_for_timeout(150)
        print(f"booking_options_marker={marker}")
        print(f"booking_option_candidates={len(options)}")
        for index, option in enumerate(options[:10], start=1):
            text = " | ".join(str(option.get("text") or "").splitlines())[:1000]
            print(f"booking_option_{index}={int(option['price']):,} KRW | {text}")
        await save_json(artifact_dir / "snapshot-booking-options.json", options)
        await save_debug(page, artifact_dir, "snapshot-booking-final")
        if not options:
            raise RuntimeError("Departure/return selected, but no Booking CTA-scoped KRW option was confirmed")

        print("\n=== SUMMARY ===")
        print(f"departure_observed={int(departure['price']):,} KRW")
        print(f"return_price_adjustment={int(returning['price']):,} KRW")
        print(f"google_booking_option={int(options[0]['price']):,} KRW")
        print("observed=True")
        print("external_checkout_verified=False")
        print("verified=False")
        print("acceptance=GOOGLE_BOOKING_OPTION_REACHED_AFTER_EXPLICIT_CHEAPEST_SELECTION")

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
