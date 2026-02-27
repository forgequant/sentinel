# polymarket v1 Design

**Date:** 2026-02-27
**Status:** Approved (with Codex feedback incorporated)
**Codex Rating of aitrader:** 5/10

## Sources

Gamma API (`gamma-api.polymarket.com`), free, no auth.

| Endpoint | Parameters | Purpose |
|----------|-----------|---------|
| `/events` | `tag_slug=crypto`, `closed=false` | Primary crypto events (100+) |
| `/events` | `tag_slug=bitcoin`, `closed=false` | Bitcoin-specific events (100+) |
| `/events` | `tag_slug=ethereum`, `closed=false` | Ethereum events (100+) |
| `/events` | `tag_slug=solana`, `closed=false` | Solana events (100+) |

Deduplicate by `event.id`. No general-volume fallback (too noisy).

**Key API findings:**
- `tag=crypto` does NOT filter. Must use `tag_slug=crypto`
- `cryptocurrency` slug exists but has 0 events — useless
- Responses Cloudflare-cached 2 min (`max-age=120`), no benefit polling faster
- No auth required, no rate limits observed
- Volume fields: `volume`, `volume24hr`, `volume1wk`, `volume1mo`, `volume1yr` (all USDC)
- Market fields also include: `lastTradePrice`, `bestBid`, `bestAsk`, `spread`

## Event Types

Two classes, explicitly separated:

| Type | Example | Horizon | Signal Use |
|------|---------|---------|------------|
| **daily/near-term** | "Bitcoin above $80k on Feb 27?" | <7 days | Trading signal |
| **structural** | "Will China unban Bitcoin by 2027?" | >7 days | Regime signal |

Horizon multiplier in confidence: `1.0 / (1.0 + days_to_expiry / 30)`.

## Market Classification

### Binary Markets (yes/no)
Single question with Yes probability. Classify directionality:
- **Bullish** keywords: reach, surpass, hit, above, approve, launch, adopt, break
- **Bearish** keywords: crash, ban, reject, fall, below, fail, hack, bankrupt
- **Structural**: doesn't match either → excluded from directional signal

### Price-Curve Markets (implied distribution)
Events with multiple strike-level sub-markets (e.g., "BTC reaches $80k/$90k/$100k/$120k/$150k"):
1. Parse numeric strike from question text: `r"\$[\d,]+k?"`
2. Sort by strike value
3. Extract Yes probability at each strike → implied survival curve
4. Compute: **median** (50th percentile), **spread** (IQR), **skew**
5. Fallback to max-Yes if parsing fails

## Confidence Formula (5-factor, per Codex)

```
signal_edge = abs(avg_bullish - 0.5) * 2          # 0-1, how decisive
liq = clamp(log1p(liquidity) / log1p(1_000_000), 0, 1)
vol = clamp(log1p(volume24hr) / log1p(5_000_000), 0, 1)
depth = clamp((n_markets - 1) / 20, 0, 1)
time = 1.0 / (1.0 + median_days_to_expiry / 30)

confidence = round(15 + 85 * (0.45*signal_edge + 0.20*liq + 0.15*vol + 0.10*depth + 0.10*time))
```

Clamped to [15, 100].

## Coin Detection

Extract coin mentions from event titles and market questions.
Same approach as news-scanner: regex word-boundary matching for top-30 coins.

## Cache

- Event-level cache at `~/.cache/crucible/polymarket/events.json`
- Fresh TTL: 15 minutes
- Stale window: 2 hours
- Rate limiting: minimum 600ms between API calls

## CLI

```
--limit 50        # max events to fetch per tag
--min-volume 1000 # filter low-volume markets (USD)
--horizon all     # all | daily | structural
--coins BTC,ETH   # filter by coin symbols
```

## Output (SignalOutput v1)

```json
{
  "schema": "signal/v1",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "Crowd expects 72% BTC above $80k, bullish across 18 directional markets",
  "data": {
    "count": 42,
    "directional_count": 18,
    "avg_bullish_probability": 0.65,
    "markets": [...],
    "price_curves": {
      "BTC": {"median": 82000, "spread": 15000, "skew": -0.3, "strikes": [...]}
    },
    "trending_coins": ["BTC", "ETH"],
    "horizon_breakdown": {"daily": 12, "structural": 6}
  },
  "analytics": {
    "confidence_components": {
      "signal_edge": 0.30,
      "liquidity": 0.85,
      "volume": 0.72,
      "depth": 0.45,
      "time_relevance": 0.60
    }
  }
}
```

## Architecture

Single file `polymarket.py` (~350-400 lines), stdlib-only, PEP 723.
Sections: fetch (3 tag_slugs) → cache → classify (binary vs curve) → coin detect → score → confidence → CLI.
