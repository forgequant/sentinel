# LunarCrush v1 Design

**Date:** 2026-02-27
**Status:** Approved (with Codex feedback incorporated)
**Codex Rating of aitrader:** bash wrapper only, no signal logic (lc.sh 35 lines)
**Codex Rating of this design:** 6-7/10 (incorporated feedback below)

## Sources

LunarCrush API v4 (`lunarcrush.com/api4/public/`), paid, Bearer token auth.

| Endpoint | Parameters | Purpose |
|----------|-----------|---------|
| `coins/list/v1` | `sort=galaxy_score`, `limit=50` | Batch social metrics for top coins |

Single API call per invocation. No per-coin fallback (rate limit budget: ~10 req/min).

**Auth:** `Authorization: Bearer $LUNARCRUSH_API_KEY`
- Key from env var `LUNARCRUSH_API_KEY`
- No key → neutral signal, confidence=0, stderr warning with setup instructions
- 401/403 → explicit auth error message, no retry
- 429 → respect Retry-After header, fallback to cache
- Never log/expose the API key in stderr or output

**Key API fields per coin:**
`galaxy_score`, `galaxy_score_previous`, `alt_rank`, `alt_rank_previous`,
`sentiment`, `social_dominance`, `interactions_24h`, `mentions_24h`,
`creators_24h`, `creators_change_24h`, `price`, `price_change_24h`,
`market_cap`, `volume_24h`

## Signal Logic (3-metric weighted)

Per-coin social score:

```
galaxy_norm  = clamp(galaxy_score, 0, 100) / 100
sentiment_norm = clamp(sentiment, 0, 100) / 100
altrank_delta = (alt_rank_previous - alt_rank) / max(alt_rank_previous, 10)
altrank_norm  = clamp((altrank_delta + 1) / 2, 0, 1)

social_score = 0.4 * galaxy_norm + 0.4 * sentiment_norm + 0.2 * altrank_norm
```

Aggregate: weighted average by `social_dominance` across all coins.
If `social_dominance` is 0/missing for all, fall back to simple average.

| avg_social | Signal |
|-----------|--------|
| > 0.60 | bullish |
| < 0.40 | bearish |
| else | neutral |

**Input guards:** All numeric fields: treat None/missing as 0. Clamp to valid ranges before normalization. Skip coins where galaxy_score is None (partial API response).

## Confidence Formula (4-factor)

```
signal_edge      = abs(avg_social - 0.5) * 2                              # 0-1
galaxy_strength  = clamp(avg_galaxy_score / 80, 0, 1)                     # 0-1
engagement       = clamp(log1p(total_interactions) / log1p(50_000_000), 0, 1)  # log-scaled
momentum         = clamp(abs(avg_altrank_delta) * 5, 0, 1)               # 0-1

confidence = round(15 + 85 * (0.35*signal_edge + 0.25*galaxy_strength + 0.20*engagement + 0.20*momentum))
```

Clamped to [15, 100]. Zero/missing inputs default to 0 for that component.

## Cache

- Path: `~/.cache/crucible/lunarcrush/coins.json`
- Fresh TTL: 60 seconds (matches LC data refresh)
- Stale window: 30 minutes
- Atomic writes: write to `.tmp` → `os.replace()` to final path
- Cache stores: `{timestamp, data}` JSON envelope

## CLI

```
--limit 50           # max coins to fetch
--sort galaxy_score  # sort by: galaxy_score, alt_rank, sentiment, interactions
--coins BTC,ETH      # filter output by coin symbols
--min-galaxy 0       # filter coins below this galaxy score
```

## Output (SignalOutput v1)

```json
{
  "schema": "signal/v1",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "Galaxy Score avg 72/100, sentiment 68% bullish across 42 coins",
  "data": {
    "count": 42,
    "avg_galaxy_score": 72.3,
    "avg_sentiment": 68.1,
    "avg_alt_rank": 156,
    "total_interactions_24h": 45000000,
    "top_coins": [
      {"symbol": "BTC", "galaxy_score": 78, "sentiment": 72, "alt_rank": 1, "social_dominance": 28.4}
    ],
    "movers": {
      "improving": [{"symbol": "SOL", "alt_rank": 12, "alt_rank_previous": 45, "delta": 33}],
      "declining": [{"symbol": "DOGE", "alt_rank": 89, "alt_rank_previous": 34, "delta": -55}]
    }
  },
  "analytics": {
    "confidence_components": {
      "signal_edge": 0.36,
      "galaxy_strength": 0.90,
      "engagement": 0.75,
      "momentum": 0.45
    }
  }
}
```

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No API key | neutral, confidence=0, stderr: "Set LUNARCRUSH_API_KEY" |
| Auth error (401/403) | neutral, confidence=0, stderr: "Invalid/expired API key" |
| Rate limit (429) | Retry-After → fallback to cache → stale → neutral, confidence=15 |
| Network error | Fallback to cache → stale → neutral, confidence=15 |
| Empty response | neutral, confidence=15 |
| Partial coin data | Skip coins with null galaxy_score, proceed with rest |

## Architecture

Single file `lunarcrush.py` (~300-350 lines), stdlib-only, PEP 723.
Sections: auth check → fetch (batch) → cache → normalize → score → confidence → CLI.
