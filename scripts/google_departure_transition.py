from __future__ import annotations

import asyncio
import re
from pathlib import Path

from playwright.async_api import Page


_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b", re.I)
_FLIGHT_LOAD_ERROR_RE = re.compile(
    r"flights? (?:could not|couldn't|can't|cannot|were unable to) (?:be )?(?:load|loaded)|"
    r"unable to load flights?|"
    r"항공편을\s*(?:불러올|로드할)\s*수\s*없",
    re.I,
)
_RETURNING_RE = re.compile(r"returning flights|귀국 항공편", re.I)


class RecoverableReturningLoadError(RuntimeError):
    """Outbound was selected, but Google's returning-flight surface failed to load."""


def _unique_times(row_text: str) -> list[str]:
    result: list[str] = []
    for value in _TIME_RE.findall(row_text or ""):
        key = re.sub(r"\s+", " ", value).strip().upper()
        if key not in result:
            result.append(key)
        if len(result) >= 2:
            break
    return result


async def _resolve_specific_card_target(page: Page, candidate: dict) -> dict:
    """Resolve a live card-level click target, never an arbitrary inner price action.

    The old probe accepted the first ancestor with ``cursor:pointer`` while
    walking upward from the price node. Google can put pointer cursors on inner
    price/detail controls, so that rule can click something other than the
    flight card. A valid target here must still contain the selected price,
    two distinct flight times and flight-shape text.
    """
    candidate_id = str(candidate.get("id") or "")
    row_text = str(candidate.get("rowText") or "")
    times = _unique_times(row_text)
    if len(times) < 2:
        return {}
    try:
        price = int(candidate.get("price"))
    except (TypeError, ValueError):
        return {}

    anchor_rect = candidate.get("anchorRect") if isinstance(candidate.get("anchorRect"), dict) else {}
    source_rect = candidate.get("sourceRect") if isinstance(candidate.get("sourceRect"), dict) else {}

    try:
        value = await page.evaluate(
            r"""({candidateId, price, times, anchorRect, sourceRect}) => {
                const state = window.__flightBotCaptureV4;
                const ref = state?.refs?.[candidateId] || null;
                const marked = candidateId
                  ? document.querySelector(`[data-flight-bot-pointer-anchor-id="${CSS.escape(candidateId)}"]`)
                  : null;
                const start = marked || ref?.anchor || null;
                const capturedRow = ref?.row || null;
                const semanticSelector = '[role="button"], [role="link"], button, a, [tabindex="0"]';
                const flightShapeRe = /nonstop|stops?|직항|경유|\bhr\b|시간/i;
                const hardBroadRe = /flight search|search results|all filters|sorted by|checking prices from multiple sources|searching nearby airports|checking online travel agencies|finding the cheapest booking options/i;

                function visible(el) {
                    if (!(el instanceof Element) || !el.isConnected) return false;
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 2 && rect.height > 2;
                }
                function textOf(el) {
                    return (el?.innerText || el?.textContent || '')
                      .replace(/[–—‑−]/g, '-')
                      .replace(/\s+/g, ' ')
                      .trim();
                }
                function hasSelectedPrice(text) {
                    if (price === 0) {
                        return /(?:\+\s*)?₩\s*0\b|\b0\s+(?:South Korean won|Korean won|KRW)\b/i.test(text);
                    }
                    const compact = text.replaceAll(',', '');
                    return compact.includes(String(price));
                }
                function flightLike(el) {
                    if (!visible(el)) return false;
                    const text = textOf(el);
                    if (!text || text.length > 1800 || hardBroadRe.test(text)) return false;
                    const upper = text.toUpperCase();
                    if (!times.every(t => upper.includes(String(t).toUpperCase()))) return false;
                    if (!flightShapeRe.test(text)) return false;
                    if (!hasSelectedPrice(text)) return false;
                    return true;
                }
                function info(el, mode) {
                    if (!el || !flightLike(el)) return null;
                    const rect = el.getBoundingClientRect();
                    // For a non-semantic row fallback, avoid the far-right price/action area.
                    const x = mode === 'live-specific-row'
                      ? rect.left + Math.min(Math.max(rect.width * 0.35, 12), Math.max(rect.width - 12, 12))
                      : rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    return {
                        mode,
                        x,
                        y,
                        tag: el.tagName || '',
                        role: el.getAttribute?.('role') || '',
                        ariaLabel: el.getAttribute?.('aria-label') || '',
                        text: textOf(el).slice(0, 900),
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height
                    };
                }

                let bestSemantic = null;
                let bestPointer = null;
                let row = capturedRow;
                if (start) {
                    let node = start;
                    for (let depth = 0; depth < 18 && node; depth += 1, node = node.parentElement) {
                        if (flightLike(node)) {
                            if (node.matches?.(semanticSelector)) bestSemantic = node;
                            if (getComputedStyle(node).cursor === 'pointer') bestPointer = node;
                            if (!row) row = node;
                        }
                        if (capturedRow && node === capturedRow) break;
                    }
                }

                // Prefer the outermost specific semantic card, then the outermost
                // specific pointer card. Never accept a price-only inner action.
                let resolved = info(bestSemantic, 'live-card-semantic') || info(bestPointer, 'live-card-pointer');
                if (resolved) return resolved;
                resolved = info(row, 'live-specific-row');
                if (resolved) return resolved;

                // Captured coordinates are only seeds. Re-resolve the element at
                // that point upward into a specific flight card before clicking.
                for (const seed of [anchorRect, sourceRect]) {
                    const sx = Number(seed?.x || 0);
                    const sy = Number(seed?.y || 0);
                    if (!(sx > 0 && sy > 0)) continue;
                    let node = document.elementFromPoint(sx, sy);
                    let semantic = null;
                    let pointer = null;
                    let specific = null;
                    for (let depth = 0; depth < 18 && node; depth += 1, node = node.parentElement) {
                        if (!flightLike(node)) continue;
                        specific = node;
                        if (node.matches?.(semanticSelector)) semantic = node;
                        if (getComputedStyle(node).cursor === 'pointer') pointer = node;
                    }
                    resolved = info(semantic, 'coordinate-card-semantic') ||
                               info(pointer, 'coordinate-card-pointer') ||
                               info(specific, 'coordinate-specific-row');
                    if (resolved) return resolved;
                }
                return {};
            }""",
            {
                "candidateId": candidate_id,
                "price": price,
                "times": times,
                "anchorRect": anchor_rect,
                "sourceRect": source_rect,
            },
        )
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def click_specific_candidate(page: Page, candidate: dict, *, prefix: str) -> str:
    target = await _resolve_specific_card_target(page, candidate)
    if not target:
        raise RuntimeError(
            "Captured flight no longer resolves to a specific card-level click target; refusing inner/stale action"
        )

    print(f"{prefix}_click_target_mode={target.get('mode')}")
    print(f"{prefix}_click_target_tag={target.get('tag') or 'unknown'}")
    print(f"{prefix}_click_target_role={target.get('role') or 'none'}")
    print(f"{prefix}_click_target_aria_label={str(target.get('ariaLabel') or '')[:500]}")
    print(f"{prefix}_click_target_text={str(target.get('text') or '')[:1000]}")
    print(
        f"{prefix}_click_target_rect="
        f"{float(target.get('left') or 0):.1f},"
        f"{float(target.get('top') or 0):.1f},"
        f"{float(target.get('width') or 0):.1f},"
        f"{float(target.get('height') or 0):.1f}"
    )

    x = float(target["x"])
    y = float(target["y"])
    await page.mouse.click(x, y, delay=18)
    return str(target.get("mode") or "specific-card")


async def _install_returning_candidate_guard(page: Page) -> dict:
    """Reject stale outbound rows before they can become Returning candidates.

    The caller switches the capture phase to ``returning`` before clicking the
    outbound card so a full navigation cannot lose the next phase. During the
    short transition Google may still keep the old CJJ->TPE DOM mounted. The
    capture scanner used to re-label that old row as a Returning candidate.

    Install an instance-level ``candidates.push`` guard that:
    - rejects every Returning candidate until the Returning marker is visible;
    - requires ``returningMarkerAtSeen=True`` after the marker;
    - rejects an explicit outbound code order (origin before destination).

    Rows without both airport codes remain eligible because current Google cards
    sometimes omit route tokens; the later flight-card contract still applies.
    """
    try:
        value = await page.evaluate(
            r"""() => {
                const s = window.__flightBotCaptureV4;
                if (!s || !Array.isArray(s.candidates)) return {installed: false, purged: 0};
                const cfg = window.__flightBotInitConfig || {};
                const outboundOrigin = String(cfg.origin || '').toUpperCase();
                const outboundDestination = String(cfg.destination || '').toUpperCase();

                function normalize(text) {
                    return String(text || '')
                      .replace(/[–—‑−]/g, '-')
                      .replace(/\s+/g, ' ')
                      .trim()
                      .toUpperCase();
                }

                function valid(item) {
                    if (!item || item.phase !== 'returning') return true;
                    if (!s.returningMarker || item.returningMarkerAtSeen !== true) return false;

                    const text = normalize(item.rowText);
                    if (outboundOrigin && outboundDestination) {
                        const originIndex = text.indexOf(outboundOrigin);
                        const destinationIndex = text.indexOf(outboundDestination);
                        if (originIndex >= 0 && destinationIndex >= 0 && originIndex < destinationIndex) {
                            return false;
                        }
                    }
                    return true;
                }

                const items = s.candidates;
                const before = items.length;
                const kept = items.filter(valid);
                items.splice(0, items.length, ...kept);
                const purged = before - kept.length;

                if (!items.__flightBotStrictReturningPushInstalled) {
                    const nativePush = Array.prototype.push;
                    Object.defineProperty(items, 'push', {
                        configurable: true,
                        writable: true,
                        value: function(...nextItems) {
                            return nativePush.apply(this, nextItems.filter(valid));
                        }
                    });
                    Object.defineProperty(items, '__flightBotStrictReturningPushInstalled', {
                        configurable: true,
                        value: true
                    });
                }

                return {installed: true, purged};
            }"""
        )
    except Exception:
        return {"installed": False, "purged": 0}
    return value if isinstance(value, dict) else {"installed": False, "purged": 0}


async def _stamp_returning_phase(page: Page) -> None:
    await page.evaluate(
        """() => {
            try { sessionStorage.setItem('__flightBotPointerPhaseV4', 'returning'); } catch (_) {}
            const s = window.__flightBotCaptureV4;
            if (!s) return;
            s.phase = 'returning';
            s.phaseStartedAtMs = performance.now();
            s.returningMarker = false;
            s.returningMarkerAtMs = null;
        }"""
    )
    await _install_returning_candidate_guard(page)


async def _mark_returning_seen(page: Page) -> None:
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
        await _install_returning_candidate_guard(page)
    except Exception:
        pass


async def wait_for_returning_with_recovery(
    page: Page,
    *,
    before_url: str,
    timeout_ms: int,
    max_reloads: int,
    artifact_dir: Path | None = None,
    save_debug=None,
) -> tuple[bool, int]:
    """Distinguish a bad click from a transient Google returning-load failure.

    If the URL changed after the outbound click, Google accepted an outbound
    selection. A subsequent "couldn't load flights" surface is therefore treated
    as a recoverable returning-load failure and the selected URL is reloaded.
    If the error appears without a URL change, fail immediately because the click
    did not establish outbound-selection evidence.
    """
    guard = await _install_returning_candidate_guard(page)
    print(f"return_phase_guard_installed={guard.get('installed')}")
    print(f"return_phase_stale_candidates_purged={int(guard.get('purged') or 0)}")

    reloads = 0
    cycle_wait = max(3000, min(timeout_ms, 8000)) / 1000

    while True:
        deadline = asyncio.get_running_loop().time() + cycle_wait
        saw_selected_url = page.url != before_url

        while asyncio.get_running_loop().time() < deadline:
            try:
                body = await page.locator("body").inner_text(timeout=2500)
            except Exception:
                await page.wait_for_timeout(80)
                continue

            current_url = page.url
            url_changed = current_url != before_url
            saw_selected_url = saw_selected_url or url_changed

            if _RETURNING_RE.search(body):
                await _mark_returning_seen(page)
                print(f"departure_outbound_selection_url_changed={url_changed}")
                print(f"departure_returning_recovery_reloads={reloads}")
                return True, reloads

            if _FLIGHT_LOAD_ERROR_RE.search(body):
                print("departure_transition_error=flight-load-error")
                print(f"departure_outbound_selection_url_changed={url_changed}")
                print(f"departure_transition_url={current_url}")
                if artifact_dir is not None and save_debug is not None:
                    try:
                        await save_debug(page, artifact_dir, f"departure-flight-load-error-{reloads + 1}")
                    except Exception:
                        pass

                if not url_changed:
                    raise RuntimeError(
                        "Departure click produced a Google flight-load error before the outbound-selection URL changed"
                    )
                if reloads >= max_reloads:
                    raise RecoverableReturningLoadError(
                        f"Google accepted the outbound selection but Returning flights still failed after {reloads} reload(s)"
                    )

                reloads += 1
                selected_url = current_url
                print(f"departure_returning_recovery_reload={reloads}/{max_reloads}")
                await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                # A same-document selection followed by reload keeps sessionStorage,
                # but stamp the phase explicitly so capture cannot regress to departure.
                await _stamp_returning_phase(page)
                print(f"departure_returning_recovery_url_preserved={page.url == selected_url}")
                await asyncio.sleep(0.35)
                break

            await page.wait_for_timeout(80)
        else:
            # No explicit error text, but a changed URL means Google accepted the
            # outbound selection. One bounded reload is safer than declaring the
            # click bad while the returning client surface is silently stalled.
            if saw_selected_url and reloads < max_reloads:
                reloads += 1
                selected_url = page.url
                print("departure_transition_stalled_after_outbound_selection=True")
                print(f"departure_returning_recovery_reload={reloads}/{max_reloads}")
                await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                await _stamp_returning_phase(page)
                print(f"departure_returning_recovery_url_preserved={page.url == selected_url}")
                await asyncio.sleep(0.35)
                continue
            print(f"departure_outbound_selection_url_changed={saw_selected_url}")
            print(f"departure_returning_recovery_reloads={reloads}")
            return False, reloads
