# Sentinel

Core sentiment stack for crypto trading. Part of the [Crucible](https://github.com/forgequant) plugin collection.

## Skills

| Skill | Description | API Cost |
|-------|-------------|----------|
| **feargreed** | Crypto Fear & Greed Index with configurable thresholds, z-score analytics, multi-TF trends | Free |
| **news-scanner** | Crypto news aggregation with sentiment scoring and keyword alerts | Free (optional key) |
| **lunarcrush** | Social intelligence — galaxy score, alt rank, social dominance | Premium (key required) |
| **polymarket** | Prediction market odds for crypto events | Free |

## Quick Start

```bash
# Install as Claude Code plugin
claude plugin add forgequant/sentinel

# Use in conversation
> "What's the current fear and greed index?"
> "Any crypto news in the last 6 hours?"
> "What are prediction markets saying about BTC?"
```

## Free vs Premium

Sentinel works without any API keys. Three skills (feargreed, news-scanner, polymarket) provide a complete free sentiment stack.

For deeper social intelligence, add a [LunarCrush](https://lunarcrush.com/pricing) subscription and set `LUNARCRUSH_API_KEY`.

For extended news access, set `CRYPTOPANIC_API_KEY` (optional).

## Signal Protocol

All skills output SignalOutput v1:

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

## License

MIT
