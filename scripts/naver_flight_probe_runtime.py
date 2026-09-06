from __future__ import annotations

import asyncio
import sys

import naver_flight_probe as base


# Naver's result UI frequently splits a visible price across nested spans.  The
# original POC only inspected direct text nodes on a candidate element, which can
# leave the browser visibly showing prices while the extractor sees no anchors.
#
# This runtime extractor keeps the same safety boundary (results page only; no
# booking navigation) but uses rendered descendant text, crosses open shadow-root
# hosts while walking upward, and has a second compact-container pass.  A row is
# still accepted only when the same compact context contains a plausible fare and
# at least two flight times, so we do not fall back to a body-wide minimum price.
ROBUST_COLLECT_ROWS_JS = r"""
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

  function textOf(el) {
    if (!(el instanceof Element)) return '';
    return clean(
      (el.innerText || el.textContent || '') + ' ' +
      (el.getAttribute('aria-label') || '') + ' ' +
      (el.getAttribute('title') || '')
    );
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
    const seen = new Set();
    const roots = [root];
    while (roots.length) {
      const current = roots.pop();
      if (!current || !current.querySelectorAll) continue;
      for (const el of current.querySelectorAll('*')) {
        if (!seen.has(el)) {
          seen.add(el);
          out.push(el);
        }
        if (el.shadowRoot) roots.push(el.shadowRoot);
      }
    }
    return out;
  }

  function parentOf(node) {
    if (!node) return null;
    if (node.parentElement) return node.parentElement;
    const root = node.getRootNode ? node.getRootNode() : null;
    return root && root.host instanceof Element ? root.host : null;
  }

  function semanticContainer(node) {
    const tag = (node.tagName || '').toLowerCase();
    const role = (node.getAttribute && node.getAttribute('role')) || '';
    const cls = String(node.className || '');
    return /^(li|article|button|a)$/.test(tag) || role === 'listitem' ||
      /flight|result|item|card|schedule|ticket|fare|air/i.test(cls);
  }

  function scoreCandidate(node, text, times) {
    let score = 0;
    if (times.length >= 2 && times.length <= 14) score += 7;
    if (directRe.test(text)) score += 3;
    if (roundTripRe.test(text)) score += 2;
    if (routeRe.test(text)) score += 2;
    if (flightRe.test(text)) score += 1;
    if (semanticContainer(node)) score += 2;
    if (text.length <= 1400) score += 1;
    return score;
  }

  function candidateFrom(node, price, depth) {
    const text = textOf(node);
    if (!text || text.length < 20 || text.length > 3200) return null;
    if (excludeRe.test(text) && !directRe.test(text)) return null;
    const times = text.match(timeRe) || [];
    if (times.length < 2) return null;
    const prices = parsePrices(text, priceHint(node));
    if (!prices.includes(price)) return null;
    const score = scoreCandidate(node, text, times);
    if (score < 7) return null;
    return {
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
  }

  const elements = allElements(document);
  const rows = [];
  const anchors = [];
  const seenRows = new Set();
  const seenAnchors = new Set();

  function addRow(candidate) {
    if (!candidate) return;
    const key = `${candidate.price}|${candidate.times.slice(0, 2).join('|')}|${candidate.text.slice(0, 600).toUpperCase()}`;
    if (seenRows.has(key)) return;
    seenRows.add(key);
    rows.push(candidate);
  }

  // Pass 1: find compact rendered price anchors.  Descendant text is used on
  // purpose because Naver often renders `319,620` and `원` in nested spans.
  for (const el of elements) {
    if (!visible(el)) continue;
    const rendered = textOf(el);
    if (!rendered || rendered.length > 320) continue;
    const hinted = priceHint(el);
    const prices = parsePrices(rendered, hinted);
    if (!prices.length) continue;

    const anchorKey = `${prices.join(',')}|${rendered}`;
    if (!seenAnchors.has(anchorKey) && anchors.length < 80) {
      seenAnchors.add(anchorKey);
      anchors.push({
        prices,
        text: rendered.slice(0, 260),
        tag: el.tagName,
        class_name: String(el.className || '').slice(0, 220),
        hinted,
      });
    }

    for (const price of prices) {
      let node = el;
      let best = null;
      for (let depth = 0; depth < 18 && node; depth += 1, node = parentOf(node)) {
        const candidate = candidateFrom(node, price, depth);
        if (!candidate) continue;
        if (!best || candidate.score > best.score ||
            (candidate.score === best.score && candidate.text.length < best.text.length)) {
          best = candidate;
        }
      }
      addRow(best);
    }
  }

  // Pass 2: independent compact-container scan.  This catches layouts where no
  // small element contains the complete visible price token.  It is deliberately
  // not body-wide: the same compact element must contain >=2 times plus the fare.
  for (const el of elements) {
    if (!visible(el)) continue;
    if (!semanticContainer(el)) continue;
    const text = textOf(el);
    if (!text || text.length < 40 || text.length > 2200) continue;
    const times = text.match(timeRe) || [];
    if (times.length < 2 || times.length > 14) continue;
    const prices = parsePrices(text, priceHint(el));
    for (const price of prices) addRow(candidateFrom(el, price, 0));
  }

  rows.sort((a, b) => b.score - a.score || a.price - b.price || a.text.length - b.text.length);
  const bodyText = clean(document.body && (document.body.innerText || document.body.textContent));
  return {
    rows: rows.slice(0, 32),
    price_anchors: anchors,
    body_has_direct: directRe.test(bodyText),
    body_has_round_trip: roundTripRe.test(bodyText),
    body_text_length: bodyText.length,
    body_price_samples: parsePrices(bodyText, false).slice(0, 20),
  };
}
"""


# Patch only the extractor.  Navigation, result-page-only behavior, artifact
# capture, timeout handling, and the no-booking boundary stay in the original POC.
base._COLLECT_ROWS_JS = ROBUST_COLLECT_ROWS_JS

DEFAULT_ORIGIN = base.DEFAULT_ORIGIN
DEFAULT_DESTINATION = base.DEFAULT_DESTINATION
DEFAULT_DEPART = base.DEFAULT_DEPART
DEFAULT_RETURN = base.DEFAULT_RETURN
NaverProbeResult = base.NaverProbeResult
build_naver_url = base.build_naver_url
collect_naver_visible_results = base.collect_naver_visible_results


if __name__ == "__main__":
    if not sys.platform.startswith("win"):
        raise SystemExit("This POC is intended for Windows visible Edge testing")
    raise SystemExit(asyncio.run(base.run(base.parse_args())))
