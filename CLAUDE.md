# Sentinel — Agent Instructions

## What
Core sentiment stack for crypto trading. Part of the crucible plugin collection.

## Skills
| Skill | API | Cost | Status |
|-------|-----|------|--------|
| feargreed | alternative.me | Free | v1 |
| news-scanner | CryptoPanic + RSS | Free/opt key | v1 |
| lunarcrush | LunarCrush v4 | Premium | v1 |
| polymarket | Polymarket Gamma | Free | v1 |

## Signal Protocol
All skills output SignalOutput v1 to stdout:
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

## Skill Scripts
- Location: `skills/<name>/scripts/<name>.py`
- Run via: `uv run skills/<name>/scripts/<name>.py [args]`
- PEP 723 inline dependencies
- Shared code: `lib/protocols.py`

## Conventions
- No API keys in code — env vars only
- Graceful degradation when optional keys are missing
- Free path (feargreed + news-scanner + polymarket) must work standalone
