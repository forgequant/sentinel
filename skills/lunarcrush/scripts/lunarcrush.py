# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""LunarCrush social intelligence: galaxy score, sentiment, alt rank.

Part of the Crucible Sentinel plugin.
Source: LunarCrush API v4 (lunarcrush.com/api4/public/) — premium, requires API key.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LC_BASE = "https://lunarcrush.com/api4/public"
USER_AGENT = "crucible-lunarcrush/1.0"

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "crucible" / "lunarcrush"
CACHE_FILE = CACHE_DIR / "coins.json"
CACHE_FRESH_TTL = 60       # 60 seconds (matches LC refresh)
CACHE_STALE_TTL = 1800     # 30 minutes

# Reference values for log normalization
INTERACT_REF = 50_000_000

# Signal weights
W_GALAXY = 0.4
W_SENTIMENT = 0.4
W_ALTRANK = 0.2

# Confidence weights
CW_EDGE = 0.35
CW_GALAXY = 0.25
CW_ENGAGE = 0.20
CW_MOMENTUM = 0.20


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Raised when API key is missing, empty, or rejected."""


class RateLimitError(Exception):
    """Raised when API returns 429."""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_coins(limit: int = 50, sort: str = "galaxy_score") -> list[dict]:
    """Fetch coins from LunarCrush API v4. Requires LUNARCRUSH_API_KEY."""
    api_key = os.environ.get("LUNARCRUSH_API_KEY", "").strip()
    if not api_key:
        raise AuthError(
            "LUNARCRUSH_API_KEY not set. Get a key at https://lunarcrush.com/developers/api"
        )

    url = f"{LC_BASE}/coins/list/v1?sort={sort}&limit={limit}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401 or e.code == 403:
            raise AuthError(f"Invalid or expired API key (HTTP {e.code})") from e
        if e.code == 429:
            raise RateLimitError("Rate limited by LunarCrush (HTTP 429)") from e
        return []
    except Exception:
        return []

    data = body.get("data") if isinstance(body, dict) else body
    if not isinstance(data, list):
        return []

    # Filter coins with null galaxy_score
    return [c for c in data if c.get("galaxy_score") is not None]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _save_cache(data: Any, path: Path | None = None) -> None:
    p = path or CACHE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"data": data, "ts": time.time()})
    tmp = p.with_suffix(".tmp")
    tmp.write_text(payload)
    os.replace(tmp, p)


def _load_cache(path: Path | None = None) -> tuple[Any, float]:
    p = path or CACHE_FILE
    try:
        payload = json.loads(p.read_text())
        return payload["data"], payload["ts"]
    except Exception:
        return None, 0


# ---------------------------------------------------------------------------
# Signal Computation
# ---------------------------------------------------------------------------


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _safe_num(val: Any, default: float = 0.0) -> float:
    """Safely convert to float, returning default on failure."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def normalize_coin(coin: dict) -> float:
    """Compute social_score for a single coin (0-1 range)."""
    galaxy = _clamp(_safe_num(coin.get("galaxy_score")), 0, 100) / 100
    sentiment = _clamp(_safe_num(coin.get("sentiment")), 0, 100) / 100

    alt_rank = _safe_num(coin.get("alt_rank"))
    alt_rank_prev = _safe_num(coin.get("alt_rank_previous"))

    if alt_rank_prev == 0 and alt_rank == 0:
        altrank_norm = 0.5  # no data
    elif alt_rank_prev == 0:
        altrank_norm = 0.5  # no previous data
    else:
        denom = max(alt_rank_prev, 10)
        delta = (alt_rank_prev - alt_rank) / denom
        altrank_norm = _clamp((delta + 1) / 2, 0, 1)

    return W_GALAXY * galaxy + W_SENTIMENT * sentiment + W_ALTRANK * altrank_norm


def compute_signal(coins: list[dict]) -> dict:
    """Compute aggregate signal from normalized coin scores."""
    if not coins:
        return {
            "signal": "neutral",
            "avg_social": 0.5,
            "avg_galaxy": 0.0,
            "avg_sentiment": 0.0,
            "avg_alt_rank": 0.0,
            "total_interactions": 0,
        }

    # Compute per-coin scores and weights
    scores: list[float] = []
    weights: list[float] = []
    total_galaxy = 0.0
    total_sentiment = 0.0
    total_alt_rank = 0.0
    total_interactions = 0

    for c in coins:
        score = normalize_coin(c)
        scores.append(score)
        dom = _safe_num(c.get("social_dominance"))
        weights.append(dom)
        total_galaxy += _safe_num(c.get("galaxy_score"))
        total_sentiment += _safe_num(c.get("sentiment"))
        total_alt_rank += _safe_num(c.get("alt_rank"))
        total_interactions += int(_safe_num(c.get("interactions_24h")))

    # Weighted average by social_dominance (fallback to simple average)
    total_weight = sum(weights)
    if total_weight > 0:
        avg_social = sum(s * w for s, w in zip(scores, weights)) / total_weight
    else:
        avg_social = sum(scores) / len(scores)

    n = len(coins)
    if avg_social > 0.60:
        signal = "bullish"
    elif avg_social < 0.40:
        signal = "bearish"
    else:
        signal = "neutral"

    return {
        "signal": signal,
        "avg_social": round(avg_social, 4),
        "avg_galaxy": round(total_galaxy / n, 2),
        "avg_sentiment": round(total_sentiment / n, 2),
        "avg_alt_rank": round(total_alt_rank / n, 2),
        "total_interactions": total_interactions,
    }


# ---------------------------------------------------------------------------
# Movers Detection
# ---------------------------------------------------------------------------


def detect_movers(coins: list[dict], top_n: int = 5) -> dict:
    """Detect biggest alt_rank movers (improving and declining)."""
    movers: list[dict] = []

    for c in coins:
        rank = _safe_num(c.get("alt_rank"))
        prev = _safe_num(c.get("alt_rank_previous"))
        if prev == 0 or rank == 0:
            continue
        delta = int(prev - rank)  # positive = improving
        if delta == 0:
            continue
        movers.append({
            "symbol": c.get("symbol", "?"),
            "alt_rank": int(rank),
            "alt_rank_previous": int(prev),
            "delta": delta,
        })

    improving = sorted([m for m in movers if m["delta"] > 0], key=lambda m: m["delta"], reverse=True)[:top_n]
    declining = sorted([m for m in movers if m["delta"] < 0], key=lambda m: m["delta"])[:top_n]

    return {"improving": improving, "declining": declining}


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def compute_confidence(
    signal_edge: float,
    avg_galaxy: float = 0,
    total_interactions: float = 0,
    avg_altrank_delta: float = 0,
) -> int:
    """Compute confidence score (15-100) using 4-factor formula."""
    edge = _clamp(signal_edge, 0, 1)
    galaxy_str = _clamp(avg_galaxy / 80, 0, 1) if avg_galaxy > 0 else 0
    engage = _clamp(math.log1p(max(0, total_interactions)) / math.log1p(INTERACT_REF), 0, 1) if total_interactions > 0 else 0
    momentum = _clamp(abs(avg_altrank_delta) * 5, 0, 1)

    raw = CW_EDGE * edge + CW_GALAXY * galaxy_str + CW_ENGAGE * engage + CW_MOMENTUM * momentum
    return max(15, min(100, round(15 + 85 * raw)))


# ---------------------------------------------------------------------------
# CLI & Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(prog="lunarcrush")
    parser.add_argument("--limit", type=int, default=50, help="Max coins to fetch")
    parser.add_argument("--sort", default="galaxy_score",
                        choices=["galaxy_score", "alt_rank", "sentiment", "interactions_24h"],
                        help="Sort field")
    parser.add_argument("--coins", type=str, default="", help="Comma-separated coin filter (e.g. BTC,ETH)")
    parser.add_argument("--min-galaxy", type=int, default=0, help="Min galaxy score filter")
    args = parser.parse_args()

    coin_filter = [c.strip().upper() for c in args.coins.split(",") if c.strip()] if args.coins else []

    # Try fetch → fresh cache → stale cache → neutral
    coins: list[dict] = []
    from_cache = False
    cache_age = 0.0

    try:
        coins = fetch_coins(limit=args.limit, sort=args.sort)
        if coins:
            _save_cache(coins)
    except AuthError as e:
        print(f"  LunarCrush auth error: {e}", file=sys.stderr)
        json.dump({
            "schema": "signal/v1",
            "signal": "neutral",
            "confidence": 0,
            "reasoning": str(e),
            "data": {},
            "analytics": {},
        }, sys.stdout)
        print(file=sys.stdout)
        return
    except RateLimitError:
        coins = []  # fall through to cache

    if not coins:
        cached, ts = _load_cache()
        if cached is not None:
            cache_age = time.time() - ts
            if cache_age < CACHE_STALE_TTL:
                coins = cached
                from_cache = True

    if not coins:
        # Total fallback: neutral
        print("  LunarCrush: no data available", file=sys.stderr)
        json.dump({
            "schema": "signal/v1",
            "signal": "neutral",
            "confidence": 15,
            "reasoning": "No data available from LunarCrush API or cache",
            "data": {"count": 0},
            "analytics": {},
        }, sys.stdout)
        print(file=sys.stdout)
        return

    # Filter by min galaxy score
    if args.min_galaxy > 0:
        coins = [c for c in coins if _safe_num(c.get("galaxy_score")) >= args.min_galaxy]

    # Filter by coin symbols
    if coin_filter:
        coins = [c for c in coins if c.get("symbol", "").upper() in coin_filter]

    # Compute signal
    sig = compute_signal(coins)

    # Detect movers
    movers = detect_movers(coins)

    # Compute confidence
    signal_edge = abs(sig["avg_social"] - 0.5) * 2
    # Average altrank delta across coins
    altrank_deltas: list[float] = []
    for c in coins:
        prev = _safe_num(c.get("alt_rank_previous"))
        cur = _safe_num(c.get("alt_rank"))
        if prev > 0 and cur > 0:
            altrank_deltas.append((prev - cur) / max(prev, 10))
    avg_altrank_delta = sum(altrank_deltas) / len(altrank_deltas) if altrank_deltas else 0

    confidence = compute_confidence(
        signal_edge=signal_edge,
        avg_galaxy=sig["avg_galaxy"],
        total_interactions=sig["total_interactions"],
        avg_altrank_delta=avg_altrank_delta,
    )

    # Stale cache penalty
    if from_cache and cache_age > CACHE_FRESH_TTL:
        confidence = max(15, confidence - 10)

    # Top coins for output
    top_coins = []
    for c in sorted(coins, key=lambda c: _safe_num(c.get("galaxy_score")), reverse=True)[:10]:
        top_coins.append({
            "symbol": c.get("symbol", "?"),
            "galaxy_score": _safe_num(c.get("galaxy_score")),
            "sentiment": _safe_num(c.get("sentiment")),
            "alt_rank": int(_safe_num(c.get("alt_rank"))),
            "social_dominance": _safe_num(c.get("social_dominance")),
        })

    reasoning = (
        f"Galaxy Score avg {sig['avg_galaxy']:.0f}/100, "
        f"sentiment {sig['avg_sentiment']:.0f}% bullish across {len(coins)} coins"
    )
    if from_cache:
        reasoning += f" (cached {cache_age:.0f}s ago)"

    output = {
        "schema": "signal/v1",
        "signal": sig["signal"],
        "confidence": confidence,
        "reasoning": reasoning,
        "data": {
            "count": len(coins),
            "avg_galaxy_score": sig["avg_galaxy"],
            "avg_sentiment": sig["avg_sentiment"],
            "avg_alt_rank": sig["avg_alt_rank"],
            "total_interactions_24h": sig["total_interactions"],
            "top_coins": top_coins,
            "movers": movers,
        },
        "analytics": {
            "confidence_components": {
                "signal_edge": round(signal_edge, 4),
                "galaxy_strength": round(_clamp(sig["avg_galaxy"] / 80, 0, 1), 4),
                "engagement": round(
                    _clamp(
                        math.log1p(max(0, sig["total_interactions"])) / math.log1p(INTERACT_REF),
                        0, 1
                    ), 4
                ),
                "momentum": round(_clamp(abs(avg_altrank_delta) * 5, 0, 1), 4),
            },
        },
    }

    # Human summary to stderr
    print(f"  LunarCrush: {len(coins)} coins analyzed", file=sys.stderr)
    print(
        f"  Signal: {sig['signal']} | Galaxy avg: {sig['avg_galaxy']:.0f} | "
        f"Sentiment: {sig['avg_sentiment']:.0f}% | Confidence: {confidence}/100",
        file=sys.stderr,
    )
    if top_coins:
        top_syms = [c["symbol"] for c in top_coins[:5]]
        print(f"  Top by Galaxy: {', '.join(top_syms)}", file=sys.stderr)
    if movers["improving"]:
        imp = [f"{m['symbol']}(+{m['delta']})" for m in movers["improving"][:3]]
        print(f"  Improving: {', '.join(imp)}", file=sys.stderr)
    if movers["declining"]:
        dec = [f"{m['symbol']}({m['delta']})" for m in movers["declining"][:3]]
        print(f"  Declining: {', '.join(dec)}", file=sys.stderr)
    if from_cache:
        print(f"  (from cache, {cache_age:.0f}s old)", file=sys.stderr)

    json.dump(output, sys.stdout, indent=None)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
