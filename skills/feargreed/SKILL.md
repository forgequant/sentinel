---
name: feargreed
description: >
  Use when the user asks about market sentiment, fear and greed index,
  crypto mood, or wants a contrarian/momentum read on market emotion.
  Fetches the Crypto Fear & Greed Index with configurable thresholds,
  z-score analytics, and multi-timeframe trend analysis.
version: 0.1.0
---

# Fear & Greed Index

Crypto Fear & Greed Index — contrarian (or momentum) sentiment signal.

## API
- Source: `api.alternative.me/fng/`
- Auth: None (free, public)
- Rate limit: Not documented; data updates daily

## Usage
```bash
uv run skills/feargreed/scripts/feargreed.py [options]
```

### Options
| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `contrarian` | Signal interpretation: `contrarian` or `momentum` |
| `--oversold` | `25` | F&G value below this = extreme fear |
| `--overbought` | `75` | F&G value above this = extreme greed |
| `--history-days` | `90` | Days of history to fetch for analytics |

### Modes
- **contrarian** (default): Extreme fear = bullish, extreme greed = bearish
- **momentum**: Follows the crowd — fear = bearish, greed = bullish

## Output (SignalOutput v1)
```json
{
  "schema": "signal/v1",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "F&G at 23 (extreme fear) — contrarian bullish",
  "data": {
    "current": { "value": 23, "label": "Extreme Fear" },
    "previous": { "value": 28, "label": "Fear" },
    "trend": "falling"
  },
  "analytics": {
    "zscore_30d": -1.8,
    "percentile_90d": 12,
    "trend_7d": -5,
    "trend_30d": -15,
    "trend_90d": +8,
    "regime_days": 4,
    "consensus": "aligned"
  }
}
```

## Analytics
- **zscore_30d**: Current value vs 30-day rolling mean/stddev
- **percentile_90d**: Where current value sits in 90-day distribution
- **trend_Nd**: Change from N days ago (absolute)
- **regime_days**: Consecutive days in current signal zone
- **consensus**: `aligned` if 2+ timeframes agree, `mixed` otherwise
