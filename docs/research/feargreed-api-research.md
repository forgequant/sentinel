# Fear & Greed Index API — Research

CONTEXT: Sentinel is a public Claude Code trading plugin with a `feargreed` skill; this research validates the alternative.me API as the data source and documents all integration constraints for plugin authors and end users.
DATE: 2026-02-27

## Question

What are the complete technical characteristics of the alternative.me Crypto Fear & Greed Index API — including endpoint parameters, response schema, rate limits, update cadence, historical depth, reliability, known gotchas, methodology, and available alternatives — sufficient to make a production integration decision for the sentinel `feargreed` skill?

## Evidence

### 1. Endpoint and Parameters

Base URL: `https://api.alternative.me/fng/`

Confirmed parameters (via official documentation and empirical testing):

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 1 | Number of entries to return. `0` returns all available data (2,945 entries as of 2026-02-27). |
| `format` | string | `json` | Output format. `json` or `csv`. |
| `date_format` | string | (none) | When set, replaces unix timestamps with human-readable dates. Values: `us` (MM/DD/YYYY), `world` (DD/MM/YYYY), `cn` or `kr` (YYYY/MM/DD). |

Source: [alternative.me Crypto API docs](https://alternative.me/crypto/api/); confirmed by live API calls.

### 2. Response Format (JSON, default)

Full empirically-verified schema from `https://api.alternative.me/fng/?limit=3`:

```json
{
  "name": "Fear and Greed Index",
  "data": [
    {
      "value": "13",
      "value_classification": "Extreme Fear",
      "timestamp": "1772150400",
      "time_until_update": "60068"
    },
    {
      "value": "11",
      "value_classification": "Extreme Fear",
      "timestamp": "1772064000"
    },
    {
      "value": "11",
      "value_classification": "Extreme Fear",
      "timestamp": "1771977600"
    }
  ],
  "metadata": {
    "error": null
  }
}
```

Field details:

| Field | Type | Notes |
|-------|------|-------|
| `value` | string (numeric) | 0-100 integer as string. Must be cast to int. |
| `value_classification` | string | One of: `Extreme Fear`, `Fear`, `Neutral`, `Greed`, `Extreme Greed`. |
| `timestamp` | string (unix epoch) | Midnight UTC (00:00:00) of the data day, as string. |
| `time_until_update` | string (seconds) | Only present on the first (latest) entry. Seconds until the next daily update. |
| `metadata.error` | null or string | `null` on success. |

Source: Live API call executed 2026-02-27 07:19 UTC.

**Gotcha — `value` is a string, not a number.** All numeric fields come back as JSON strings. Consumers must cast: `int(entry["value"])`.

**Gotcha — `time_until_update` is only on the latest entry.** It is absent from all historical entries. Do not assume it is always present.

**Gotcha — `time_until_update` returns negative values when `date_format` is set.** Empirically confirmed: when using `?date_format=us`, `time_until_update` becomes a large negative integer (e.g., `-1772090347`). This is a server-side bug. Use the default unix timestamp mode to get a valid `time_until_update`.

**CSV format is malformed.** The `format=csv` response wraps CSV content inside a JSON shell, producing unparseable output:

```
{
  "name": "Fear and Greed Index",
  "data": [
fng_value,fng_classification,date
27-02-2026,13,Extreme Fear
  ],
  ...
}
```

This is an upstream bug. Do not use `format=csv` in production code.

Source: Live empirical testing, 2026-02-27.

### 3. Rate Limits

Documented: 60 requests per minute, enforced over a 10-minute window. Higher limits available by contacting `support@alternative.me`.

Source: [alternative.me API docs](https://alternative.me/crypto/api/).

Empirical headers: No `X-RateLimit-*` headers are returned. The response headers are:

```
content-type: application/json
access-control-allow-origin: *
```

There is no server-side rate limit signaling in responses. Clients must self-throttle.

Empirical response times: 5 sequential rapid calls averaged **0.439 seconds** per response, with no throttling observed. The server is nginx/1.14.2, hosted on IP `54.39.131.114` (OVH/Canada).

Source: Live empirical testing, 2026-02-27.

**Implication for the sentinel plugin:** Since the index updates once per day and a single call fetches all needed data, the rate limit is not a concern in practice. A plugin that caches the response for 1 hour uses at most 24 calls/day, far below any limit.

### 4. Data Update Frequency

The index updates **once per day at midnight UTC (00:00:00)**.

Evidence: All entry timestamps are exactly `00:00:00 UTC`. On 2026-02-27 at 07:19 UTC, `time_until_update` was `60,006` seconds, placing the next update at 2026-02-27 16:39 UTC — which is exactly midnight UTC on 2026-02-28 (86,400 - 7.19*3600 ≈ 60,000 seconds remaining). Confirmed by computing `timestamp + time_until_update = next midnight`.

Source: [alternative.me Fear & Greed Index page](https://alternative.me/crypto/fear-and-greed-index/); live API empirical analysis, 2026-02-27.

**Implication:** Do not poll more frequently than once per hour. The value will not change between midnight UTC updates. A stale-data warning should trigger if the latest entry's timestamp is more than 25 hours old.

### 5. Historical Data Availability

Using `limit=0`, the API returns all available data. As of 2026-02-27:

- **Total entries: 2,945**
- **Oldest entry: 2018-02-01** (value: 30, "Fear")
- **Newest entry: 2026-02-27** (value: 13, "Extreme Fear")
- **Coverage: ~8 years, continuous daily data**

The index was created in February 2018, coinciding with the end of the 2017 bull market. No data exists before 2018-02-01.

Source: Live API call `https://api.alternative.me/fng/?limit=0`, 2026-02-27.

**Implication:** The full dataset fits in a single API call (~2,945 entries, negligible payload). No pagination is needed for bulk historical downloads.

### 6. Reliability — Known Issues and Gotchas

**No official SLA or status page found.** The alternative.me website does not publish uptime metrics or a status page.

**Server infrastructure:** Single-origin nginx server at `54.39.131.114` (OVH datacenter, Canada). No CDN detected in response headers. This is not a highly-available architecture.

**TLS certificate:** Let's Encrypt cert, valid Jan 16 – Apr 16, 2026. Standard rotation, no concern.

**CORS:** `Access-Control-Allow-Origin: *` is set, enabling direct browser requests. This is relevant for browser-based plugins.

**No authentication required.** The API is completely open — no API key, no account, no header required. This makes it ideal for a public plugin where end users should not need to configure credentials.

**Known bugs (empirically confirmed):**
1. `time_until_update` is negative when `date_format` parameter is used (server-side arithmetic error on the timestamp type)
2. `format=csv` returns malformed output (CSV inside JSON wrapper)
3. All numeric values are JSON strings, not numbers

**Community reliability perception:** No prominent outage reports found in search results across developer communities (GitHub issues, Reddit). The API has been stable enough that multiple production libraries (PyPI `fear-and-greed-crypto`) depend on it without documented reliability concerns.

Source: Live API testing, 2026-02-27; [GitHub search results](https://github.com/rhettre/fear-and-greed-crypto); web search across developer communities.

### 7. Alternative APIs for Fear & Greed Data

| Provider | Endpoint | Auth | Cost | Data | Notes |
|----------|----------|------|------|------|-------|
| **alternative.me** | `https://api.alternative.me/fng/` | None | Free | 2018-present, daily | Primary source; only provider with free open historical access |
| **CoinMarketCap** | `https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical` | API key required | Paid tiers ($0 basic, but F&G endpoint likely premium) | Daily | Proprietary methodology; "most cited" per CMC marketing; requires account |
| **CFGI.io** | API available (registration required) | Account required | Freemium | 2021-present | Multi-timeframe (15M, 1H, 4H, 1D), 50+ tokens, AI-powered components; better granularity for intraday use |
| **Glassnode** | `https://studio.glassnode.com/` | API key required | $999/mo professional | Deep historical | On-chain focus; Fear & Greed as one of many metrics; not a standalone F&G feed |
| **CoinGecko** | Part of market data | API key required | $129+/mo | Varies | Aggregator with sentiment indicators; not a dedicated F&G endpoint |
| **Cloudsway** | `https://www.cloudsway.ai/tools/en/fear-and-greed-index` | Unknown | Unknown | Unknown | Aggregator; limited documentation |
| **RapidAPI (crypto-fear-greed-index2)** | Available via RapidAPI marketplace | RapidAPI key | Paid | Unknown | Third-party wrapper; not primary source |

Source: [Glassnode](https://studio.glassnode.com/charts/indicators.FearGreed?a=BTC); [CoinMarketCap](https://coinmarketcap.com/charts/fear-and-greed-index/); [CFGI.io](https://cfgi.io/); [CoinGecko](https://www.coingecko.com/learn/crypto-fear-and-greed-index); web search 2026-02-27.

**For a public plugin where users must not be required to configure API keys, alternative.me is the only viable option.** All other providers require authentication.

### 8. Methodology

The index scores 0-100, where 0 = Extreme Fear, 100 = Extreme Greed. Five components contribute, with fixed percentage weights:

| Component | Weight | Methodology |
|-----------|--------|-------------|
| **Volatility** | 25% | Current BTC volatility and max drawdown vs. 30-day and 90-day averages. Rising unusual volatility signals fear. |
| **Market Momentum / Volume** | 25% | Current volume and momentum vs. historical averages. Strong buying volume in a positive market signals greed. |
| **Social Media** | 15% | Twitter/X hashtag analysis — post count and interaction rate for Bitcoin. High interaction rates signal public greed. |
| **Surveys** | 15% | Weekly polls via Strawpoll.com (currently paused). Typically 2,000-3,000 votes per poll. Weight effectively 0 while paused. |
| **Bitcoin Dominance** | 10% | Rising BTC market cap share signals fear-driven rotation out of altcoins into BTC as "safe haven." Falling dominance signals altcoin speculation (greed). |
| **Google Trends** | 10% | Search volume for BTC-related terms and related query patterns (e.g., spikes in "bitcoin price manipulation" suggest fear). |

Reddit sentiment analysis is described as experimental and is explicitly excluded from live calculations per the methodology page.

Classification bands:
- 0-24: Extreme Fear
- 25-49: Fear
- 50-74: Neutral (and Greed in some splits)
- 75-100: Extreme Greed

Source: [alternative.me Fear & Greed Index methodology page](https://alternative.me/crypto/fear-and-greed-index/).

**Methodological caveats for trading plugin authors:**
- The survey component is currently inactive, reducing the effective component count to four
- Social media data is Twitter/X-only; Reddit and other platforms are excluded
- The index is Bitcoin-centric — dominance and momentum are BTC-specific; altcoin-specific sentiment is not captured
- Google Trends introduces a 1-2 day lag in some data pipelines
- The index is backward-looking by construction (daily snapshot); no intraday granularity

## Analysis

The alternative.me API is uniquely positioned for public Claude Code plugins: it is the only Fear & Greed provider that requires no authentication, no account, and no payment. This is non-negotiable for a public community plugin targeting skill7.dev users.

**Strengths:**
- Zero-friction integration: no API key, no registration, CORS enabled for browser use
- 8 years of daily history accessible in a single call
- Simple, stable schema with well-defined value classifications
- Consistent daily update cadence (midnight UTC)
- Response times under 500ms, rate limit far exceeds typical plugin usage patterns

**Weaknesses:**
- No SLA or status page — single-origin infrastructure with no redundancy
- Several persistent bugs (CSV format, `time_until_update` with `date_format`, string-typed numbers)
- Survey component currently disabled (reduces methodology coverage)
- Bitcoin-centric only — no per-altcoin sentiment
- Daily granularity only — not suitable for intraday strategies
- No official changelog or versioning on the API — breaking changes could occur silently

**The `time_until_update` bug pattern** suggests the API receives minimal maintenance. Code should treat all fields as potentially string-typed and never depend on `time_until_update` being present or positive.

**The CoinMarketCap alternative** is functionally superior in methodology documentation and institutional credibility, but requires API key configuration which violates the sentinel plugin's "free path must work standalone" invariant from CLAUDE.md.

**CFGI.io** is interesting for future enhancement (multi-timeframe, intraday granularity), but requires account registration and has limited public documentation — not appropriate for the free path.

## Recommendation

**Use alternative.me as the primary and sole data source for the sentinel `feargreed` skill. Confidence: HIGH.**

The API is well-suited to the plugin's requirements. Implement with the following defensive practices:

1. **Cast all values to int explicitly:** `int(entry["value"])` — never assume numeric JSON type.
2. **Never use `date_format` parameter:** Use default unix timestamps to avoid the `time_until_update` bug. Convert timestamps in client code.
3. **Never use `format=csv`:** Malformed output. JSON only.
4. **Check `time_until_update` presence before access:** It is absent on all non-latest entries. Use `.get("time_until_update")` with a fallback.
5. **Cache responses for at least 1 hour:** The value changes only once per day at midnight UTC. Aggressive polling wastes requests and adds latency with no benefit.
6. **Stale data warning threshold:** If latest entry timestamp is more than 25 hours old, emit a warning to stderr. This catches API-side delivery failures.
7. **Fallback on error:** Return `signal=neutral, confidence=0` with a clear error message when the API is unreachable. Do not crash.
8. **Fetch with `limit=0` only when historical analytics are needed** (e.g., z-score, percentile calculation). For current-value-only use cases, `limit=1` is sufficient and faster.

For future oracle or furnace plugins requiring intraday sentiment or altcoin-specific data, CFGI.io and CoinMarketCap are the candidates to evaluate — but only behind premium paywalls, not on the free path.

Sources:
- [alternative.me Crypto API Documentation](https://alternative.me/crypto/api/)
- [alternative.me Fear & Greed Index Methodology](https://alternative.me/crypto/fear-and-greed-index/)
- [GitHub: rhettre/fear-and-greed-crypto Python wrapper](https://github.com/rhettre/fear-and-greed-crypto)
- [GitHub: kukapay/crypto-feargreed-mcp MCP server](https://github.com/kukapay/crypto-feargreed-mcp)
- [CFGI.io multi-timeframe Fear & Greed](https://cfgi.io/)
- [CoinMarketCap Fear & Greed Index](https://coinmarketcap.com/charts/fear-and-greed-index/)
- [Glassnode Fear & Greed Chart](https://studio.glassnode.com/charts/indicators.FearGreed?a=BTC)
- [CoinGecko: Crypto Fear and Greed Index Explained](https://www.coingecko.com/learn/crypto-fear-and-greed-index)
- Live API empirical testing: `https://api.alternative.me/fng/`, 2026-02-27
