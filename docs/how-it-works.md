# Sentinel — How It Works

## Architecture

Sentinel is a four-skill plugin. Each skill is an independent self-contained script that fetches one data source and emits a `signal/v1` signal. A shared library defines the common output schema.

```
sentinel/
  skills/
    feargreed/
      scripts/feargreed.py
    news-scanner/
      scripts/news_scanner.py
    lunarcrush/
      scripts/lunarcrush.py
    polymarket/
      scripts/polymarket.py
  lib/
    protocols.py            # signal/v1 schema and output helpers
```

All scripts are PEP 723 compliant: dependencies are declared inline in the script header and resolved by `uv run` with no manual installation.

## Data Flow (per skill)

```
External API / RSS
      |
      v
  HTTP fetch
      |
      v
  Parsing + normalization
      |
      v
  Analytics computation
      |
      v
  Signal scoring + confidence
      |
      v
  Cache write (where applicable)
      |
      v
  signal/v1 JSON → stdout
  Human summary   → stderr
```

## Skill: feargreed

### Data Source

api.alternative.me — free, no authentication. Returns the Crypto Fear & Greed Index (0-100) for today and up to 90 days of history.

### Computation

The raw index value is a single number. The feargreed skill enriches it with four analytics layers:

**Z-score (30d):** How many standard deviations the current reading is from the 30-day mean. A high positive z-score means greed is unusually elevated; a strongly negative z-score signals unusual fear.

**Percentile (90d):** Where today's value sits in the 90-day distribution. A reading in the 5th percentile means the index is near its lowest point in three months.

**Trend deltas:** Change from yesterday, 7 days ago, and 30 days ago. Direction and momentum of the index shift.

**Regime duration:** How many consecutive days the index has been in the same regime (fear, greed, extreme fear, extreme greed). Long-duration extreme readings are more statistically significant for contrarian signals.

**Modes:**

- `contrarian`: Extreme fear → bullish signal; extreme greed → bearish signal. Confidence increases the more extreme and sustained the reading.
- `momentum`: Trend in the same direction as the signal. Confidence increases with strong trend continuation.

**Confidence:** 4-component weighted score incorporating z-score extremity, percentile extremity, regime duration, and mode alignment.

**Thresholds:** Configurable via `--oversold` (default 25) and `--overbought` (default 75).

### Cache

Two-layer cache at `~/.cache/crucible/feargreed.json`. The outer layer stores the last API response; the inner layer stores the computed analytics. Stale window: 36 hours.

## Skill: news-scanner

### Data Sources

- **CryptoPanic API** (free tier or authenticated with `CRYPTOPANIC_API_KEY` for extended results)
- **CoinDesk RSS** and **CoinTelegraph RSS** (public feeds, no auth)

### Computation

Articles are fetched from all configured sources and merged into a single list. Deduplication runs by title similarity (fuzzy match) to avoid the same story appearing from multiple feeds.

Each article is scored for sentiment using keyword-based heuristics (positive: rally, surge, adoption, partnership; negative: hack, crash, ban, liquidation; neutral: launch, update, report). The per-article scores are aggregated into an overall signal.

Filters apply before aggregation:
- `--window` restricts to articles published in the last N hours/days
- `--coins` filters to articles mentioning specific assets
- `--keywords` adds custom keyword filters
- `--sources` restricts to specific source names

The overall signal direction is determined by the ratio of bullish-leaning to bearish-leaning articles. Confidence is weighted by article count (more data = more confident) and recency (older articles penalized).

## Skill: polymarket

### Data Source

Polymarket Gamma API (unofficial, free, no authentication). Returns open prediction markets.

### Computation

Markets are filtered by `--min-volume` and `--min-liquidity` to exclude illiquid or low-activity markets.

Each market is classified by orientation based on the question text and current probability:
- A market asking "Will BTC reach $100k by end of quarter?" with 70% yes → bullish signal
- A market asking "Will ETH drop below $1000?" with 60% yes → bearish signal

Classification uses keyword detection in the market title (upside keywords: reach, break above, rally; downside keywords: drop, fall below, crash, liquidation).

The aggregated signal reflects the balance of bullish vs bearish market probabilities weighted by volume.

## Skill: lunarcrush

### Data Source

LunarCrush API v4. Requires a paid `LUNARCRUSH_API_KEY`. Returns social metrics including Galaxy Score, AltRank, sentiment, social dominance, and post/contributor counts.

### Computation

The skill surfaces raw LunarCrush metrics rather than deriving a proprietary model on top. Signal direction is derived from Galaxy Score (above midpoint = bullish) and sentiment score. Confidence reflects data recency and the strength of the Galaxy Score reading.

Supported queries: `coins` list, `coin <symbol>` detail, `trending`, `search <query>`. Results sortable by `galaxy_score`, `alt_rank`, `sentiment`, or `interactions`.

## Shared: protocols.py

`lib/protocols.py` defines the `signal/v1` JSON schema used by all four skills (and by the oracle plugin). Any skill output can be consumed by a downstream aggregator or by Claude directly in a conversation.

## Trust Boundaries

- All network connections are outbound HTTPS to public or API-key-gated endpoints.
- No user data, portfolio information, or private keys are transmitted.
- `LUNARCRUSH_API_KEY` and `CRYPTOPANIC_API_KEY` are read from environment variables, never logged or cached to disk.
- Local writes are limited to cache files under `~/.cache/crucible/`.
- No trades are executed. The plugin has no connection to any exchange account or wallet.

## Limitations

- **Sentiment signals are lagging.** Fear & Greed and news sentiment typically lag price action. They are most useful for context, not as leading indicators.
- **News sentiment scoring is heuristic.** The keyword-based approach does not understand context. Sarcasm, negation, and nuanced framing can produce incorrect per-article scores.
- **Polymarket API is unofficial.** The Gamma API endpoint is not publicly documented by Polymarket and may change without notice.
- **LunarCrush requires a paid subscription.** The free tier does not provide the v4 API access required by the skill.
- **No signal aggregation built-in.** Sentinel does not combine its four skills into a single meta-signal. That synthesis happens in the Claude conversation context.
