from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import Page, async_playwright


DEFAULT_ORIGIN = "CJJ"
DEFAULT_DESTINATION = "TPE"
DEFAULT_DEPART = "2026-09-18"
DEFAULT_RETURN = "2026-09-20"


@dataclass
class NaverProbeResult:
    url: str
    rows: list[dict]
    body: str
    diagnostics: dict
    artifact_dir: Path


def build_naver_url(origin: str, destination: str, depart: str, return_date: str) -> str:
    origin = origin.strip().upper()
    destination = destination.strip().upper()
    depart_compact = depart.replace("-", "")
    return_compact = return_date.replace("-", "")
    path = (
        "https://flight.naver.com/flights/international/"
        f"{origin}:airport-{destination}:airport-{depart_compact}/"
        f"{destination}:airport-{origin}:airport-{return_compact}"
    )
    query = urlencode({"adult": 1, "fareType": "Y", "isDirect": "true"})
    return f"{path}?{query}"


# Naver changes CSS class names often.  The extractor therefore does not rely on
# one hashed class.  It starts at visible text nodes that look like prices and
# walks upward until it finds a compact flight-result context containing times.
# It also traverses open shadow roots.  We still refuse body-wide minimum-price
# scraping because that could mistake calendar/ad prices for a flight result.
_COLLECT_ROWS_JS = r"""
() => {
  const timeRe = /\b(?:[01]?\d|2[0-3]):[0-5]\d\b/g;
  const directRe = /직항|direct|nonstop/i;
  const roundTripRe = /왕복|round\s*trip/i;
  const routeRe = /CJJ|TPE|청주|타이(?:베이|완)|타오위안|공항|airport/i;
  const flightRe = /항공|airlines?|airways?|flight/i;
  const excludeRe = /달력|calendar|월\s*최저|최저가\s*달력|호텔|렌터카|투어|광고/i;

  function clean(text) {
    return String(text || '').replace(/\s+/g, ' ').trim();
  }

  function visible(el) {
    if (!(el instanceof Element) || !el.isConnected) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) === 0) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 2 && rect.height > 2;
  }

  function ownText(el) {
    let out = '';
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) out += ' ' + (node.textContent || '');
    }
    out += ' ' + (el.getAttribute('aria-label') || '');
    out += ' ' + (el.getAttribute('title') || '');
    return clean(out);
  }

  function priceHint(el) {
    const hint = [
      el.tagName,
      el.className || '',
      el.id || '',
      el.getAttribute('data-testid') || '',
      el.getAttribute('aria-label') || '',
    ].join(' ');
    return /price|fare|amount|cost|won|wonPrice|요금|가격/i.test(hint);
  }

  function parsePrices(text, hinted) {
    const source = clean(text);
    if (!source) return [];
    const hasCurrency = /₩|KRW|원/i.test(source);
    const out = [];
    const re = /(?:₩\s*|KRW\s*)?([0-9]{2,3}(?:,[0-9]{3})+|[0-9]{5,7})\s*(?:원|KRW)?/gi;
    let m;
    while ((m = re.exec(source)) !== null) {
      const token = m[1];
      if (!hasCurrency && !hinted && !token.includes(',')) continue;
      const value = Number(token.replaceAll(',', ''));
      if (Number.isFinite(value) && value >= 50000 && value <= 1500000) out.push(value);
    }
    return [...new Set(out)];
  }

  function allElements(root) {
    const out = [];
    const stack = [root];
    while (stack.length) {
      const current = stack.pop();
      if (!current || !current.querySelectorAll) continue;
      for (const el of current.querySelectorAll('*')) {
        out.push(el);
        if (el.shadowRoot) stack.push(el.shadowRoot);
      }
    }
    return out;
  }

  function semanticContainer(node) {
    const tag = (node.tagName || '').toLowerCase();
    const role = (node.getAttribute && node.getAttribute('role')) || '';
    const cls = String(node.className || '');
    return /^(li|article|button|a)$/.test(tag) || role === 'listitem' ||
      /flight|result|item|card|schedule|ticket|fare/i.test(cls);
  }

  const rows = [];
  const anchors = [];
  const seenRows = new Set();
  const seenAnchors = new Set();

  for (const el of allElements(document)) {
    if (!visible(el)) continue;
    const own = ownText(el);
    if (!own || own.length > 180) continue;
    const hinted = priceHint(el);
    const ownPrices = parsePrices(own, hinted);
    if (!ownPrices.length) continue;

    const anchorKey = `${ownPrices.join(',')}|${own}`;
    if (!seenAnchors.has(anchorKey) && anchors.length < 40) {
      seenAnchors.add(anchorKey);
      anchors.push({
        prices: ownPrices,
        text: own.slice(0, 220),
        tag: el.tagName,
        class_name: String(el.className || '').slice(0, 220),
        hinted,
      });
    }

    for (const price of ownPrices) {
      let node = el;
      let best = null;
      for (let depth = 0; depth < 16 && node; depth += 1, node = node.parentElement) {
        if (!(node instanceof Element)) continue;
        const text = clean(node.innerText || node.textContent || '');
        if (!text || text.length < 20) continue;
        if (text.length > 3000) break;
        if (excludeRe.test(text) && !directRe.test(text)) continue;

        const times = text.match(timeRe) || [];
        const rowPrices = parsePrices(text, priceHint(node));
        if (!rowPrices.includes(price)) continue;

        let score = 0;
        if (times.length >= 2 && times.length <= 12) score += 6;
        if (directRe.test(text)) score += 3;
        if (roundTripRe.test(text)) score += 2;
        if (routeRe.test(text)) score += 2;
        if (flightRe.test(text)) score += 1;
        if (semanticContainer(node)) score += 2;
        if (text.length <= 1200) score += 1;

        const candidate = {
          price,
          times: times.slice(0, 6),
          direct_evidence: directRe.test(text) ? 'row-direct-marker' : 'query-isDirect=true',
          round_trip_evidence: roundTripRe.test(text) ? 'row-round-trip-marker' : 'round-trip-search-url',
          score,
          depth,
          tag: node.tagName,
          class_name: String(node.className || '').slice(0, 240),
          text: text.slice(0, 1800),
        };
        if (!best || candidate.score > best.score ||
            (candidate.score === best.score && candidate.text.length < best.text.length)) {
          best = candidate;
        }
      }

      if (!best || best.score < 6 || best.times.length < 2) continue;
      const key = `${best.price}|${best.times.slice(0, 2).join('|')}|${best.text.slice(0, 600).toUpperCase()}`;
      if (seenRows.has(key)) continue;
      seenRows.add(key);
      rows.push(best);
    }
  }

  rows.sort((a, b) => b.score - a.score || a.price - b.price || a.text.length - b.text.length);
  return {
    rows: rows.slice(0, 24),
    price_anchors: anchors,
    body_has_direct: directRe.test(clean(document.body && document.body.innerText)),
    body_has_round_trip: roundTripRe.test(clean(document.body && document.body.innerText)),
  };
}
"""


async def _dismiss_consent(page: Page) -> None:
    labels = [
        r"^모두 동의$",
        r"^동의$",
        r"^동의하고 계속$",
        r"^확인$",
        r"^Accept all$",
        r"^I agree$",
    ]
    for pattern in labels:
        try:
            button = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            if await button.count() and await button.is_visible():
                await button.click(timeout=1500)
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def _body_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


async def _collect_all_frames(page: Page) -> tuple[list[dict], dict]:
    all_rows: list[dict] = []
    diagnostics: dict = {"frames": [], "price_anchors": []}

    for index, frame in enumerate(page.frames):
        frame_url = frame.url
        try:
            payload = await frame.evaluate(_COLLECT_ROWS_JS)
        except Exception as exc:
            diagnostics["frames"].append(
                {"index": index, "url": frame_url, "error": f"{type(exc).__name__}: {exc}"}
            )
            continue

        frame_rows = list(payload.get("rows") or [])
        frame_anchors = list(payload.get("price_anchors") or [])
        diagnostics["frames"].append(
            {
                "index": index,
                "url": frame_url,
                "row_count": len(frame_rows),
                "price_anchor_count": len(frame_anchors),
                "body_has_direct": bool(payload.get("body_has_direct")),
                "body_has_round_trip": bool(payload.get("body_has_round_trip")),
            }
        )
        for row in frame_rows:
            row = dict(row)
            row["frame_url"] = frame_url
            all_rows.append(row)
        for anchor in frame_anchors[:40]:
            if len(diagnostics["price_anchors"]) >= 80:
                break
            item = dict(anchor)
            item["frame_url"] = frame_url
            diagnostics["price_anchors"].append(item)

    # Semantic de-duplication.  Prefer the highest-scoring/smallest context for
    # the same price and first two visible times.
    best: dict[tuple, dict] = {}
    for row in all_rows:
        key = (int(row["price"]), tuple((row.get("times") or [])[:2]))
        old = best.get(key)
        if old is None:
            best[key] = row
            continue
        old_score = int(old.get("score") or 0)
        new_score = int(row.get("score") or 0)
        if new_score > old_score or (
            new_score == old_score and len(str(row.get("text") or "")) < len(str(old.get("text") or ""))
        ):
            best[key] = row

    rows = list(best.values())
    rows.sort(key=lambda row: (int(row["price"]), -int(row.get("score") or 0)))
    return rows[:12], diagnostics


async def _wait_for_rows(page: Page, timeout_seconds: int) -> tuple[list[dict], str, dict]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_body = ""
    last_diagnostics: dict = {"frames": [], "price_anchors": []}
    cycle = 0

    while asyncio.get_running_loop().time() < deadline:
        cycle += 1
        await _dismiss_consent(page)
        rows, diagnostics = await _collect_all_frames(page)
        diagnostics["cycle"] = cycle
        last_diagnostics = diagnostics
        if rows:
            return rows, await _body_text(page), diagnostics

        last_body = await _body_text(page)
        lowered = last_body.lower()
        blocked_markers = (
            "접근이 제한",
            "비정상적인 접근",
            "captcha",
            "verify you are human",
            "access denied",
        )
        if any(marker in lowered for marker in blocked_markers):
            raise RuntimeError("Naver Flights appears to be blocking or challenging this browser session")

        # Naver virtualizes some result lists.  A small scroll makes the browser
        # render additional result cards without navigating away from results.
        if cycle % 4 == 0:
            try:
                await page.mouse.wheel(0, 700)
            except Exception:
                pass
        await page.wait_for_timeout(1000)

    return [], last_body, last_diagnostics


async def _save_artifacts(
    page: Page,
    artifact_dir: Path,
    rows: list[dict],
    body: str,
    diagnostics: dict,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(artifact_dir / "page.png"), full_page=True)
    except Exception:
        pass
    (artifact_dir / "page.txt").write_text(body or "", encoding="utf-8")
    try:
        html = await page.content()
        (artifact_dir / "page.html").write_text(html, encoding="utf-8")
    except Exception:
        pass
    (artifact_dir / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    payload = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "url": page.url,
        "rows": rows,
        "diagnostics": diagnostics,
    }
    (artifact_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def collect_naver_visible_results(
    *,
    origin: str = DEFAULT_ORIGIN,
    destination: str = DEFAULT_DESTINATION,
    depart: str = DEFAULT_DEPART,
    return_date: str = DEFAULT_RETURN,
    navigation_timeout: int = 60,
    result_timeout: int = 70,
    artifact_dir: str | Path = "artifacts/naver-flight-poc",
    headless: bool = False,
    keep_open: int = 0,
    failure_keep_open: int = 0,
) -> NaverProbeResult:
    url = build_naver_url(origin, destination, depart, return_date)
    artifact_path = Path(artifact_dir)

    playwright = await async_playwright().start()
    browser = None
    context = None
    page = None
    rows: list[dict] = []
    body = ""
    diagnostics: dict = {"frames": [], "price_anchors": []}
    try:
        try:
            browser = await playwright.chromium.launch(
                channel="msedge",
                headless=headless,
                args=[] if headless else ["--start-maximized"],
            )
        except Exception as exc:
            raise RuntimeError(
                "Microsoft Edge could not be launched by Playwright. Install/update Edge and rerun the BAT."
            ) from exc

        context = await browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1440, "height": 1000},
        )
        page = await context.new_page()
        page.set_default_timeout(5000)
        await page.goto(url, wait_until="domcontentloaded", timeout=navigation_timeout * 1000)
        print(f"loaded_url={page.url}")

        rows, body, diagnostics = await _wait_for_rows(page, result_timeout)
        await _save_artifacts(page, artifact_path, rows, body, diagnostics)

        if not rows:
            anchor_count = len(diagnostics.get("price_anchors") or [])
            raise RuntimeError(
                "Naver results are visible but no reliable flight row was extracted "
                f"(visible price anchors found: {anchor_count})."
            )

        if keep_open > 0:
            await page.wait_for_timeout(keep_open * 1000)
        return NaverProbeResult(
            url=page.url,
            rows=rows,
            body=body,
            diagnostics=diagnostics,
            artifact_dir=artifact_path.resolve(),
        )
    except Exception:
        if page is not None:
            body = body or await _body_text(page)
            try:
                await _save_artifacts(page, artifact_path, rows, body, diagnostics)
            except Exception:
                pass
            if failure_keep_open > 0:
                try:
                    await page.wait_for_timeout(failure_keep_open * 1000)
                except Exception:
                    pass
        raise
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        await playwright.stop()


def _print_rows(result: NaverProbeResult, max_rows: int = 4) -> None:
    print("\n=== NAVER RESULT ===")
    print("POC_STATUS=PASS")
    print(f"direct_candidate_count={len(result.rows)}")
    print(f"lowest_visible_direct_price={result.rows[0]['price']:,} KRW")
    for index, row in enumerate(result.rows[:max_rows], start=1):
        times = row.get("times") or []
        time_text = " -> ".join(times[:2]) if len(times) >= 2 else "time-unavailable"
        compact = re.sub(r"\s+", " ", str(row.get("text") or ""))[:420]
        print(
            f"candidate_{index}={row['price']:,} KRW | {time_text} | "
            f"score={row.get('score')} | {compact}"
        )
    print(f"result_url={result.url}")
    print("booking_navigation_performed=False")
    print(f"artifact_dir={result.artifact_dir}")


async def run(args: argparse.Namespace) -> int:
    print("==================================================")
    print(" NAVER FLIGHTS independent visible POC")
    print("==================================================")
    print(f"route={args.origin.upper()}->{args.destination.upper()}->{args.origin.upper()}")
    print(f"dates={args.depart}~{args.return_date}")
    print("browser=Microsoft Edge (Playwright msedge channel)")
    print("direct_only=True")
    print("booking_navigation=False")
    print(f"search_url={build_naver_url(args.origin, args.destination, args.depart, args.return_date)}")
    print("")

    try:
        result = await collect_naver_visible_results(
            origin=args.origin,
            destination=args.destination,
            depart=args.depart,
            return_date=args.return_date,
            navigation_timeout=args.navigation_timeout,
            result_timeout=args.result_timeout,
            artifact_dir=args.artifact_dir,
            headless=False,
            keep_open=args.keep_open,
            failure_keep_open=args.failure_keep_open,
        )
    except Exception as exc:
        print("\n=== NAVER RESULT ===")
        print("POC_STATUS=FAIL")
        print(f"error={type(exc).__name__}: {exc}")
        print(f"artifact_dir={Path(args.artifact_dir).resolve()}")
        print("diagnostic_files=page.png,page.txt,page.html,diagnostics.json,result.json")
        return 2

    _print_rows(result)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visible Naver Flights POC")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--destination", default=DEFAULT_DESTINATION)
    parser.add_argument("--depart", default=DEFAULT_DEPART)
    parser.add_argument("--return-date", default=DEFAULT_RETURN)
    parser.add_argument("--navigation-timeout", type=int, default=60)
    parser.add_argument("--result-timeout", type=int, default=70)
    parser.add_argument("--keep-open", type=int, default=8)
    parser.add_argument("--failure-keep-open", type=int, default=20)
    parser.add_argument("--artifact-dir", default="artifacts/naver-flight-poc")
    return parser.parse_args()


if __name__ == "__main__":
    if not sys.platform.startswith("win"):
        raise SystemExit("This POC is intended for Windows visible Edge testing")
    raise SystemExit(asyncio.run(run(parse_args())))
