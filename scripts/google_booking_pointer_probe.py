from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path


warnings.filterwarnings("ignore", category=SyntaxWarning, message="invalid escape sequence.*")

_BASE_SCRIPT = Path(__file__).with_name("google_booking_probe.py")
_SPEC = importlib.util.spec_from_file_location("google_booking_probe_pointer_base", _BASE_SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Could not load google_booking_probe.py")
base = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = base
_SPEC.loader.exec_module(base)
transient = base.transient
probe = base.probe


_POINTER_PICK_JS = r"""
(() => {
    if (window.__flightBotPointerPick) return;

    const PHASE_KEY = '__flightBotPointerPhase';
    const CLICKS_KEY = '__flightBotPointerClicks';

    function loadClicks() {
        try {
            const value = JSON.parse(sessionStorage.getItem(CLICKS_KEY) || '[]');
            return Array.isArray(value) ? value : [];
        } catch (_) {
            return [];
        }
    }

    let phase = 'departure';
    try {
        const saved = sessionStorage.getItem(PHASE_KEY);
        if (saved === 'returning' || saved === 'done') phase = saved;
    } catch (_) {}

    const state = window.__flightBotPointerPick = {
        phase,
        candidates: [],
        pending: null,
        clicks: loadClicks(),
        timer: null,
        settleMs: 55,
        rejectedBroad: 0,
        rejectedSource: 0,
        startedAtMs: performance.now()
    };

    const priceRe = /₩\s*([0-9][0-9,]*)/g;
    const timeRe = /\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi;
    const flightShapeRe = /nonstop|stops?|직항|경유|\bhr\b|시간/i;
    const semanticSelector = '[role="button"], [role="link"], button, a, [tabindex="0"]';
    const broadMarkerRe = /flight search|search results|all filters|top departing flights|other departing flights|sorted by|checking prices from multiple sources|searching nearby airports/i;

    function normalized(text) {
        return (text || '')
            .replace(/[–—]/g, '-')
            .replace(/\s+/g, ' ')
            .toUpperCase();
    }

    function routeToken() {
        return state.phase === 'returning' ? 'TPE-CJJ' : 'CJJ-TPE';
    }

    function countToken(text, token) {
        const value = normalized(text);
        let count = 0;
        let offset = 0;
        while (true) {
            const index = value.indexOf(token, offset);
            if (index < 0) break;
            count += 1;
            offset = index + token.length;
        }
        return count;
    }

    function prices(text) {
        const result = [];
        priceRe.lastIndex = 0;
        let match;
        while ((match = priceRe.exec(text || '')) !== null) {
            const value = Number(match[1].replaceAll(',', ''));
            if (Number.isFinite(value) && value >= 50000 && value <= 1500000) result.push(value);
        }
        return [...new Set(result)];
    }

    function visible(el) {
        if (!(el instanceof Element) || !el.isConnected) return false;
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 2 && rect.height > 2;
    }

    function directPriceSource(el) {
        if (!(el instanceof Element) || !visible(el)) return [];
        const aria = el.getAttribute('aria-label') || '';
        const directText = Array.from(el.childNodes || [])
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent || '')
            .join(' ')
            .trim();
        const own = `${aria}\n${directText}`.trim();
        if (!own.includes('₩') || own.length > 180) {
            state.rejectedSource += 1;
            return [];
        }
        const found = prices(own);
        return found.length <= 2 ? found : [];
    }

    function compactFlightContext(source, price) {
        const token = routeToken();
        let node = source;
        for (let depth = 0; depth < 18 && node; depth += 1, node = node.parentElement) {
            const text = (node.innerText || node.textContent || '').trim();
            if (!text || text.length > 1800) {
                if (text && text.length > 1800) state.rejectedBroad += 1;
                continue;
            }
            timeRe.lastIndex = 0;
            const times = text.match(timeRe) || [];
            if (times.length < 2 || times.length > 4) continue;
            if (countToken(text, token) !== 1) continue;
            if (!flightShapeRe.test(text)) continue;
            const rowPrices = prices(text);
            if (!rowPrices.includes(price) || rowPrices.length > 3) continue;
            if (broadMarkerRe.test(text)) {
                state.rejectedBroad += 1;
                continue;
            }
            return {
                row: node,
                rowText: text,
                timeCount: times.length,
                rowPriceCount: rowPrices.length
            };
        }
        return null;
    }

    function clickAnchor(source, row) {
        let node = source;
        while (node) {
            if (visible(node)) {
                if (node.matches?.(semanticSelector)) {
                    return {el: node, mode: 'semantic'};
                }
                const style = getComputedStyle(node);
                if (style.cursor === 'pointer') {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text.length <= 1800) return {el: node, mode: 'cursor-pointer'};
                }
            }
            if (node === row) break;
            node = node.parentElement;
        }
        return visible(source) ? {el: source, mode: 'price-source'} : null;
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

    function schedulePending() {
        if (state.pending || state.phase === 'done') return;
        if (state.timer) clearTimeout(state.timer);
        state.timer = setTimeout(() => {
            state.timer = null;
            const current = state.candidates.filter(item =>
                item.phase === state.phase && item.source.isConnected && item.anchor.isConnected && visible(item.anchor)
            );
            if (!current.length) return;
            current.sort((a, b) => a.price - b.price || a.seenAtMs - b.seenAtMs);
            const best = current[0];
            const anchorRect = rectOf(best.anchor);
            const sourceRect = rectOf(best.source);
            state.pending = {
                phase: best.phase,
                price: best.price,
                rowText: best.rowText.slice(0, 2800),
                sourceText: best.sourceText.slice(0, 300),
                seenAtMs: best.seenAtMs,
                anchorMode: best.anchorMode,
                anchorTag: best.anchor.tagName,
                anchorRole: best.anchor.getAttribute('role'),
                x: anchorRect.x,
                y: anchorRect.y,
                anchorRect,
                sourceRect,
                timeCount: best.timeCount,
                routeCount: 1,
                rowPriceCount: best.rowPriceCount,
                rowLength: best.rowText.length,
                urlBefore: location.href
            };
        }, state.settleMs);
    }

    function consider(el) {
        if (state.pending || state.phase === 'done') return;
        const foundPrices = directPriceSource(el);
        if (!foundPrices.length) return;
        const sourceText = `${el.getAttribute('aria-label') || ''}\n${Array.from(el.childNodes || [])
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent || '')
            .join(' ')}`.trim();
        const seenAtMs = Math.round(performance.now() * 10) / 10;
        for (const price of foundPrices) {
            const context = compactFlightContext(el, price);
            if (!context) continue;
            const anchor = clickAnchor(el, context.row);
            if (!anchor) continue;
            const duplicate = state.candidates.some(item =>
                item.phase === state.phase && item.price === price && item.source === el
            );
            if (duplicate) continue;
            state.candidates.push({
                phase: state.phase,
                price,
                source: el,
                sourceText,
                anchor: anchor.el,
                anchorMode: anchor.mode,
                rowText: context.rowText,
                timeCount: context.timeCount,
                rowPriceCount: context.rowPriceCount,
                seenAtMs
            });
        }
        schedulePending();
    }

    function inspect(root) {
        if (!root) return;
        if (root instanceof Element) consider(root);
        if (!root.querySelectorAll) return;
        let checked = 0;
        for (const el of root.querySelectorAll('*')) {
            if (++checked > 2600) break;
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
            if (likely) consider(el);
        }
    }

    const observer = new MutationObserver(mutations => {
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
        attributeFilter: ['aria-label']
    });

    document.addEventListener('DOMContentLoaded', () => inspect(document.documentElement), {once: true});
    let scans = 0;
    const scanTimer = setInterval(() => {
        inspect(document.documentElement);
        scans += 1;
        if (scans >= 40 || state.phase === 'done') clearInterval(scanTimer);
    }, 60);
})();
"""


async def pointer_state(page) -> dict:
    try:
        value = await page.evaluate(
            """() => {
                const s = window.__flightBotPointerPick;
                if (!s) return {phase: 'missing', clicks: [], pending: null};
                return {
                    phase: s.phase,
                    pending: s.pending ? {...s.pending} : null,
                    clicks: (s.clicks || []).map(item => ({...item})),
                    candidateCount: (s.candidates || []).length,
                    rejectedBroad: s.rejectedBroad || 0,
                    rejectedSource: s.rejectedSource || 0
                };
            }"""
        )
        return value if isinstance(value, dict) else {"phase": "invalid", "clicks": [], "pending": None}
    except Exception:
        return {"phase": "unavailable", "clicks": [], "pending": None}


async def wait_for_pending(page, phase: str, timeout_ms: int) -> tuple[dict, dict]:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    latest: dict = {"phase": "unknown", "clicks": [], "pending": None}
    while asyncio.get_running_loop().time() < deadline:
        latest = await pointer_state(page)
        pending = latest.get("pending")
        if isinstance(pending, dict) and pending.get("phase") == phase:
            return pending, latest
        await page.wait_for_timeout(12)
    return {}, latest


async def arm_next_phase(page, pending: dict) -> dict:
    next_phase = "returning" if pending.get("phase") == "departure" else "done"
    value = await page.evaluate(
        """({nextPhase}) => {
            const s = window.__flightBotPointerPick;
            if (!s || !s.pending) return null;
            const click = {...s.pending, clickedAtMs: Math.round(performance.now() * 10) / 10};
            s.clicks.push(click);
            s.phase = nextPhase;
            s.pending = null;
            s.candidates = [];
            try {
                sessionStorage.setItem('__flightBotPointerPhase', nextPhase);
                sessionStorage.setItem('__flightBotPointerClicks', JSON.stringify(s.clicks));
            } catch (_) {}
            return click;
        }""",
        {"nextPhase": next_phase},
    )
    return value if isinstance(value, dict) else {}


def card_text_is_local(text: str, origin: str, destination: str) -> bool:
    if not base.row_text_is_specific_flight(text, origin, destination):
        return False
    lowered = " ".join(text.lower().split())
    broad_markers = (
        "flight search",
        "search results",
        "all filters",
        "top departing flights",
        "other departing flights",
        "sorted by",
        "checking prices from multiple sources",
        "searching nearby airports",
    )
    return not any(marker in lowered for marker in broad_markers)


def print_pick(prefix: str, pick: dict, diagnostics: dict) -> None:
    print(f"{prefix}_selected={int(pick['price']):,} KRW")
    print(f"{prefix}_anchor_mode={pick.get('anchorMode')}")
    print(f"{prefix}_anchor={pick.get('anchorTag')} role={pick.get('anchorRole')}")
    print(f"{prefix}_source_text={str(pick.get('sourceText') or '')[:180]}")
    print(
        f"{prefix}_row_shape=times:{pick.get('timeCount')} route_count:{pick.get('routeCount')} "
        f"prices:{pick.get('rowPriceCount')} length:{pick.get('rowLength')}"
    )
    print(f"{prefix}_candidate_count={diagnostics.get('candidateCount', 0)}")
    print(f"{prefix}_rejected_broad={diagnostics.get('rejectedBroad', 0)}")
    print(f"{prefix}_rejected_source={diagnostics.get('rejectedSource', 0)}")
    row = " | ".join(str(pick.get("rowText") or "").splitlines())[:1000]
    print(f"{prefix}_row={row}")


async def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("This acceptance probe is Windows-only")
    if probe.env_bool("BROWSER_HEADLESS", False):
        raise SystemExit("This acceptance probe must run visible; BROWSER_HEADLESS=false")

    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    selection_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_SELECTION_WAIT_MS", "20000")))
    booking_wait_ms = max(3000, int(os.getenv("GOOGLE_UI_BOOKING_WAIT_MS", "15000")))
    keep_open_seconds = int(os.getenv("BROWSER_KEEP_OPEN_SECONDS", "8"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-ui-win"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-profile-win"))
    search_url = os.getenv("GOOGLE_UI_SEARCH_URL", transient.ACCEPTANCE_SEARCH_URL).strip()
    cheapest_url = os.getenv("GOOGLE_UI_CHEAPEST_URL", base.acceptance_cheapest_url(search_url)).strip()

    print("Google Flights source-anchored pointer selection + booking probe")
    print("  CJJ -> TPE -> CJJ")
    print("  direct-price element only: YES")
    print("  broad results container rejected: YES")
    print("  DOM element.click fallback: NO")
    print("  real Playwright mouse click: YES")
    print("  transient lowest departure/return: YES")
    print("  external seller checkout: NO")
    print("  body-wide minimum fallback: NO")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = probe.free_local_port()
    edge_process: subprocess.Popen | None = None
    playwright = await probe.async_playwright().start()
    browser = None
    page = None

    try:
        edge_process = transient.launch_edge_blank(profile_dir, port)
        await probe.wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Native Edge exposed no browser context")
        context = browser.contexts[0]
        await context.add_init_script(_POINTER_PICK_JS)

        print("\n=== POINTER AUTO-SELECT DOCUMENT ===")
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        await page.goto(cheapest_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"selection_url={page.url}")

        departure, dep_diag = await wait_for_pending(page, "departure", selection_wait_ms)
        if not departure:
            await save_json(artifact_dir / "pointer-departure-state.json", dep_diag)
            await probe.save_debug(page, artifact_dir, "pointer-departure-failed")
            raise RuntimeError("No direct-price anchored CJJ-TPE transient candidate became clickable")
        if not card_text_is_local(str(departure.get("rowText") or ""), "CJJ", "TPE"):
            raise RuntimeError("Departure candidate still resolved to a broad results container")
        print_pick("departure", departure, dep_diag)
        dep_click = await arm_next_phase(page, departure)
        await page.mouse.click(float(departure["x"]), float(departure["y"]), delay=15)
        print("departure_pointer_click_sent=True")

        returning, ret_diag = await wait_for_pending(page, "returning", selection_wait_ms)
        if not returning:
            body = await page.locator("body").inner_text()
            print("return_selection_failed=True")
            print(f"body_has_returning={'returning flights' in body.lower() or '귀국 항공편' in body}")
            print(f"current_url={page.url}")
            await save_json(artifact_dir / "pointer-return-state.json", ret_diag)
            await probe.save_debug(page, artifact_dir, "pointer-return-failed")
            raise RuntimeError("Departure pointer click was sent, but no direct-price TPE-CJJ return candidate appeared")
        if not card_text_is_local(str(returning.get("rowText") or ""), "TPE", "CJJ"):
            raise RuntimeError("Return candidate still resolved to a broad results container")
        print_pick("return", returning, ret_diag)
        ret_click = await arm_next_phase(page, returning)
        await page.mouse.click(float(returning["x"]), float(returning["y"]), delay=15)
        print("return_pointer_click_sent=True")

        await save_json(
            artifact_dir / "pointer-clicks.json",
            {"departure": dep_click, "return": ret_click, "state": await pointer_state(page)},
        )
        await page.wait_for_timeout(800)

        print("\n=== BOOKING OPTIONS ===")
        deadline = asyncio.get_running_loop().time() + booking_wait_ms / 1000
        options: list[dict] = []
        marker = False
        while asyncio.get_running_loop().time() < deadline:
            options = await base.booking_options(page)
            body = await page.locator("body").inner_text()
            marker = "booking options" in body.lower() or "예약 옵션" in body
            if options:
                break
            await page.wait_for_timeout(180)

        print(f"booking_options_marker={marker}")
        print(f"booking_option_candidates={len(options)}")
        for index, option in enumerate(options[:10], start=1):
            text = " | ".join(str(option.get("text") or "").splitlines())[:1100]
            print(f"booking_option_{index}={int(option['price']):,} KRW | {text}")
            print(f"booking_option_{index}_href_present={bool(option.get('href'))}")

        await save_json(artifact_dir / "pointer-booking-options.json", options)
        await probe.save_debug(page, artifact_dir, "pointer-booking-final")
        if not options:
            raise RuntimeError("Departure/return pointer clicks completed, but no Booking CTA-scoped KRW option was confirmed")

        print("\n=== SUMMARY ===")
        print(f"departure_observed={int(departure['price']):,} KRW")
        print(f"return_selection_price={int(returning['price']):,} KRW")
        print(f"google_booking_option={int(options[0]['price']):,} KRW")
        print("observed=True")
        print("booking_option_visible=True")
        print("external_checkout_verified=False")
        print("verified=False")
        print("acceptance=GOOGLE_BOOKING_OPTION_REACHED_BY_POINTER_TRANSIENT_ROWS")
        print(f"artifact_dir={artifact_dir.resolve()}")

        if keep_open_seconds > 0:
            await page.wait_for_timeout(keep_open_seconds * 1000)
    except Exception as exc:
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        if page is not None:
            try:
                await save_json(artifact_dir / "pointer-error-state.json", await pointer_state(page))
            except Exception:
                pass
            try:
                await probe.save_debug(page, artifact_dir, "pointer-probe-error")
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
