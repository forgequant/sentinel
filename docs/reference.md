# Sentinel — Reference

## Skill: feargreed

### Auto-trigger Phrases

- Fear and greed index, Fear & Greed
- Crypto sentiment
- Market sentiment, sentiment index
- Extreme fear, extreme greed

### CLI Usage

```bash
# Default (contrarian mode, standard thresholds)
uv run skills/feargreed/scripts/feargreed.py

# Momentum mode
uv run skills/feargreed/scripts/feargreed.py --mode momentum

# Custom thresholds
uv run skills/feargreed/scripts/feargreed.py --oversold 20 --overbought 80

# Extended history
uv run skills/feargreed/scripts/feargreed.py --history-days 90
```

### Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--mode` | `contrarian`, `momentum` | `contrarian` | Signal interpretation mode |
| `--oversold` | int | `25` | Lower threshold for extreme fear |
| `--overbought` | int | `75` | Upper threshold for extreme greed |
| `--history-days` | int | `90` | Days of history to fetch for analytics |

### Output Example

```json
{
  "schema": "signal/v1",
  "signal": "bullish",
  "confidence": 71,
  "reasoning": "Extreme fear (18) — contrarian bullish. Z-score: -2.1 (unusually low). 8th percentile over 90d. Regime: 5 days in extreme fear.",
  "data": {
    "value": 18,
    "classification": "Extreme Fear",
    "previous_day": 22,
    "previous_week": 31
  },
  "analytics": {
    "zscore_30d": -2.1,
    "percentile_90d": 8,
    "regime_days": 5,
    "delta_1d": -4,
    "delta_7d": -13,
    "delta_30d": -19
  }
}
```

---

## Skill: news-scanner

### Auto-trigger Phrases

- Crypto news, latest news
- What happened in crypto today
- BTC news, ETH news, any coin mentioned by name
- News headlines, market news

### CLI Usage

```bash
# Last 24 hours, all coins
uv run skills/news-scanner/scripts/news_scanner.py

# Last 6 hours, specific coins
uv run skills/news-scanner/scripts/news_scanner.py --window 6h --coins BTC,ETH,SOL

# With keyword filter
uv run skills/news-scanner/scripts/news_scanner.py --keywords "regulation,SEC,ETF"

# Specific sources only
uv run skills/news-scanner/scripts/news_scanner.py --sources cryptopanic,coindesk

# Extended window
uv run skills/news-scanner/scripts/news_scanner.py --window 7d
```

### Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--window` | `6h`, `24h`, `7d` | `24h` | Time window for articles |
| `--coins` | comma-separated | all | Filter by coin ticker |
| `--keywords` | comma-separated | none | Additional keyword filters |
| `--sources` | comma-separated | all | Restrict to specific sources |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CRYPTOPANIC_API_KEY` | Optional | Enables authenticated CryptoPanic access (more results, faster rate limits) |

### Output Example

```json
{
  "schema": "signal/v1",
  "signal": "bearish",
  "confidence": 48,
  "reasoning": "14 articles in 24h window. 8 bearish-leaning (SEC enforcement, liquidations), 4 bullish (partnership, ETF inflow), 2 neutral. Net: bearish.",
  "data": {
    "total_articles": 14,
    "bullish_count": 4,
    "bearish_count": 8,
    "neutral_count": 2,
    "sources": ["cryptopanic", "coindesk", "cointelegraph"],
    "window": "24h"
  },
  "analytics": {
    "sentiment_ratio": 0.33,
    "top_keywords": ["SEC", "liquidation", "ETF", "partnership"]
  }
}
```

---

## Skill: polymarket

### Auto-trigger Phrases

- Prediction markets
- Polymarket
- What are markets pricing, market odds
- Event probabilities

### CLI Usage

```bash
# Default (top 10 markets by volume)
uv run skills/polymarket/scripts/polymarket.py

# More markets, higher volume threshold
uv run skills/polymarket/scripts/polymarket.py --limit 25 --min-volume 10000

# Higher liquidity filter
uv run skills/polymarket/scripts/polymarket.py --min-liquidity 5000
```

### Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--limit` | int | `10` | Number of markets to fetch |
| `--min-volume` | int | `1000` | Minimum market volume (USD) |
| `--min-liquidity` | int | `500` | Minimum market liquidity (USD) |

### Output Example

```json
{
  "schema": "signal/v1",
  "signal": "bullish",
  "confidence": 55,
  "reasoning": "6 of 10 markets show bullish orientation by volume-weighted probability. Dominant market: 'Will BTC reach $120k in 2026?' at 64% yes, $2.1M volume.",
  "data": {
    "total_markets": 10,
    "bullish_markets": 6,
    "bearish_markets": 3,
    "neutral_markets": 1
  },
  "analytics": {
    "top_market": "Will BTC reach $120k in 2026?",
    "top_market_yes_probability": 0.64,
    "top_market_volume": 2100000,
    "volume_weighted_bullish_probability": 0.58
  }
}
```

---

## Skill: lunarcrush

### Auto-trigger Phrases

- Social metrics, social intelligence
- Galaxy score, alt rank
- LunarCrush
- Social dominance

### CLI Usage

```bash
# List top coins by galaxy score
uv run skills/lunarcrush/scripts/lunarcrush.py coins --sort galaxy_score --limit 10

# Single coin detail
uv run skills/lunarcrush/scripts/lunarcrush.py coin BTC

# Trending topics
uv run skills/lunarcrush/scripts/lunarcrush.py trending

# Search
uv run skills/lunarcrush/scripts/lunarcrush.py search "ethereum layer 2"

# Sort options
uv run skills/lunarcrush/scripts/lunarcrush.py coins --sort alt_rank --limit 20
```

### Commands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `coins` | `--sort`, `--limit` | List coins with social metrics |
| `coin` | `<symbol>` | Detail for a single coin |
| `trending` | `--limit` | Currently trending topics |
| `search` | `<query>` | Search for a topic |

### Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--limit` | int | `10` | Number of results |
| `--sort` | `galaxy_score`, `alt_rank`, `sentiment`, `interactions` | `galaxy_score` | Sort metric |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LUNARCRUSH_API_KEY` | Required | LunarCrush v4 API key (paid subscription) |

### Output Example

```json
{
  "schema": "signal/v1",
  "signal": "bullish",
  "confidence": 63,
  "reasoning": "BTC Galaxy Score: 72/100 (strong). Sentiment: 74%. Social dominance: 38.2%. AltRank: #4.",
  "data": {
    "symbol": "BTC",
    "galaxy_score": 72,
    "alt_rank": 4,
    "sentiment": 74,
    "social_dominance": 38.2,
    "interactions_24h": 4820000,
    "posts_24h": 18400,
    "contributors_24h": 9100
  }
}
```

---

## Troubleshooting

### feargreed: "API unavailable"

api.alternative.me is occasionally slow. The 36-hour cache window means a recent snapshot is usually available. If the cache is also stale, the skill will report degraded data quality in confidence scoring.

### news-scanner: very few articles returned

With no `CRYPTOPANIC_API_KEY`, the free CryptoPanic tier has rate limits and returns fewer results. RSS feeds (CoinDesk, CoinTelegraph) are the fallback. Use `--window 7d` to widen the search window if the 24h window returns few articles.

### polymarket: "no markets found"

The Polymarket Gamma API is unofficial and may change. If `--min-volume` or `--min-liquidity` filters are too strict, no markets pass the filter. Try lower thresholds. If no markets are returned even with `--min-volume 0`, the API endpoint may be temporarily unreachable.

### lunarcrush: "authentication error"

The `LUNARCRUSH_API_KEY` environment variable is not set or the key is invalid. Verify the key is exported in your shell: `echo $LUNARCRUSH_API_KEY`. LunarCrush v4 requires a paid subscription — free tier API keys do not work with the v4 endpoints used by this skill.

### `uv` not found

Install `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`. All sentinel scripts require `uv run` for inline dependency resolution.

### Low confidence across all skills

This is expected during calm or directionless markets where indicators give mixed signals. Low confidence is meaningful information — it indicates the sentiment picture is ambiguous, not that the plugin is malfunctioning.

## Composing with Oracle

Sentinel and Oracle share the `signal/v1` protocol. In a Claude conversation, you can pull signals from both plugins and ask Claude to synthesize them:

```
Oracle: BTC options — bearish (confidence 58). RR25 negative, PCR elevated.
Sentinel/feargreed: Extreme fear (value 19) — contrarian bullish (confidence 71).
Sentinel/news-scanner: Bearish news flow (confidence 48).
Sentinel/polymarket: Bullish event probabilities (confidence 55).

Three of four signals are mixed. Ask Claude: "What's the aggregate read?"
```

No programmatic aggregation is needed. Claude synthesizes the signals in context and can weight them by confidence or by your preferred framework.
