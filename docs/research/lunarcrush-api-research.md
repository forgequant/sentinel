# LunarCrush API v4 — Research

CONTEXT: The sentinel plugin includes a `lunarcrush` skill that consumes the LunarCrush v4 API for crypto social metrics; this research establishes the full integration contract before implementation.
DATE: 2026-02-27

## Question

What is the complete integration contract for the LunarCrush API v4, covering authentication, key social/scoring endpoints, rate limits, response schema, and pricing tiers?

## Evidence

### 1. Authentication

Authentication uses a Bearer token passed in the HTTP `Authorization` header. There is no documented query-parameter alternative.

```
Authorization: Bearer <API_KEY>
```

Example curl:
```bash
curl -H "Authorization: Bearer <API_KEY>" \
  https://lunarcrush.com/api4/public/coins/list/v1
```

API keys are generated from the LunarCrush developer dashboard at `lunarcrush.com/developers/api/authentication`. No token expiry is documented; keys appear to be long-lived. Keys are tier-bound — a subscription must be active for the key to return full data. Without a subscription the API enters "Limited data mode" and returns partial or no metrics. Sources: [LunarCrush Auth Docs](https://lunarcrush.com/developers/api/authentication), [Build an AI Crypto Research Agent](https://dev.to/dbatson/build-an-ai-crypto-research-agent-with-claude-and-lunarcrush-api-4pb0), [AltRank Monitor article](https://dev.to/dbatson/build-an-altrank-monitor-to-catch-social-momentum-early-51b7).

---

### 2. Base URL and Versioning

```
https://lunarcrush.com/api4/public/
```

All v4 endpoints live under `/api4/public/`. Endpoint paths include explicit version suffixes (`/v1`, `/v2`). The `v2` variants of list endpoints update every few seconds, whereas `v1` is more heavily cached. Source: [LunarCrush API Overview](https://lunarcrush.com/developers/api/overview), [Uniblock API Reference](https://docs.uniblock.dev/docs/tonapi-copy-2).

---

### 3. Key Endpoints

The full v4 API spans six domain groups. The 31 documented endpoints (via the Uniblock proxy mirror, which reflects the complete LunarCrush v4 surface) are listed below.

#### 3a. Coins (most relevant for sentinel)

| Endpoint | Path | Notes |
|----------|------|-------|
| Coins List v1 | `GET /coins/list/v1` | Cached list; sortable |
| Coins List v2 | `GET /coins/list/v2` | Near real-time updates |
| Coin Detail | `GET /coins/{coin}/v1` | Single asset snapshot |
| Coin Time Series v1 | `GET /coins/{coin}/time-series/v1` | Historical time series |
| Coin Time Series v2 | `GET /coins/{coin}/time-series/v2` | Historical, more frequent |
| Coin Meta | `GET /coins/{coin}/meta/v1` | Static metadata |

Query parameters for list endpoints:
- `sort` — field to sort by (e.g., `alt_rank`, `galaxy_score`, `interactions_24h`)
- `limit` — number of results
- `interval` — time bucket for time-series (`1d`, `1w`, `1m`)
- `start` / `end` — Unix timestamps for time-series range
- `bucket` — granularity (`hours` or `days`)

Source: [AltRank Monitor article](https://dev.to/dbatson/build-an-altrank-monitor-to-catch-social-momentum-early-51b7), [Uniblock API Reference](https://docs.uniblock.dev/docs/tonapi-copy-2).

#### 3b. Topics

| Endpoint | Path |
|----------|------|
| Topics List | `GET /topics/list/v1` |
| Topic Detail | `GET /topic/{topic}/v1` |
| Topic Time Series | `GET /topic/{topic}/time-series/v1` |
| Topic Posts | `GET /topic/{topic}/posts/v1` |
| Topic Creators | `GET /topic/{topic}/creators/v1` |
| Topic Whatsup (AI summary) | `GET /topic/{topic}/whatsup/v1` |

Topic names must be lowercase. Source: [LunarCrush API Overview](https://lunarcrush.com/developers/api/overview), [Sentiment Tracker article](https://dev.to/dbatson/build-a-real-time-ai-sentiment-tracker-with-lunarcrush-api-in-20-minutes-16i1).

#### 3c. Categories

`GET /categories/list/v1`, `GET /category/{category}/v1`, `/time-series/v1`, `/topics/v1`, `/posts/v1`, `/creators/v1`.

#### 3d. Creators

`GET /creators/list/v1`, `GET /creator/{network}/{id}/v1`, `/time-series/v1`, `/posts/v1`.

#### 3e. NFTs

`GET /nfts/list/v1`, `/list/v2`, `GET /nfts/{nft}/v1`, `/time-series/v1`, `/time-series/v2`.

#### 3f. Stocks

`GET /stocks/list/v1`, `/list/v2`, `GET /stocks/{stock}/v1`, `/time-series/v1`, `/time-series/v2`.

#### 3g. Searches (custom topic tracking)

`POST /searches/create`, `GET /searches/list`, `GET /searches/search`, `PATCH /searches/update`, `DELETE /searches/delete`.

#### 3h. System

`GET /system/changes/v1` — changelog for recent data schema changes.

Source: [Uniblock API Reference](https://docs.uniblock.dev/docs/tonapi-copy-2), [LunarCrush GitHub](https://github.com/lunarcrush/api).

---

### 4. Galaxy Score and AltRank

**Galaxy Score** (0–100 scale):

A proprietary composite score built from four sub-signals:
1. Price score — relative price appreciation measured via MACD (current vs. previous interval)
2. Social impact score — engagement and reach across social platforms
3. Average sentiment — ML-classified sentiment of social content (bullish vs. bearish)
4. Correlation rank — how closely social volume/sentiment tracks price and trading volume

Scores are aggregated and normalized to 0–100. Scores above 70 are interpreted as high social health. The previous-period value is returned as `galaxy_score_previous` for delta tracking. Sources: [LunarCrush FAQ - Galaxy Score](https://lunarcrush.com/faq/what-is-a-galaxy-score), [AltRank Monitor article](https://dev.to/dbatson/build-an-altrank-monitor-to-catch-social-momentum-early-51b7), [LunarCrush API Overview](https://lunarcrush.com/developers/api/overview).

**AltRank** (lower = better):

A relative ranking of an asset versus all other supported assets. Combines:
- Change in price
- Change in volume
- Change in social volume
- Social score

AltRank 1–50 is considered top tier. Previous value returned as `alt_rank_previous`. Sources: [LunarCrush FAQ - Metrics](https://lunarcrush.com/faq/what-metrics-are-available-on-lunarcrush), [LunarCrush API Overview](https://lunarcrush.com/developers/api/overview).

---

### 5. Response Format

All responses are JSON. The envelope structure contains a `config` metadata block and a `data` array (or object for single-asset endpoints). Example for `GET /api4/public/topic/{topic}/v1`:

```json
{
  "config": { ... },
  "data": {
    "topic": "bitcoin",
    "galaxy_score": 74,
    "galaxy_score_previous": 71,
    "alt_rank": 3,
    "alt_rank_previous": 5,
    "price": 95000.00,
    "price_change_24h": 2.5,
    "market_cap": 1880000000000,
    "volume_24h": 45000000000,
    "sentiment": 68,
    "social_volume": 18400,
    "social_dominance": 28.4,
    "interactions_24h": 3200000,
    "mentions_24h": 18400,
    "creators_24h": 5200,
    "creators_change_24h": 12.3,
    "engagements_24h": 3200000
  }
}
```

**Field glossary:**

| Field | Type | Description |
|-------|------|-------------|
| `galaxy_score` | int 0–100 | Composite social-health score |
| `galaxy_score_previous` | int | Galaxy Score in prior period |
| `alt_rank` | int | Relative rank vs all assets (lower = better) |
| `alt_rank_previous` | int | AltRank in prior period |
| `sentiment` | int 0–100 | Percentage of bullish social content |
| `social_volume` | int | Total social posts/mentions volume |
| `social_dominance` | float | Asset's % share of total crypto social volume |
| `interactions_24h` | int | Total engagement actions in 24h |
| `mentions_24h` | int | Raw mention count in 24h |
| `creators_24h` | int | Unique accounts posting about asset in 24h |
| `creators_change_24h` | float | % change in unique creator count |
| `engagements_24h` | int | Aggregated engagement metric in 24h |
| `price` | float | Current price (USD) |
| `price_change_24h` | float | 24h price % change |
| `market_cap` | float | Total market cap (USD) |
| `volume_24h` | float | 24h trading volume (USD) |

Time-series endpoints return an array of timestamped objects under `data`, each containing: `time` (Unix ts), `galaxy_score`, `alt_rank`, `sentiment`, `engagements`, `creators`, `interactions`, `social_volume`, `price`, `volume`.

The platform tracks 20,000+ assets and 60+ metrics per asset in historical time series. Sources: [Sentiment Tracker article](https://dev.to/dbatson/build-a-real-time-ai-sentiment-tracker-with-lunarcrush-api-in-20-minutes-16i1), [AltRank Monitor article](https://dev.to/dbatson/build-an-altrank-monitor-to-catch-social-momentum-early-51b7), [AI Crypto Research Agent article](https://dev.to/dbatson/build-an-ai-crypto-research-agent-with-claude-and-lunarcrush-api-4pb0).

---

### 6. Rate Limits

Explicit rate limit numbers are not published in the official v4 documentation pages. The evidence gathered is:

- The Individual plan enforces **10 requests per minute** (cited in a search result summary referencing LunarCrush pricing FAQ).
- Builder/Enterprise plans have higher limits but specific numbers are not publicly documented.
- HTTP `429 Too Many Requests` is the rate-limit response code; recommended mitigation is increasing polling intervals or upgrading plan.
- The minimum API credit bundle referenced is 2,000 credits/$1/day with additional credits at $0.0005 each, suggesting a credit-based quota layer exists on top of per-minute limits.
- Tutorial authors recommend caching responses for a minimum of 60 seconds, as that is the data refresh frequency on the platform.

Sources: [LunarCrush Pricing FAQ](https://lunarcrush.com/faq/how-does-api-pricing-work), [AltRank Monitor article](https://dev.to/dbatson/build-an-altrank-monitor-to-catch-social-momentum-early-51b7), search result summaries from [LunarCrush About API](https://lunarcrush.com/about/api).

---

### 7. Pricing Tiers

| Tier | Price | API Access | Notes |
|------|-------|-----------|-------|
| Discover (Free) | $0 | Limited data mode | Basic platform access; API returns partial/no metrics |
| Individual | ~$24/month | Full social + market metrics; 10 req/min | All metrics, AI highlights, trending categories |
| Builder | ~$240/month | Enhanced API; higher rate limits | Developer-focused; app integration tier |
| Enterprise | Custom | Premium API; dedicated support | Custom limits, consulting, brand customization |

A credit system also exists alongside the subscription tiers (2,000 credits minimum, $0.0005/additional credit), likely used for metered endpoints or burst capacity.

Sources: [LunarCrush Pricing](https://lunarcrush.com/pricing), [AIChief LunarCrush Review 2026](https://aichief.com/ai-data-management/lunarcrush-review-2025/), [LunarCrush About API](https://lunarcrush.com/about/api).

---

### 8. Official SDK

An official JavaScript/TypeScript SDK exists:

```bash
npm install @jamaalbuilds/lunarcrush-api
```

Usage pattern:
```typescript
import { LunarCrush } from '@jamaalbuilds/lunarcrush-api';

const lc = new LunarCrush(process.env.LUNARCRUSH_API_KEY);
const data = await lc.coins.get('bitcoin');
const trending = await lc.coins.list({ sort: 'alt_rank', limit: 100 });
```

Source: [Unlocking Crypto Market Insights article](https://dev.to/dbatson/unlocking-crypto-market-insights-a-practical-guide-to-building-real-time-trading-signals-with-the-1bm1).

---

## Analysis

**Integration fit for sentinel's lunarcrush skill:**

The API is well-suited to the sentinel use case. The `GET /coins/{coin}/v1` endpoint is the primary target — it delivers Galaxy Score, AltRank, sentiment percentage, social volume, and 24h engagement in a single call with no additional parameters. For time-series context, `GET /coins/{coin}/time-series/v2` with `interval=1d` provides the historical social trajectory.

**Key design constraints:**

1. The API is **not free** for meaningful use. The free Discover tier returns "limited data mode" which in practice means most metric fields are absent or zeroed. Sentinel's CLAUDE.md correctly flags this skill as "Premium". The minimum viable tier is Individual (~$24/month).

2. **Rate limits are low on Individual**: 10 req/min means the skill must not poll aggressively. At a 60-second minimum cache TTL (matching LunarCrush's own data refresh rate), a single-coin query per minute fits cleanly. Multi-coin scans (e.g., top 20 by AltRank) should use `coins/list/v1` in a single call rather than N individual calls.

3. **Authentication is simple and header-only**: `Authorization: Bearer <key>`. No HMAC signing, no OAuth, no query-param fallback. The env var should be `LUNARCRUSH_API_KEY` (already referenced in sentinel's CLAUDE.md).

4. **Response schema is stable and rich**: Galaxy Score, AltRank, sentiment, social volume, interactions, creators, and dominance are all first-class fields in the current v4 API. The `_previous` suffix variants enable delta/momentum signals without a second call.

5. **Coin lookup**: Coins are referenced by symbol (e.g., `bitcoin`, `ethereum`). The `coins/list/v1` endpoint doubles as a discovery/lookup endpoint. The `coins/{coin}/meta/v1` endpoint provides static metadata (name, symbol, links).

6. **Topic-based queries** (e.g., `topic/bitcoin/v1`) appear to return the same social metrics as coin-based queries and may offer broader coverage of informal mentions. Worth testing both paths.

**Gaps in evidence:**

- Exact credit-to-request mapping is undocumented publicly.
- Builder plan rate limit is undocumented (known only to be "higher than Individual").
- Whether the `v2` coin list endpoint requires a Builder plan or is available on Individual is not confirmed.
- No official Python SDK exists; raw `httpx`/`requests` calls with the Bearer header are the idiomatic Python path.

---

## Recommendation

**Implement the lunarcrush skill as follows:**

1. **Auth**: Read `LUNARCRUSH_API_KEY` from env. If absent, emit a `neutral` signal with `confidence=0` and a human-readable warning on stderr (graceful degradation consistent with sentinel conventions).

2. **Primary endpoint**: `GET https://lunarcrush.com/api4/public/coins/{symbol}/v1` for per-coin snapshot. Use `GET /coins/list/v1?sort=alt_rank&limit=50` for market-wide social momentum scans.

3. **Time series**: `GET /coins/{symbol}/time-series/v2?interval=1d` for 7–30 day lookback to provide trend context (rising vs. falling social momentum).

4. **Signal logic**: Map Galaxy Score and sentiment to the bullish/bearish/neutral signal. Suggested thresholds (to be calibrated): Galaxy Score > 65 + sentiment > 60 = bullish; Galaxy Score < 40 or sentiment < 40 = bearish; otherwise neutral. AltRank delta (`alt_rank` vs `alt_rank_previous`) provides a momentum confirmation.

5. **Caching**: Cache responses for 60 seconds minimum to respect rate limits and avoid redundant calls. The Individual plan's 10 req/min budget is adequate for single-asset polling but requires batching for multi-asset use.

6. **Plan requirement**: Document clearly in skill README and `.claude-plugin/plugin.json` that this skill requires a LunarCrush Individual plan or higher (~$24/month). The `LUNARCRUSH_API_KEY` env var must be declared as required.

**Confidence: MEDIUM-HIGH** — Authentication, endpoint paths, response fields, and signal logic are well-evidenced across multiple independent sources. Rate limit specifics for paid tiers and credit system mechanics remain partially undocumented in public sources; exact thresholds should be validated against actual API responses during implementation.
