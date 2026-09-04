from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path


_SCRIPT = Path(__file__).with_name("google_ui_probe.py")
_SPEC = importlib.util.spec_from_file_location("google_ui_probe_runtime", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Could not load google_ui_probe.py")
probe = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = probe
_SPEC.loader.exec_module(probe)


DEFAULT_SEARCH_URL = (
    "https://www.google.com/travel/flights/search?"
    "tfs=CBwQAhoeEgoyMDI2LTA5LTE4agcIARIDQ0pKcgcIARIDVFBFGh4SCjIwMjYtMDktMjBqBwgBEgNUUEVyBwgBEgNDSkpAAUgBcAGCAQsI____________AZgBAQ"
    "&hl=en&gl=kr&curr=KRW"
)


async def dump_price_nodes(page, artifact_dir: Path) -> None:
    data = await page.evaluate(
        r"""() => {
            const hasWon = value => typeof value === 'string' && value.includes('₩');
            const nodes = [];
            for (const el of document.querySelectorAll('*')) {
                const aria = el.getAttribute('aria-label') || '';
                const ownText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === Node.TEXT_NODE)
                    .map(n => n.textContent || '')
                    .join(' ')
                    .trim();
                if (!hasWon(aria) && !hasWon(ownText)) continue;

                const ancestors = [];
                let node = el;
                for (let depth = 0; depth < 10 && node; depth += 1, node = node.parentElement) {
                    const text = (node.innerText || node.textContent || '').trim();
                    ancestors.push({
                        depth,
                        tag: node.tagName,
                        role: node.getAttribute('role'),
                        aria: node.getAttribute('aria-label'),
                        className: String(node.className || '').slice(0, 240),
                        text: text.slice(0, 1200),
                    });
                }
                nodes.push({
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    aria,
                    className: String(el.className || '').slice(0, 240),
                    ownText: ownText.slice(0, 500),
                    ancestors,
                });
                if (nodes.length >= 120) break;
            }
            return nodes;
        }"""
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "price-node-dump.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"price_node_dump_count={len(data)}")
    for index, item in enumerate(data[:20], start=1):
        print(
            f"price_node_{index}: tag={item.get('tag')} role={item.get('role')} "
            f"aria={item.get('aria')!r} own={item.get('ownText')!r}"
        )
        for anc in item.get("ancestors", [])[:6]:
            text = " | ".join(str(anc.get("text") or "").splitlines())[:350]
            print(
                f"  anc{anc.get('depth')} tag={anc.get('tag')} role={anc.get('role')} "
                f"class={anc.get('className')!r} text={text!r}"
            )


async def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("Windows only")

    search_url = os.getenv("GOOGLE_UI_SEARCH_URL", DEFAULT_SEARCH_URL)
    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))
    price_wait_ms = int(os.getenv("GOOGLE_UI_PRICE_WAIT_MS", "20000"))
    artifact_dir = Path(os.getenv("BROWSER_DEBUG_DIR", "artifacts/google-url-ci"))
    profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "artifacts/google-url-profile-ci"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    port = probe.free_local_port()
    edge_process = None
    playwright = await probe.async_playwright().start()
    browser = None
    page = None
    try:
        edge_process = probe.launch_native_edge(profile_dir, port)
        await probe.wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        context = browser.contexts[0]
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)

        print("DIRECT GENERATED-URL DIAGNOSTIC")
        print(f"search_url={search_url}")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"fresh_url={page.url}")
        await probe.wait_for_results(page, timeout_ms)

        cheapest = await probe.select_cheapest(page)
        print(f"cheapest_found={cheapest.found}")
        print(f"cheapest_clicked={cheapest.clicked}")
        print(f"cheapest_advertised={cheapest.advertised_price}")
        await probe.expand_results(page)

        prices = await probe.wait_for_price_candidates(page, price_wait_ms)
        body = await page.locator("body").inner_text()
        print(f"price_unavailable={'price unavailable' in body.lower()}")
        print(f"parser_price_candidates={len(prices)}")
        for index, candidate in enumerate(prices[:20], start=1):
            row = " | ".join(candidate.row_text.splitlines())[:800]
            print(f"candidate_{index}={candidate.price} | {row}")

        await dump_price_nodes(page, artifact_dir)
        await probe.save_debug(page, artifact_dir, "direct-search-final")
        await probe.print_session_diagnostics(page, "DIRECT SEARCH")
    except Exception as exc:
        print(f"DIAGNOSTIC FAILED: {type(exc).__name__}: {exc}")
        if page is not None:
            try:
                await dump_price_nodes(page, artifact_dir)
            except Exception as dump_exc:
                print(f"price-node dump failed: {dump_exc}")
            await probe.save_debug(page, artifact_dir, "direct-search-error")
        raise
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
