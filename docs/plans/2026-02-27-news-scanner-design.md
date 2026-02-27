# news-scanner v2 Design

**Date:** 2026-02-27
**Status:** Approved (with Codex feedback incorporated)
**Codex Rating:** 6/10 → revised based on feedback

## Sources (RSS-first)

| Source | Articles | TTL | Role |
|--------|----------|-----|------|
| CoinDesk RSS | 25 | 5 min | primary — fresh, good tags |
| CoinTelegraph RSS | 30 | 4h | primary — broad coverage |
| Decrypt.co RSS | 37 | 10s | primary — cleanest text for sentiment |
| CryptoSlate RSS | 10 | 1h | secondary — different editorial angle |
| CryptoPanic API | ? | ? | **bonus** — only with CRYPTOPANIC_API_KEY |

**Key decision:** CryptoPanic returns HTTP 404 without auth_token (confirmed 2026-02-27).
RSS is the primary data source. CryptoPanic adds votes/currencies when key available.

## Sentiment

**Hybrid approach (revised per Codex):**
- CryptoPanic votes: adaptive weight (0.3-0.65 based on vote count and recency)
- Lexical scoring: 15-20 focused words with negation handling
- When no CryptoPanic data: lexical-only with lower confidence base

**Word lists:**
- Positive (~10): rally, surge, bullish, approval, launch, soars, gains, partnership, breakthrough, adoption
- Negative (~10): crash, hack, ban, dump, bearish, plunge, exploit, lawsuit, delisting, fraud
- Negation: not, no, never, fails, unlikely, denies → flip polarity
- Boosters: extreme, massive, major, historic → 1.5x weight

**Confidence formula:**
```
agreement = |bull - bear| / max(1, bull + bear)
recency = mean(decay(article_age_h) for each article)  # exp(-age/12)
coverage = min(1.0, n_articles / 10)
diversity = n_unique_sources / n_total_sources
confidence = round(15 + 85 * (0.35*agreement + 0.25*coverage + 0.25*recency + 0.15*diversity))
```

## Deduplication

3-stage (revised threshold per Codex):
1. **Canonical URL** — strip UTM/tracking params, normalize scheme/host
2. **GUID match** — RSS guid field when available
3. **Fuzzy title** — SequenceMatcher ratio ≥ **0.90** (lowered from 0.93)

## Coin Detection

Top-30 coins with regex word-boundary matching:
- Full name patterns: `\bsolana\b` (case-insensitive)
- Symbol patterns: `(?<![A-Za-z])SOL(?![A-Za-z])` (case-sensitive for short symbols)
- Symbol blacklist for ambiguous: DOT requires "polkadot" context nearby, OP requires "optimism"

## CLI

```
--window 24h       # 6h, 24h, 7d, 30m, 2d
--coins BTC,ETH    # filter by symbols
--keywords etf,sec # custom alert keywords
--sources all      # all | rss | cryptopanic
```

## Cache

- Fresh TTL: 15 minutes
- Stale window: 2 hours (news stales fast)
- Per-source caching in `~/.cache/crucible/news-scanner/`

## Output (SignalOutput v1)

```json
{
  "schema": "signal/v1",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "5 bullish / 2 bearish across 12 articles from 4 sources",
  "data": {
    "count": 12,
    "articles": [...],
    "trending_coins": ["BTC", "ETH"],
    "alert_keywords": ["etf", "sec"],
    "sentiment": {"positive": 5, "negative": 2, "neutral": 5},
    "sources_used": ["CoinDesk", "CoinTelegraph", "Decrypt"],
    "data_fresh": true
  },
  "analytics": {
    "confidence_components": {
      "agreement": 0.72,
      "coverage": 0.85,
      "recency": 0.64,
      "source_diversity": 0.75
    },
    "effective_sample_size": 10,
    "duplicate_rate": 0.15
  }
}
```

## Architecture

Single file `news_scanner.py` (~350-400 lines), stdlib-only, PEP 723.
Sections: fetch (RSS + CryptoPanic) → cache → dedup → coin detect → sentiment → scoring → CLI.
