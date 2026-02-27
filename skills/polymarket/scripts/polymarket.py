# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Polymarket prediction markets: crypto crowd-sourced probabilities.

Part of the Crucible Sentinel plugin.
Sources: Polymarket Gamma API (gamma-api.polymarket.com) — free, no auth.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GAMMA_BASE = "https://gamma-api.polymarket.com"
DEFAULT_TAG_SLUGS = ["crypto", "bitcoin", "ethereum", "solana"]
USER_AGENT = "crucible-polymarket/1.0"

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "crucible" / "polymarket"
CACHE_FILE = CACHE_DIR / "events.json"
CACHE_FRESH_TTL = 900  # 15 minutes
CACHE_STALE_TTL = 7200  # 2 hours

# Bullish/bearish keyword patterns for binary market classification
BULLISH_WORDS = re.compile(
    r"\b(reach|surpass|hit|above|approve|launch|adopt|break|exceed|pass)\b", re.I
)
BEARISH_WORDS = re.compile(
    r"\b(crash|ban|reject|fall|below|fail|hack|bankrupt|drop|decline|lose)\b", re.I
)

# Strike extraction: $80,000 | $80k | $80K | 80000 | 80,000
STRIKE_PATTERNS = [
    re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*[kK]"),       # $80k, $150K
    re.compile(r"\$\s*([\d,]+(?:\.\d+)?)"),                # $80,000 or $80000
    re.compile(r"\b(\d{2,3})[kK]\b"),                       # 80k, 150K (no $)
    re.compile(r"\b(\d[\d,]{3,})\b"),                       # 80000, 80,000 (plain big numbers)
]

# Coin detection (simplified top-15 for prediction markets)
COIN_MAP: list[tuple[str, re.Pattern]] = [
    ("BTC", re.compile(r"\bbitcoin\b|\bBTC\b|\$BTC\b", re.I)),
    ("ETH", re.compile(r"\bethereum\b|\bETH\b|\$ETH\b", re.I)),
    ("SOL", re.compile(r"\bsolana\b|\$SOL\b")),
    ("XRP", re.compile(r"\bripple\b|\bXRP\b|\$XRP\b", re.I)),
    ("BNB", re.compile(r"\bbinance\b|\bBNB\b|\$BNB\b", re.I)),
    ("ADA", re.compile(r"\bcardano\b|\bADA\b|\$ADA\b", re.I)),
    ("DOGE", re.compile(r"\bdogecoin\b|\bDOGE\b|\$DOGE\b", re.I)),
    ("AVAX", re.compile(r"\bavalanche\b|\bAVAX\b|\$AVAX\b", re.I)),
    ("DOT", re.compile(r"\bpolkadot\b", re.I)),
    ("LINK", re.compile(r"\bchainlink\b|\$LINK\b", re.I)),
    ("MATIC", re.compile(r"\bpolygon\b|\bMATIC\b|\$MATIC\b", re.I)),
    ("UNI", re.compile(r"\buniswap\b|\$UNI\b", re.I)),
    ("AAVE", re.compile(r"\baave\b|\$AAVE\b", re.I)),
    ("OP", re.compile(r"\boptimism\b", re.I)),
    ("ARB", re.compile(r"\barbitrum\b|\$ARB\b", re.I)),
]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_events(
    tag_slugs: list[str] | None = None, limit: int = 50
) -> list[dict]:
    """Fetch events from Gamma API across multiple tag_slugs, dedup by event.id."""
    slugs = tag_slugs or DEFAULT_TAG_SLUGS
    seen_ids: set[str] = set()
    all_events: list[dict] = []

    for slug in slugs:
        url = f"{GAMMA_BASE}/events?tag_slug={slug}&closed=false&limit={limit}&order=volume24hr&ascending=false"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception:
            continue

        if not isinstance(data, list):
            continue

        for ev in data:
            eid = str(ev.get("id", ""))
            if not eid or eid in seen_ids:
                continue
            seen_ids.add(eid)
            all_events.append(ev)

    return all_events


def parse_probability(market: dict) -> float | None:
    """Extract Yes probability from a market's outcomePrices."""
    raw_prices = market.get("outcomePrices")
    raw_outcomes = market.get("outcomes")
    if not raw_prices:
        return None

    try:
        prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
        outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else (raw_outcomes or [])
    except (json.JSONDecodeError, TypeError):
        return None

    if not prices:
        return None

    # Find "Yes" outcome index
    for i, label in enumerate(outcomes):
        if isinstance(label, str) and label.lower() == "yes":
            try:
                return float(prices[i])
            except (IndexError, ValueError, TypeError):
                return None

    # Fallback: first price
    try:
        return float(prices[0])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _save_cache(data: Any, path: Path | None = None) -> None:
    p = path or CACHE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"data": data, "ts": time.time()}
    p.write_text(json.dumps(payload))


def _load_cache(path: Path | None = None) -> tuple[Any, float]:
    p = path or CACHE_FILE
    try:
        payload = json.loads(p.read_text())
        return payload["data"], payload["ts"]
    except Exception:
        return None, 0


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_event(event: dict) -> dict:
    """Classify event: type (binary/curve), horizon (daily/structural), direction."""
    markets = event.get("markets") or []
    title = event.get("title", "")

    # Horizon
    end_date_str = event.get("endDate")
    horizon = "structural"
    days_to_expiry = 365.0
    if end_date_str:
        try:
            end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = (end_dt - now).total_seconds() / 86400
            days_to_expiry = max(0.0, delta)
            horizon = "daily" if delta < 7 else "structural"
        except (ValueError, TypeError):
            pass

    # Type: curve if ≥2 sub-markets have parseable strikes
    strike_count = sum(1 for m in markets if extract_strike(m.get("question", "")) is not None)
    event_type = "curve" if strike_count >= 2 else "binary"

    # Direction (from title + market questions)
    all_text = title + " " + " ".join(m.get("question", "") for m in markets)
    has_bull = bool(BULLISH_WORDS.search(all_text))
    has_bear = bool(BEARISH_WORDS.search(all_text))
    if has_bull and not has_bear:
        direction = "bullish"
    elif has_bear and not has_bull:
        direction = "bearish"
    else:
        direction = "neutral"

    event["_type"] = event_type
    event["_horizon"] = horizon
    event["_direction"] = direction
    event["_days_to_expiry"] = days_to_expiry
    return event


# ---------------------------------------------------------------------------
# Price Curve
# ---------------------------------------------------------------------------


def extract_strike(question: str) -> float | None:
    """Extract a numeric strike value from a market question."""
    for pat in STRIKE_PATTERNS:
        m = pat.search(question)
        if m:
            raw = m.group(1).replace(",", "")
            try:
                val = float(raw)
                # If matched k/K pattern, multiply by 1000
                if pat is STRIKE_PATTERNS[0] or pat is STRIKE_PATTERNS[2]:
                    val *= 1000
                return val
            except ValueError:
                continue
    return None


def build_price_curve(event: dict) -> dict | None:
    """Build implied probability curve from multi-strike event. Returns None if <2 strikes."""
    markets = event.get("markets") or []
    points: list[tuple[float, float]] = []

    for m in markets:
        if m.get("closed"):
            continue
        strike = extract_strike(m.get("question", ""))
        prob = parse_probability(m)
        if strike is not None and prob is not None:
            points.append((strike, prob))

    if len(points) < 2:
        return None

    points.sort(key=lambda p: p[0])
    strikes = [p[0] for p in points]
    probs = [p[1] for p in points]

    # Median: find strike where probability crosses 0.5
    median = strikes[-1]  # default to highest strike
    for i in range(len(probs) - 1):
        if probs[i] >= 0.5 >= probs[i + 1]:
            # Linear interpolation
            if probs[i] != probs[i + 1]:
                frac = (probs[i] - 0.5) / (probs[i] - probs[i + 1])
                median = strikes[i] + frac * (strikes[i + 1] - strikes[i])
            else:
                median = (strikes[i] + strikes[i + 1]) / 2
            break
    else:
        # If probabilities are all > 0.5 or all < 0.5
        if probs[0] < 0.5:
            median = strikes[0]

    # Spread: IQR (25th to 75th percentile strikes)
    def _find_percentile(target: float) -> float:
        for i in range(len(probs) - 1):
            if probs[i] >= target >= probs[i + 1]:
                if probs[i] != probs[i + 1]:
                    frac = (probs[i] - target) / (probs[i] - probs[i + 1])
                    return strikes[i] + frac * (strikes[i + 1] - strikes[i])
                return (strikes[i] + strikes[i + 1]) / 2
        return strikes[0] if probs[0] < target else strikes[-1]

    p25 = _find_percentile(0.75)  # P(above X) = 0.75 → 25th percentile
    p75 = _find_percentile(0.25)  # P(above X) = 0.25 → 75th percentile
    spread = p75 - p25

    # Skew: simple measure based on median position in IQR
    skew = 0.0
    if spread > 0:
        skew = 2 * (median - (p25 + p75) / 2) / spread

    return {
        "strikes": strikes,
        "probabilities": probs,
        "median": round(median, 2),
        "spread": round(spread, 2),
        "skew": round(skew, 3),
        "n_points": len(points),
    }


# ---------------------------------------------------------------------------
# Coin Detection
# ---------------------------------------------------------------------------


def detect_coins(text: str) -> list[str]:
    """Detect coin mentions in text."""
    found: list[str] = []
    for symbol, pattern in COIN_MAP:
        if pattern.search(text):
            found.append(symbol)
    return found


# ---------------------------------------------------------------------------
# Directional Scoring
# ---------------------------------------------------------------------------


def bullish_probability(market: dict) -> float | None:
    """Compute bullish probability for a single market. None if unclassifiable."""
    question = market.get("question", "")
    prob = parse_probability(market)
    if prob is None:
        return None

    has_bull = bool(BULLISH_WORDS.search(question))
    has_bear = bool(BEARISH_WORDS.search(question))

    if has_bull and not has_bear:
        return prob
    elif has_bear and not has_bull:
        return 1.0 - prob
    return None


def compute_signal(events: list[dict]) -> dict:
    """Compute aggregate directional signal from classified events."""
    bull_probs: list[float] = []
    daily_count = 0
    structural_count = 0

    for ev in events:
        horizon = ev.get("_horizon", "structural")
        if horizon == "daily":
            daily_count += 1
        else:
            structural_count += 1

        for m in ev.get("markets") or []:
            bp = bullish_probability(m)
            if bp is not None:
                bull_probs.append(bp)

    if not bull_probs:
        return {
            "signal": "neutral",
            "avg_bullish": 0.5,
            "directional_count": 0,
            "horizon_breakdown": {"daily": daily_count, "structural": structural_count},
        }

    avg_bull = sum(bull_probs) / len(bull_probs)

    if avg_bull > 0.6:
        signal = "bullish"
    elif avg_bull < 0.4:
        signal = "bearish"
    else:
        signal = "neutral"

    return {
        "signal": signal,
        "avg_bullish": round(avg_bull, 4),
        "directional_count": len(bull_probs),
        "horizon_breakdown": {"daily": daily_count, "structural": structural_count},
    }


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

# Reference values for log normalization
LIQ_REF = 1_000_000
VOL_REF = 5_000_000


def compute_confidence(
    signal_edge: float,
    liquidity: float = 0,
    volume24hr: float = 0,
    n_markets: int = 0,
    median_days_to_expiry: float = 365,
) -> int:
    """Compute confidence score (15-100) using 5-factor formula."""
    edge = min(1.0, max(0.0, signal_edge))
    liq = min(1.0, math.log1p(max(0, liquidity)) / math.log1p(LIQ_REF)) if liquidity > 0 else 0
    vol = min(1.0, math.log1p(max(0, volume24hr)) / math.log1p(VOL_REF)) if volume24hr > 0 else 0
    depth = min(1.0, max(0, n_markets - 1) / 20)
    time_rel = 1.0 / (1.0 + max(0, median_days_to_expiry) / 30)

    raw = 0.45 * edge + 0.20 * liq + 0.15 * vol + 0.10 * depth + 0.10 * time_rel
    return max(15, min(100, round(15 + 85 * raw)))


# ---------------------------------------------------------------------------
# CLI & Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(prog="polymarket")
    parser.add_argument("--limit", type=int, default=50, help="Max events per tag_slug")
    parser.add_argument("--min-volume", type=float, default=1000, help="Min volume USD")
    parser.add_argument("--horizon", choices=["all", "daily", "structural"], default="all")
    parser.add_argument("--coins", type=str, default="", help="Comma-separated coin filter")
    args = parser.parse_args()

    coin_filter = [c.strip().upper() for c in args.coins.split(",") if c.strip()] if args.coins else []

    # Cache check
    cached, ts = _load_cache()
    age = time.time() - ts
    if cached is not None and age < CACHE_FRESH_TTL:
        events = cached
    else:
        events = fetch_events(limit=args.limit)
        if events:
            _save_cache(events)
        elif cached is not None and age < CACHE_STALE_TTL:
            events = cached

    # Classify
    for ev in events:
        classify_event(ev)

    # Filter by volume
    events = [ev for ev in events if float(ev.get("volume24hr") or 0) >= args.min_volume]

    # Filter by horizon
    if args.horizon != "all":
        events = [ev for ev in events if ev.get("_horizon") == args.horizon]

    # Filter by coins
    if coin_filter:
        filtered = []
        for ev in events:
            all_text = ev.get("title", "") + " " + " ".join(
                m.get("question", "") for m in ev.get("markets", [])
            )
            coins = detect_coins(all_text)
            if any(c in coin_filter for c in coins):
                filtered.append(ev)
        events = filtered

    # Compute signal
    sig = compute_signal(events)

    # Gather price curves
    price_curves: dict[str, dict] = {}
    for ev in events:
        if ev.get("_type") == "curve":
            curve = build_price_curve(ev)
            if curve:
                all_text = ev.get("title", "")
                coins = detect_coins(all_text)
                for coin in coins:
                    if coin not in price_curves:
                        price_curves[coin] = curve

    # Aggregate metrics for confidence
    total_liq = sum(float(ev.get("liquidity") or 0) for ev in events)
    total_vol24 = sum(float(ev.get("volume24hr") or 0) for ev in events)
    total_markets = sum(len(ev.get("markets") or []) for ev in events)
    days_list = [ev.get("_days_to_expiry", 365) for ev in events]
    median_days = sorted(days_list)[len(days_list) // 2] if days_list else 365

    signal_edge = abs(sig["avg_bullish"] - 0.5) * 2
    confidence = compute_confidence(signal_edge, total_liq, total_vol24, total_markets, median_days)

    # Trending coins
    coin_counts: dict[str, int] = {}
    for ev in events:
        all_text = ev.get("title", "") + " " + " ".join(
            m.get("question", "") for m in ev.get("markets", [])
        )
        for c in detect_coins(all_text):
            coin_counts[c] = coin_counts.get(c, 0) + 1
    trending = sorted(coin_counts, key=lambda c: coin_counts[c], reverse=True)

    # Build market summaries
    market_summaries = []
    for ev in events[:20]:
        for m in (ev.get("markets") or [])[:3]:
            prob = parse_probability(m)
            if prob is None:
                continue
            market_summaries.append({
                "question": m.get("question", ""),
                "probability": round(prob, 4),
                "volume_usd": round(float(m.get("volume") or 0), 2),
                "liquidity_usd": round(float(m.get("liquidity") or 0), 2),
                "end_date": m.get("endDate"),
                "url": f"https://polymarket.com/event/{ev.get('slug', '')}",
            })

    reasoning = (
        f"Avg bullish probability {sig['avg_bullish']:.0%} across "
        f"{sig['directional_count']} directional markets from {len(events)} events"
    )

    output = {
        "schema": "signal/v1",
        "signal": sig["signal"],
        "confidence": confidence,
        "reasoning": reasoning,
        "data": {
            "count": len(events),
            "directional_count": sig["directional_count"],
            "avg_bullish_probability": sig["avg_bullish"],
            "markets": market_summaries,
            "price_curves": price_curves,
            "trending_coins": trending,
            "horizon_breakdown": sig["horizon_breakdown"],
        },
        "analytics": {
            "confidence_components": {
                "signal_edge": round(signal_edge, 4),
                "liquidity": round(total_liq, 2),
                "volume_24h": round(total_vol24, 2),
                "depth": total_markets,
                "median_days_to_expiry": round(median_days, 1),
            },
        },
    }

    # Human summary to stderr
    print(
        f"  Polymarket: {len(events)} events, {sig['directional_count']} directional markets",
        file=sys.stderr,
    )
    print(
        f"  Signal: {sig['signal']} | Avg bullish: {sig['avg_bullish']:.0%} | Confidence: {confidence}/100",
        file=sys.stderr,
    )
    if trending:
        print(f"  Trending: {', '.join(trending[:5])}", file=sys.stderr)
    if price_curves:
        for coin, curve in list(price_curves.items())[:3]:
            print(
                f"  {coin} curve: median=${curve['median']:,.0f}, spread=${curve['spread']:,.0f}, skew={curve['skew']:.2f}",
                file=sys.stderr,
            )

    json.dump(output, sys.stdout, indent=None)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
