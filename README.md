# Sentinel

<div align="center">

**Aggregate crypto sentiment from four independent sources**

![Claude Code Plugin](https://img.shields.io/badge/Claude_Code-Plugin-5b21b6?style=flat-square)
![Version](https://img.shields.io/badge/Version-0.1.0-5b21b6?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-5b21b6?style=flat-square)

```bash
claude plugin marketplace add heurema/emporium
claude plugin install sentinel@emporium
```

</div>

## What it does

Crypto trading decisions depend on market psychology, yet sentiment data is scattered across incompatible sources with inconsistent formats. Sentinel aggregates Fear & Greed, news, prediction markets, and social intelligence into a unified `signal/v1` stream that Claude can reason over directly. Unlike single-source sentiment tools, it works out of the box with no API keys and scales to paid data when you need deeper social signals.

## Install

<!-- INSTALL:START — auto-synced from emporium/INSTALL_REFERENCE.md -->
```bash
claude plugin marketplace add heurema/emporium
claude plugin install sentinel@emporium
```
<!-- INSTALL:END -->

<details>
<summary>Manual install from source</summary>

```bash
git clone https://github.com/forgequant/sentinel
cd sentinel
claude plugin install --local .
```

</details>

## Quick start

```
What's the current Fear & Greed index?
Any major crypto news in the last 6 hours?
What are prediction markets saying about BTC?
```

Skills trigger automatically from natural language, or invoke directly:

```
/feargreed --mode contrarian
/news-scanner --window 6h --coins BTC,ETH
/polymarket --min-volume 10000
/lunarcrush coin BTC
```

## Commands

| Command | Data source | API key required |
|---------|-------------|-----------------|
| `/feargreed` | api.alternative.me | None |
| `/news-scanner` | CryptoPanic + CoinDesk/CoinTelegraph RSS | None (CRYPTOPANIC_API_KEY optional) |
| `/polymarket` | Polymarket Gamma API | None |
| `/lunarcrush` | LunarCrush API v4 | LUNARCRUSH_API_KEY (paid) |

## Features

**Signal protocol.** All commands emit `signal/v1` JSON to stdout; human-readable summaries go to stderr.

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

**feargreed.** Fetches the Crypto Fear & Greed Index from api.alternative.me. Supports `--mode contrarian` (buy fear, sell greed) or `--mode momentum`. Analytics include 30-day z-score, 90-day percentile, trend deltas across timeframes, and regime duration. Two-layer cache at `~/.cache/crucible/feargreed.json`, 36-hour stale window.

**news-scanner.** Aggregates crypto news from CryptoPanic and CoinDesk/CoinTelegraph RSS feeds. Deduplicates articles by title similarity, scores per-article sentiment, and supports time window, coin filter, keyword, and source filters.

**polymarket.** Fetches open prediction markets from the Polymarket Gamma API. Filters by minimum volume and liquidity. Classifies each market as bullish or bearish based on question framing and current odds.

**lunarcrush.** Queries LunarCrush API v4 for social intelligence metrics. Supports coins list, individual coin lookup, trending, and search. Sortable by galaxy score, alt rank, sentiment, or interactions. Requires `LUNARCRUSH_API_KEY`.

**Free vs premium.** The free tier covers sentiment index, news, and prediction markets. Adding a LunarCrush key unlocks social intelligence.

| Tier | Commands | Coverage |
|------|----------|---------|
| Free | feargreed + news-scanner + polymarket | Sentiment index, news, prediction markets |
| Premium | + lunarcrush | Social intelligence, galaxy score, alt rank |

## Configuration

Optional environment variables:

```bash
export LUNARCRUSH_API_KEY=your_key    # enables lunarcrush command
export CRYPTOPANIC_API_KEY=your_key  # enables extended CryptoPanic news
```

## Requirements

- **Runtime:** Python 3.14 via `uv run` (PEP 723 inline dependencies)
- **Network:** All commands make outbound HTTPS requests to their respective APIs
- **API keys:** None required for free tier

## Privacy

Sentinel makes network calls to external APIs on every invocation. The table below documents each endpoint.

| Command | Host | What is sent | Notes |
|---------|------|-------------|-------|
| `/feargreed` | api.alternative.me | No user data | Public endpoint, no auth |
| `/news-scanner` | cryptopanic.com | Key if set | CoinDesk, CoinTelegraph RSS |
| `/polymarket` | gamma-api.polymarket.com | No user data | Unofficial public API |
| `/lunarcrush` | lunarcrush.com | LUNARCRUSH_API_KEY | Paid; LunarCrush ToS apply |

No data is stored or forwarded beyond the originating API call. Signal output remains local to your Claude session.

## See also

- [skill7.dev](https://skill7.dev) — plugin directory and documentation
- [emporium](https://github.com/heurema/emporium) — plugin registry and installer
- [oracle](https://github.com/heurema/oracle) — on-chain data plugin for Sentinel signals

## License

[MIT](LICENSE)
