# Sentinel

**Core sentiment stack for crypto trading — Fear & Greed, news scanning, social intelligence, prediction markets.**

Version: 0.1.0 | Author: forgequant | License: MIT

---

## Overview

Sentinel is a Claude Code plugin that aggregates crypto market sentiment from four independent data sources into structured `signal/v1` signals. It is designed to give traders a multi-dimensional read on market psychology without requiring any API keys to start.

## Quick Start

Ask Claude about sentiment — skills trigger automatically:

```
What's the current Fear & Greed index?
Any major crypto news in the last 6 hours?
What are prediction markets saying about BTC?
What's the LunarCrush galaxy score for ETH?
```

Or invoke directly:

```
/feargreed --mode contrarian
/news-scanner --window 6h --coins BTC,ETH
/polymarket --min-volume 10000
/lunarcrush coin BTC
```

## Skills

| Skill | Data Source | API Key Required |
|-------|-------------|-----------------|
| `feargreed` | api.alternative.me | None (free) |
| `news-scanner` | CryptoPanic + CoinDesk/CoinTelegraph RSS | None (CRYPTOPANIC_API_KEY optional) |
| `polymarket` | Polymarket Gamma API (unofficial) | None (free) |
| `lunarcrush` | LunarCrush API v4 | LUNARCRUSH_API_KEY (paid) |

## Free vs Premium

Sentinel works out of the box with no configuration. The free tier provides a complete sentiment stack:

| Tier | Skills | Coverage |
|------|--------|---------|
| Free | feargreed + news-scanner + polymarket | Sentiment index, news, prediction markets |
| Premium | + lunarcrush | Social intelligence, galaxy score, alt rank |

Optional environment variables:

```bash
export LUNARCRUSH_API_KEY=your_key    # enables lunarcrush skill
export CRYPTOPANIC_API_KEY=your_key  # enables extended CryptoPanic news
```

## Requirements

- **Runtime:** Python 3.14 via `uv run` (PEP 723 inline dependencies).
- **Network:** Yes — all skills make outbound HTTPS requests to their respective public APIs.
- **API keys:** None required. See Premium section above for optional keys.

## Signal Protocol

All skills emit `signal/v1` JSON to stdout:

```json
{
  "schema": "signal/v1",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "brief explanation",
  "data": { ... },
  "analytics": { ... }
}
```

Human-readable summary goes to stderr.

## Skill Details

### feargreed

Fetches the Crypto Fear & Greed Index from api.alternative.me. Supports `--mode contrarian` (buy fear, sell greed) or `--mode momentum`. Analytics include 30-day z-score, 90-day percentile, trend deltas across timeframes, and regime duration. Two-layer cache at `~/.cache/crucible/feargreed.json`, 36-hour stale window.

### news-scanner

Aggregates crypto news from CryptoPanic (with or without API key) and CoinDesk/CoinTelegraph RSS feeds. Deduplicates articles by title similarity. Scores per-article sentiment. Configurable by time window, coin filter, keywords, and source filter.

### polymarket

Fetches open prediction markets from the Polymarket Gamma API (unofficial, free). Filters by minimum volume and liquidity. Classifies each market's orientation as bullish or bearish based on the question framing and current odds.

### lunarcrush

Queries LunarCrush API v4 for social intelligence metrics. Supports coins list, individual coin lookup, trending, and search. Sortable by galaxy score, alt rank, sentiment, or interactions. Requires `LUNARCRUSH_API_KEY`.

## Testing

```bash
python3 -m pytest tests/ -v
```

---

> This plugin provides data signals for informational purposes only. It does not constitute financial advice. Past performance does not indicate future results. Always do your own research before making trading decisions.
