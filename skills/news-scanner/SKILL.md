---
name: news-scanner
description: >
  Use when the user asks about crypto news, recent headlines, breaking events,
  market-moving announcements, or wants sentiment from news sources.
  Aggregates crypto news from configurable sources with keyword alerts
  and sentiment scoring.
version: 0.1.0
---

# News Scanner

Crypto news aggregation with sentiment scoring and keyword alerts.

## API
- Primary: CryptoPanic API (`cryptopanic.com/api/`)
  - Without key: trending posts only
  - With `CRYPTOPANIC_API_KEY`: full access + filters
- Secondary: Configurable RSS feeds (CoinDesk, CoinTelegraph by default)

## Usage
```bash
uv run skills/news-scanner/scripts/news_scanner.py [options]
```

### Options
| Flag | Default | Description |
|------|---------|-------------|
| `--window` | `24h` | Time window for news (e.g., `6h`, `24h`, `7d`) |
| `--coins` | (all) | Filter by coin symbols (e.g., `BTC,ETH,SOL`) |
| `--keywords` | (config) | Alert keywords to highlight |
| `--sources` | (config) | Override news sources |

## Output (SignalOutput v1)
```json
{
  "schema": "signal/v1",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "5 bullish headlines in 6h, BTC ETF approval trending",
  "data": {
    "count": 12,
    "articles": [...],
    "trending_coins": ["BTC", "ETH"],
    "alert_keywords": ["ETF", "SEC"],
    "sentiment": { "positive": 5, "negative": 2, "neutral": 5 }
  }
}
```

## Configuration
Sources and keywords are configurable. Detailed design TBD —
will be defined in a separate brainstorm session.

## Notes
- RSS feeds may change format without notice
- CryptoPanic trending endpoint works without API key
- Deduplication across sources by title similarity
