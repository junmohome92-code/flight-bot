from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


_SCRIPT = Path(__file__).with_name("google_ui_probe.py")
_SPEC = importlib.util.spec_from_file_location("google_ui_probe_transient", _SCRIPT)
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

_TRANSIENT_CAPTURE_JS = r"""
(() => {
    if (window.__flightBotTransient) return;

    const state = window.__flightBotTransient = {
        phase: window.__flightBotInitialPhase || 'document-init',
        events: [],
        keys: {},
        startedAtMs: performance.now()
    };

    const priceRe = /₩\s*([0-9][0-9,]*)/g;
    const timeRe = /\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi;
    const flightShapeRe = /nonstop|stops?|직항|경유|\bhr\b|시간/i;

    function extractPrices(text) {
        const result = [];
        priceRe.lastIndex = 0;
        let match;
        while ((match = priceRe.exec(text || '')) !== null) {
            const value = Number(match[1].replaceAll(',', ''));
            if (Number.isFinite(value) && value >= 50000 && value <= 1500000) {
                result.push(value);
            }
        }
        return [...new Set(result)];
    }

    function directText(el) {
        const aria = el.getAttribute?.('aria-label') || '';
        const textNodes = Array.from(el.childNodes || [])
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent || '')
            .join(' ');
        let own = `${aria}\n${textNodes}`.trim();
        if (!own.includes('₩') && (el.children?.length || 0) <= 2) {
            const text = (el.innerText || el.textContent || '').trim();
            if (text.includes('₩') && text.length <= 800) own += `\n${text}`;
        }
        return own;
    }

    function findFlightRow(el) {
        let node = el;
        for (let depth = 0; depth < 16 && node; depth += 1, node = node.parentElement) {
            const text = (node.innerText || node.textContent || '').trim();
            if (!text || text.length > 7000) continue;
            timeRe.lastIndex = 0;
            const times = text.match(timeRe) || [];
            const upper = text.toUpperCase();
            const hasRoute = upper.includes('CJJ') && upper.includes('TPE');
            const hasShape = flightShapeRe.test(text);
            if (times.length >= 2 && (hasRoute || hasShape)) return text;
        }
        return '';
    }

    function recordElement(el, reason) {
        if (!(el instanceof Element)) return;
        const own = directText(el);
        if (!own.includes('₩')) return;
        const prices = extractPrices(own);
        if (!prices.length) return;
        const rowText = findFlightRow(el);
        if (!rowText) return;

        for (const price of prices) {
            const key = `${state.phase}|${price}|${rowText.slice(0, 900)}`;
            if (state.keys[key]) continue;
            state.keys[key] = true;
            state.events.push({
                phase: state.phase,
                price,
                rowText: rowText.slice(0, 3500),
                ownText: own.slice(0, 900),
                reason,
                seenAtMs: Math.round(performance.now() * 10) / 10,
                url: location.href,
                tag: el.tagName,
                role: el.getAttribute('role'),
                aria: el.getAttribute('aria-label')
            });
            if (state.events.length > 250) state.events.shift();
        }
    }

    function inspect(root, reason) {
        if (!root) return;
        if (root instanceof Element) recordElement(root, reason);
        if (!root.querySelectorAll) return;

        let checked = 0;
        for (const el of root.querySelectorAll('*')) {
            if (++checked > 2500) break;
            const aria = el.getAttribute?.('aria-label') || '';
            let likely = aria.includes('₩');
            if (!likely) {
                for (const child of el.childNodes || []) {
                    if (child.nodeType === Node.TEXT_NODE && (child.textContent || '').includes('₩')) {
                        likely = true;
                        break;
                    }
                }
            }
            if (likely) recordElement(el, reason);
        }
    }

    const observer = new MutationObserver(mutations => {
        for (const mutation of mutations) {
            if (mutation.target instanceof Element) recordElement(mutation.target, 'mutation-target');
            for (const node of mutation.addedNodes || []) inspect(node, 'mutation-added');
        }
    });
    observer.observe(document, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ['aria-label']
    });

    document.addEventListener('DOMContentLoaded', () => {
        inspect(document.documentElement, 'domcontentloaded');
    }, {once: true});

    let scans = 0;
    const timer = setInterval(() => {
        inspect(document.documentElement, 'early-scan');
        scans += 1;
        if (scans >= 16) clearInterval(timer);
    }, 125);
})();
"""


@dataclass(frozen=True)
class TransientCandidate:
    price: int
    row_text: str
    phase: str
    seen_at_ms: float
    reason: str
    url: str


def event_to_candidate(event: dict) -> TransientCandidate | None:
    try:
        price = int(event.get("price"))
    except (TypeError, ValueError):
        return None
    row_text = str(event.get("rowText") or "").strip()
    if not 50_000 <= price <= 1_500_000:
        return None
    if not probe.row_looks_like_flight_result(row_text):
        return None
    try:
        seen_at_ms = float(event.get("seenAtMs") or 0)
    except (TypeError, ValueError):
        seen_at_ms = 0.0
    return TransientCandidate(
        price=price,
        row_text=row_text,
        phase=str(event.get("phase") or "unknown"),
        seen_at_ms=seen_at_ms,
        reason=str(event.get("reason") or "unknown"),
        url=str(event.get("url") or ""),
    )


def normalize_events(events: list[dict]) -> list[TransientCandidate]:
    found: dict[tuple[int, str, str], TransientCandidate] = {}
    for event in events:
        candidate = event_to_candidate(event)
        if candidate is None:
            continue
        found[(candidate.price, candidate.phase, candidate.row_text)] = candidate
    return sorted(found.values(), key=lambda item: (item.price, item.seen_at_ms))


def matching_candidates(
    candidates: list[TransientCandidate],
    advertised_price: int | None,
    *,
    phases: set[str] | None = None,
) -> list[TransientCandidate]:
    scoped = [item for item in candidates if phases is None or item.phase in phases]
    if advertised_price is None:
        return scoped
    return [item for item in scoped if item.price <= advertised_price]


def launch_edge_blank(profile_dir: Path, port: int) -> subprocess.Popen:
    edge = probe.find_windows_edge()
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
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


async def read_candidates(page) -> list[TransientCandidate]:
    try:
        events = await page.evaluate("() => window.__flightBotTransient?.events || []")
    except Exception:
        return []
    return normalize_events(events if isinstance(events, list) else [])


async def mark_phase(page, phase: str) -> None:
    await page.evaluate(
        "phase => { if (window.__flightBotTransient) window.__flightBotTransient.phase = phase; }",
        phase,
    )


async def save_transient_artifact(page, artifact_dir: Path, stem: str) -> list[TransientCandidate]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = await page.evaluate("() => window.__flightBotTransient?.events || []")
    except Exception:
        raw = []
    path = artifact_dir / f"{stem}-transient.json"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalize_events(raw if isinstance(raw, list) else [])


async def print_candidates(label: str, candidates: list[TransientCandidate]) -> None:
    print(f"{label}_count={len(candidates)}")
    for index, candidate in enumerate(candidates[:20], start=1):
        row = " | ".join(
            line.strip() for line in candidate.row_text.splitlines() if line.strip()
        )[:900]
        print(
            f"{label}_{index}={candidate.price:,} KRW | phase={candidate.phase} "
            f"| seen_ms={candidate.seen_at_ms:.1f} | {row}"
        )


async def wait_for_matching_transient(
    page,
    advertised_price: int | None,
    *,
    phases: set[str],
    timeout_ms: int,
) -> tuple[list[TransientCandidate], list[TransientCandidate]]:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    latest: list[TransientCandidate] = []
    while asyncio.get_running_loop().time() < deadline:
        latest = await read_candidates(page)
        matched = matching_candidates(latest, advertised_price, phases=phases)
        if matched:
            return latest, matched
        await page.wait_for_timeout(100)
    return latest, []


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("This acceptance probe is Windows-only")
    if probe.env_bool("BROWSER_HEADLESS", False):
        raise SystemExit("This acceptance probe must run visible; BROWSER_HEADLESS=false")

    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    transient_wait_ms = max(1000, int(os.getenv("GOOGLE_UI_TRANSIENT_WAIT_MS", "5000")))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "6"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    search_url = os.getenv("GOOGLE_UI_SEARCH_URL", ACCEPTANCE_SEARCH_URL).strip()

    print("Google Flights transient-price probe")
    print("  CJJ -> TPE / 2026-09-18 ~ 2026-09-20")
    print("  canonical generated acceptance URL reused: YES")
    print("  browser starts at about:blank for faster acceptance startup")
    print("  MutationObserver installed before Google page scripts")
    print("  captures flight-row price text even if later removed")
    print("  body-wide minimum fallback: DISABLED")
    print("  transient observed price is NOT booking-verified")
    print(f"  transient wait: {transient_wait_ms} ms")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = probe.free_local_port()
    edge_process: subprocess.Popen | None = None
    playwright = await probe.async_playwright().start()
    browser = None
    last_page = None

    try:
        edge_process = launch_edge_blank(profile_dir, port)
        await probe.wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]
        await context.add_init_script(_TRANSIENT_CAPTURE_JS)

        print("\n=== BASE FRESH DOCUMENT ===")
        page = await context.new_page()
        last_page = page
        page.set_default_timeout(timeout_ms)
        await page.add_init_script("window.__flightBotInitialPhase = 'base-fresh';")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"base_url={page.url}")
        await probe.wait_for_results(page, timeout_ms)

        base_candidates = await read_candidates(page)
        await print_candidates("base_transient", base_candidates)

        await mark_phase(page, "cheapest-transition")
        cheapest_state = await probe.select_cheapest(page)
        cheapest_url = page.url
        print(f"cheapest_transition_url={cheapest_url}")

        transition_candidates, transition_matches = await wait_for_matching_transient(
            page,
            cheapest_state.advertised_price,
            phases={"cheapest-transition"},
            timeout_ms=transient_wait_ms,
        )
        await print_candidates("transition_transient", transition_candidates)
        await save_transient_artifact(page, artifact_dir, "cheapest-transition")
        await probe.save_debug(page, artifact_dir, "cheapest-transition-final")

        body = await page.locator("body").inner_text()
        print(f"transition_final_price_unavailable={'price unavailable' in body.lower()}")
        if transition_matches:
            best = transition_matches[0]
            print("\n=== SUMMARY ===")
            print(f"transient_phase={best.phase}")
            print(f"transient_lowest={best.price:,} KRW")
            print(f"cheapest_advertised={cheapest_state.advertised_price:,} KRW" if cheapest_state.advertised_price is not None else "cheapest_advertised=unknown")
            print("observed=TRANSIENT_FLIGHT_ROW_CAPTURED")
            print("verified=False")
            print("acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE")
            print(f"artifact_dir={artifact_dir.resolve()}")
            if keep_open_seconds > 0:
                await page.wait_for_timeout(keep_open_seconds * 1000)
            return

        if not cheapest_state.found or not cheapest_state.clicked:
            raise RuntimeError("Cheapest/최저가 tab was not ready")
        if cheapest_url == search_url:
            raise RuntimeError("Cheapest click did not produce a transition URL")

        print("\n=== CHEAPEST URL FRESH DOCUMENT ===")
        fresh = await context.new_page()
        last_page = fresh
        fresh.set_default_timeout(timeout_ms)
        await fresh.add_init_script("window.__flightBotInitialPhase = 'cheapest-fresh';")
        await fresh.goto(cheapest_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"cheapest_fresh_url={fresh.url}")

        fresh_candidates, fresh_matches = await wait_for_matching_transient(
            fresh,
            cheapest_state.advertised_price,
            phases={"cheapest-fresh", "document-init"},
            timeout_ms=transient_wait_ms,
        )
        await print_candidates("cheapest_fresh_transient", fresh_candidates)

        try:
            await probe.wait_for_results(fresh, min(timeout_ms, 15000))
        except Exception as exc:
            print(f"final_result_wait={type(exc).__name__}: {exc}")

        final_body = await fresh.locator("body").inner_text()
        print(f"cheapest_fresh_final_price_unavailable={'price unavailable' in final_body.lower()}")
        final_prices = await probe.collect_price_candidates(fresh)
        print(f"final_dom_price_candidates={len(final_prices)}")

        await save_transient_artifact(fresh, artifact_dir, "cheapest-fresh")
        await probe.save_debug(fresh, artifact_dir, "cheapest-fresh-final")
        await probe.print_session_diagnostics(fresh, "TRANSIENT CHEAPEST FRESH")

        if fresh_matches:
            best = fresh_matches[0]
            print("\n=== SUMMARY ===")
            print(f"transient_phase={best.phase}")
            print(f"transient_lowest={best.price:,} KRW")
            print(f"cheapest_advertised={cheapest_state.advertised_price:,} KRW" if cheapest_state.advertised_price is not None else "cheapest_advertised=unknown")
            print("observed=TRANSIENT_FLIGHT_ROW_CAPTURED")
            print("verified=False")
            print("acceptance=CHEAPEST_OBSERVED_BEFORE_PRICE_UNAVAILABLE")
            print(f"artifact_dir={artifact_dir.resolve()}")
            if keep_open_seconds > 0:
                await fresh.wait_for_timeout(keep_open_seconds * 1000)
            return

        raise RuntimeError(
            "No flight-row scoped Cheapest price was captured before Google replaced the page with Price unavailable"
        )
    except Exception as exc:
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        if last_page is not None:
            try:
                await save_transient_artifact(last_page, artifact_dir, "transient-final-error")
            except Exception:
                pass
            await probe.save_debug(last_page, artifact_dir, "transient-final-error")
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
