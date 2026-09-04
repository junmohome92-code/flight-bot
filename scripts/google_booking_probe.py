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

_TRANSIENT_SCRIPT = Path(__file__).with_name("google_transient_price_probe.py")
_SPEC = importlib.util.spec_from_file_location("google_transient_price_probe_booking", _TRANSIENT_SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Could not load google_transient_price_probe.py")
transient = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = transient
_SPEC.loader.exec_module(transient)
probe = transient.probe


_AUTO_PICK_JS = r"""
(() => {
    if (window.__flightBotAutoPick) return;

    const state = window.__flightBotAutoPick = {
        phase: 'departure',
        live: [],
        clicks: [],
        timer: null,
        armed: true,
        startedAtMs: performance.now()
    };

    const priceRe = /₩\s*([0-9][0-9,]*)/g;
    const timeRe = /\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b/gi;
    const flightShapeRe = /nonstop|stops?|직항|경유|\bhr\b|시간/i;

    function normalized(text) {
        return (text || '').replace(/[–—]/g, '-').toUpperCase();
    }

    function directPrices(el) {
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
        const values = [];
        priceRe.lastIndex = 0;
        let match;
        while ((match = priceRe.exec(own)) !== null) {
            const value = Number(match[1].replaceAll(',', ''));
            if (Number.isFinite(value) && value >= 50000 && value <= 1500000) values.push(value);
        }
        return [...new Set(values)];
    }

    function flightRow(el) {
        let node = el;
        for (let depth = 0; depth < 16 && node; depth += 1, node = node.parentElement) {
            const text = (node.innerText || node.textContent || '').trim();
            if (!text || text.length > 5000) continue;
            timeRe.lastIndex = 0;
            const times = text.match(timeRe) || [];
            const route = normalized(text);
            const routeOK = state.phase === 'departure'
                ? route.includes('CJJ-TPE')
                : route.includes('TPE-CJJ');
            if (times.length >= 2 && routeOK && flightShapeRe.test(text)) {
                return {el: node, text};
            }
        }
        return null;
    }

    function visible(el) {
        if (!(el instanceof Element) || !el.isConnected) return false;
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 2 && rect.height > 2;
    }

    function clickTarget(row) {
        if (row.matches?.('[role="button"], [role="link"], button, a, [tabindex="0"]') && visible(row)) {
            return row;
        }
        const items = row.querySelectorAll?.('[role="button"], [role="link"], button, a, [tabindex="0"]') || [];
        for (const item of items) {
            if (!visible(item)) continue;
            const text = (item.innerText || item.textContent || '').trim();
            if (timeRe.test(text) || text.includes('₩')) return item;
        }
        return visible(row) ? row : null;
    }

    function scheduleClick() {
        if (!state.armed || state.clicks.length >= 2) return;
        if (state.timer) clearTimeout(state.timer);
        state.timer = setTimeout(() => {
            state.timer = null;
            const candidates = state.live.filter(item => item.phase === state.phase && item.row.isConnected);
            if (!candidates.length) return;
            candidates.sort((a, b) => a.price - b.price || a.seenAtMs - b.seenAtMs);
            const best = candidates[0];
            const target = clickTarget(best.row);
            if (!target) return;

            const click = {
                phase: state.phase,
                price: best.price,
                rowText: best.rowText.slice(0, 3500),
                seenAtMs: Math.round(performance.now() * 10) / 10,
                targetTag: target.tagName,
                targetRole: target.getAttribute('role'),
                urlBefore: location.href
            };
            state.clicks.push(click);

            if (state.phase === 'departure') {
                state.phase = 'returning';
                state.live = [];
            } else {
                state.phase = 'done';
                state.armed = false;
                state.live = [];
            }

            target.click();
        }, 140);
    }

    function consider(el) {
        if (!state.armed || state.phase === 'done' || !(el instanceof Element)) return;
        const prices = directPrices(el);
        if (!prices.length) return;
        const row = flightRow(el);
        if (!row) return;
        const seenAtMs = Math.round(performance.now() * 10) / 10;
        for (const price of prices) {
            const duplicate = state.live.some(item =>
                item.phase === state.phase && item.price === price && item.row === row.el
            );
            if (!duplicate) {
                state.live.push({phase: state.phase, price, row: row.el, rowText: row.text, seenAtMs});
            }
        }
        scheduleClick();
    }

    function inspect(root) {
        if (!root) return;
        if (root instanceof Element) consider(root);
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
        if (scans >= 24 || !state.armed) clearInterval(scanTimer);
    }, 100);
})();
"""


async def auto_click_state(page) -> dict:
    try:
        value = await page.evaluate(
            """() => {
                const s = window.__flightBotAutoPick;
                if (!s) return {phase: 'missing', clicks: []};
                return {
                    phase: s.phase,
                    clicks: s.clicks.map(item => ({...item}))
                };
            }"""
        )
        return value if isinstance(value, dict) else {"phase": "invalid", "clicks": []}
    except Exception:
        return {"phase": "unavailable", "clicks": []}


async def wait_for_clicks(page, count: int, timeout_ms: int) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    latest = {"phase": "unknown", "clicks": []}
    while asyncio.get_running_loop().time() < deadline:
        latest = await auto_click_state(page)
        if len(latest.get("clicks") or []) >= count:
            return latest
        await page.wait_for_timeout(50)
    return latest


def parse_booking_price(text: str) -> int | None:
    values = probe.parse_prices(text)
    values = [value for value in values if 50_000 <= value <= 1_500_000]
    return min(values) if values else None


async def booking_options(page) -> list[dict]:
    try:
        rows = await page.evaluate(
            r"""() => {
                const priceRe = /₩\s*([0-9][0-9,]*)/g;
                const actionRe = /book|continue|select|예약|계속|선택/i;
                const result = [];
                const controls = document.querySelectorAll('a, button, [role="button"], [role="link"]');
                for (const control of controls) {
                    if (!control.isConnected) continue;
                    let node = control;
                    for (let depth = 0; depth < 8 && node; depth += 1, node = node.parentElement) {
                        const text = (node.innerText || node.textContent || '').trim();
                        if (!text || text.length > 5000 || !text.includes('₩')) continue;
                        const controlText = (control.innerText || control.textContent || control.getAttribute('aria-label') || '').trim();
                        if (!actionRe.test(`${controlText}\n${text}`)) continue;
                        priceRe.lastIndex = 0;
                        const prices = [];
                        let match;
                        while ((match = priceRe.exec(text)) !== null) {
                            const value = Number(match[1].replaceAll(',', ''));
                            if (Number.isFinite(value) && value >= 50000 && value <= 1500000) prices.push(value);
                        }
                        if (!prices.length) continue;
                        result.push({
                            price: Math.min(...prices),
                            text: text.slice(0, 3500),
                            controlText: controlText.slice(0, 700),
                            href: control.href || null,
                            tag: control.tagName,
                            role: control.getAttribute('role')
                        });
                        break;
                    }
                    if (result.length >= 30) break;
                }
                return result;
            }"""
        )
    except Exception:
        return []

    unique: dict[tuple[int, str, str | None], dict] = {}
    for row in rows if isinstance(rows, list) else []:
        try:
            price = int(row.get("price"))
        except (TypeError, ValueError, AttributeError):
            continue
        text = str(row.get("text") or "").strip()
        href = str(row.get("href")) if row.get("href") else None
        unique[(price, text, href)] = row
    return sorted(unique.values(), key=lambda item: int(item["price"]))


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

    print("Google Flights transient selection + booking probe")
    print("  CJJ -> TPE -> CJJ")
    print("  transient lowest departure auto-click: YES")
    print("  transient lowest return auto-click: YES")
    print("  Booking options row/CTA price inspection: YES")
    print("  external seller checkout: NO")
    print("  body-wide minimum fallback: NO")
    print("  Booking option != final seller checkout verification")

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
        await context.add_init_script(transient._TRANSIENT_CAPTURE_JS)

        # We already proved that the canonical base URL can reveal a transient
        # cheapest value. For selection acceptance, start directly from the
        # Cheapest tfu URL so the auto-picker is armed before rows appear.
        bootstrap = await context.new_page()
        bootstrap.set_default_timeout(timeout_ms)
        await bootstrap.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        await probe.wait_for_results(bootstrap, timeout_ms)
        cheapest_state = await probe.select_cheapest(bootstrap)
        cheapest_url = bootstrap.url
        if not cheapest_state.found or not cheapest_state.clicked or cheapest_url == search_url:
            raise RuntimeError("Could not obtain Cheapest transition URL")
        print(f"cheapest_url={cheapest_url}")
        if cheapest_state.advertised_price is not None:
            print(f"cheapest_advertised={cheapest_state.advertised_price:,} KRW")
        else:
            print("cheapest_advertised=unknown")
        await bootstrap.close()

        print("\n=== AUTO-SELECT DOCUMENT ===")
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        await page.add_init_script("window.__flightBotInitialPhase = 'departure';")
        await page.add_init_script(_AUTO_PICK_JS)
        await page.goto(cheapest_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"selection_url={page.url}")

        first = await wait_for_clicks(page, 1, selection_wait_ms)
        clicks = first.get("clicks") or []
        print(f"departure_click_count={len(clicks)}")
        if clicks:
            dep = clicks[0]
            print(f"departure_selected={int(dep['price']):,} KRW")
            dep_row = " | ".join(str(dep.get("rowText") or "").splitlines())[:1100]
            print(f"departure_row={dep_row}")
        else:
            raise RuntimeError("Transient departure row was captured but not auto-clicked in time")

        second = await wait_for_clicks(page, 2, selection_wait_ms)
        clicks = second.get("clicks") or []
        print(f"return_click_count={max(0, len(clicks) - 1)}")
        if len(clicks) >= 2:
            ret = clicks[1]
            print(f"return_selected={int(ret['price']):,} KRW")
            ret_row = " | ".join(str(ret.get("rowText") or "").splitlines())[:1100]
            print(f"return_row={ret_row}")
        else:
            body = await page.locator("body").inner_text()
            print("return_selection_failed=True")
            print(f"body_has_returning={'returning flights' in body.lower() or '귀국 항공편' in body}")
            await save_json(artifact_dir / "auto-click-state.json", second)
            await probe.save_debug(page, artifact_dir, "return-selection-failed")
            raise RuntimeError("Departure was selected, but no transient TPE-CJJ return row was auto-clicked")

        await save_json(artifact_dir / "auto-click-state.json", second)
        await page.wait_for_timeout(1200)

        print("\n=== BOOKING OPTIONS ===")
        deadline = asyncio.get_running_loop().time() + booking_wait_ms / 1000
        options: list[dict] = []
        while asyncio.get_running_loop().time() < deadline:
            options = await booking_options(page)
            body = await page.locator("body").inner_text()
            if options or "booking options" in body.lower() or "예약 옵션" in body:
                if options:
                    break
            await page.wait_for_timeout(250)

        body = await page.locator("body").inner_text()
        print(f"booking_options_marker={'booking options' in body.lower() or '예약 옵션' in body}")
        print(f"booking_option_candidates={len(options)}")
        for index, option in enumerate(options[:10], start=1):
            text = " | ".join(str(option.get("text") or "").splitlines())[:1200]
            print(f"booking_option_{index}={int(option['price']):,} KRW | {text}")
            print(f"booking_option_{index}_href_present={bool(option.get('href'))}")

        await save_json(artifact_dir / "booking-options.json", options)
        await transient.save_transient_artifact(page, artifact_dir, "booking-selection")
        await probe.save_debug(page, artifact_dir, "booking-options-final")
        await probe.print_session_diagnostics(page, "BOOKING OPTIONS")

        if not options:
            raise RuntimeError("Departure and return were selected, but no booking CTA-scoped KRW option was confirmed")

        best_option = options[0]
        print("\n=== SUMMARY ===")
        print(f"departure_observed={int(clicks[0]['price']):,} KRW")
        print(f"return_selection_price={int(clicks[1]['price']):,} KRW")
        print(f"google_booking_option={int(best_option['price']):,} KRW")
        print("observed=True")
        print("booking_option_visible=True")
        print("external_checkout_verified=False")
        print("verified=False")
        print("acceptance=GOOGLE_BOOKING_OPTION_REACHED_FROM_TRANSIENT_ROWS")
        print(f"artifact_dir={artifact_dir.resolve()}")

        if keep_open_seconds > 0:
            await page.wait_for_timeout(keep_open_seconds * 1000)
    except Exception as exc:
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        if page is not None:
            try:
                await save_json(artifact_dir / "auto-click-state-error.json", await auto_click_state(page))
            except Exception:
                pass
            try:
                await transient.save_transient_artifact(page, artifact_dir, "booking-error")
            except Exception:
                pass
            await probe.save_debug(page, artifact_dir, "booking-probe-error")
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
