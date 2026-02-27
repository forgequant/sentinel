---
name: polymarket
description: >
  Use when the user asks about prediction markets, crypto event probabilities,
  market expectations, or what the crowd is betting on. Fetches crypto-related
  prediction market odds from Polymarket.
version: 0.1.0
---

# Polymarket Prediction Markets

Prediction market odds for crypto events — crowd-sourced probabilities.

## API
- Source: Polymarket Gamma API (`gamma-api.polymarket.com`)
- Auth: None (free, public)
- Rate limit: Not documented
- Note: Gamma API is unofficial and may change without notice

## Usage
```bash
uv run skills/polymarket/scripts/polymarket.py [options]
```

### Options
| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | `10` | Number of markets to return |
| `--min-volume` | `1000` | Minimum volume USD to filter noise |
| `--min-liquidity` | `500` | Minimum liquidity USD |

## Output (SignalOutput v1)
```json
{
  "schema": "signal/v1",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "Crowd expects 72% BTC above 100k by Q2, bullish consensus",
  "data": {
    "crypto_markets": [
      {
        "question": "Will BTC exceed $100k by June 2026?",
        "probability": 0.72,
        "volume_usd": 45000,
        "liquidity_usd": 12000,
        "end_date": "2026-06-30",
        "orientation": "bullish",
        "url": "https://polymarket.com/event/..."
      }
    ],
    "avg_bullish_probability": 0.65,
    "market_count": 8
  }
}
```

## Notes
- Filters only crypto-related markets using keyword matching
- Classifies market orientation (bullish/bearish) by question text
- Gamma API is unofficial — include API fragility warning in output
