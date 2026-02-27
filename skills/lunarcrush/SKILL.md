---
name: lunarcrush
description: >
  Use when the user asks about social metrics, galaxy score, alt rank,
  social dominance, trending crypto topics, or social intelligence data.
  Requires LUNARCRUSH_API_KEY (paid subscription).
version: 0.1.0
---

# LunarCrush Social Intelligence

Social metrics for crypto assets — galaxy score, alt rank, sentiment,
social dominance, trending topics.

## API
- Source: LunarCrush API v4 (`lunarcrush.com/api4/public/`)
- Auth: `LUNARCRUSH_API_KEY` (Bearer token, **required**)
- Rate limit: ~10 req/min (Individual Starter plan)
- Subscription: https://lunarcrush.com/pricing

## Usage
```bash
uv run skills/lunarcrush/scripts/lunarcrush.py <endpoint> [options]
```

### Endpoints
| Endpoint | Description |
|----------|-------------|
| `coins` | Top coins by social metrics |
| `coin <symbol>` | Detailed metrics for one coin |
| `trending` | Currently trending topics |
| `search <query>` | Search social data |

### Options
| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | `10` | Number of results |
| `--sort` | `galaxy_score` | Sort by: galaxy_score, alt_rank, sentiment, interactions |

## Output (SignalOutput v1)
```json
{
  "schema": "signal/v1",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "BTC galaxy score 78/100, social dominance rising",
  "data": {
    "symbol": "BTC",
    "galaxy_score": 78,
    "alt_rank": 1,
    "sentiment": 72,
    "social_dominance": 45.2,
    "interactions_24h": 1250000
  }
}
```

## Premium Skill
This skill requires a paid LunarCrush subscription.
Without `LUNARCRUSH_API_KEY`, the skill reports a clear error message
suggesting how to obtain a key. The sentinel plugin works without it —
feargreed, news-scanner, and polymarket provide the free path.
