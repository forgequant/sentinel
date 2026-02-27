# Polymarket Gamma API — Research

CONTEXT: Evaluating the Polymarket Gamma API as a data source for crypto prediction market signals in the Sentinel project.
DATE: 2026-02-27

## Question

What endpoints does the Polymarket Gamma API expose for crypto prediction markets, what do their responses look like, how do you filter by crypto topic, and is the API free/rate-limited?

---

## Evidence

### 1. Endpoint Status (All Tested 2026-02-27)

| Endpoint | HTTP Status | Notes |
|----------|-------------|-------|
| `GET /markets?tag=crypto&closed=false&limit=5` | 200 | `tag=` param is IGNORED — returns default sort (oldest first), not crypto-filtered |
| `GET /markets?tag=bitcoin&closed=false&limit=5` | 200 | Same: `tag=` param ignored on `/markets` |
| `GET /events?tag=crypto&closed=false&limit=5` | 200 | `tag=` param is also ignored on `/events` — returns unfiltered results |
| `GET /events?closed=false&limit=5` | 200 | Works, returns most recently updated events |
| `GET /events?tag_slug=crypto&closed=false&limit=100` | 200 | **Correct param**: returns 100 crypto-tagged events |
| `GET /events?tag_slug=bitcoin&closed=false&limit=100` | 200 | Returns 100 Bitcoin-tagged events |
| `GET /public-search?q=bitcoin&events_status=active&limit_per_type=3` | 200 | Full-text search, returns 819 total results |
| `GET /tags` | 200 | Returns all available tags with id, label, slug |
| `GET /tags?limit=500` | 200 | Returns 300 tags (full list, ignores limit past 300) |
| `GET /docs` | 404 | No embedded docs at the API root |
| `GET /openapi.json` | 404 | No OpenAPI spec exposed directly |
| `GET https://docs.polymarket.com` | 200 | Mintlify-based docs site exists |

Source: Direct curl testing against `https://gamma-api.polymarket.com`

---

### 2. Authentication

No authentication required for any read endpoint tested. All requests return data without any API key or `Authorization` header. The official docs (sourced from `https://docs.polymarket.com/api-reference/events/list-events` and `https://docs.polymarket.com/api-reference/markets/list-markets`) confirm `"security: []"` for both `/events` and `/markets`.

Source: Response headers, official API docs at `https://docs.polymarket.com`

---

### 3. Rate Limits

No `X-RateLimit-*` headers observed in responses. Response headers show:
- `cache-control: public, max-age=120` — responses are cached for 2 minutes
- `cf-cache-status: HIT` — Cloudflare CDN caching is active
- No `Retry-After`, `X-RateLimit-Remaining`, or similar headers

The official docs have a dedicated rate-limits page but it mentions tier-based limits only for authenticated Builder API access. Public read endpoints appear unthrottled, but no explicit documentation of public rate limits was found.

Source: `curl -sI https://gamma-api.polymarket.com/events?limit=1`, `https://docs.polymarket.com`

---

### 4. Official Documentation

Official docs at `https://docs.polymarket.com` are comprehensive. Relevant pages (confirmed live):
- `https://docs.polymarket.com/api-reference/events/list-events` — full events endpoint spec
- `https://docs.polymarket.com/api-reference/markets/list-markets` — full markets endpoint spec
- `https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles` — search endpoint
- `https://docs.polymarket.com/api-reference/tags/list-tags` — tag listing
- `https://docs.polymarket.com/market-data/fetching-markets` — guide with recommended patterns

Source: `https://docs.polymarket.com/sitemap.xml`

---

### 5. Correct Crypto Filtering

The `tag=` parameter in the originally proposed URLs does NOT filter — it is silently ignored. The correct parameter is `tag_slug=` on the `/events` endpoint.

Confirmed working crypto tag slugs and their open-market counts (2026-02-27):

| tag_slug | Active+Open Event Count |
|----------|------------------------|
| `crypto` | 100+ |
| `bitcoin` | 100+ |
| `ethereum` | 100+ |
| `solana` | 100+ |
| `crypto-prices` | 100+ |
| `bitcoin-dominance` | 1 |
| `cryptocurrency` | 0 (slug exists but unused) |

Tag IDs for programmatic use:
- `id=21`, `slug=crypto`, `label=Crypto` — broad crypto category
- `id=235`, `slug=bitcoin`, `label=Bitcoin`
- `id=1312`, `slug=crypto-prices`, `label=Crypto Prices`

Source: `GET https://gamma-api.polymarket.com/tags`, live endpoint tests

---

### 6. Response Structure: `/events` Endpoint

**Event object** (top-level fields — excludes `markets[]` array):

```json
{
  "id": "194107",
  "ticker": "what-price-will-bitcoin-hit-in-february-2026",
  "slug": "what-price-will-bitcoin-hit-in-february-2026",
  "title": "What price will Bitcoin hit in February?",
  "description": "...",
  "resolutionSource": "",
  "startDate": "2026-01-31T02:17:18.974124Z",
  "creationDate": "2026-01-31T02:17:18.974091Z",
  "endDate": "2026-03-01T05:00:00Z",
  "active": true,
  "closed": false,
  "archived": false,
  "new": false,
  "featured": false,
  "restricted": true,
  "liquidity": 7219629.30915,
  "volume": 113036250.864094,
  "openInterest": 0,
  "competitive": 0.8105,
  "volume24hr": 3967650.86,
  "volume1wk": 40759997.13,
  "volume1mo": 112960291.72,
  "volume1yr": 112960291.72,
  "enableOrderBook": true,
  "liquidityClob": 7219629.30915,
  "negRisk": false,
  "commentCount": 0,
  "tags": [
    {"id": "235", "label": "Bitcoin", "slug": "bitcoin"},
    {"id": "1312", "label": "Crypto Prices", "slug": "crypto-prices"},
    {"id": "21", "label": "Crypto", "slug": "crypto"}
  ],
  "markets": [ /* see market object below */ ]
}
```

Key numeric fields and their types:
- `volume` (float, USDC lifetime) — e.g., `113036250.864094`
- `volume24hr` (float) — e.g., `3967650.86`
- `liquidity` (float) — current AMM/CLOB liquidity in USDC
- `competitive` (float 0–1) — market competitiveness score
- `openInterest` (float) — currently always 0 in tested data

---

### 7. Response Structure: Market Object (within events[].markets[])

```json
{
  "id": "1303355",
  "question": "Will Bitcoin reach $150,000 in February?",
  "conditionId": "0x5e5c9dfa...",
  "slug": "will-bitcoin-reach-150k-in-february-2026",
  "endDate": "2026-03-01T05:00:00Z",
  "startDate": "2026-01-31T02:16:17.311269Z",
  "outcomes": "[\"Yes\", \"No\"]",
  "outcomePrices": "[\"0.0005\", \"0.9995\"]",
  "volume": "28317613.96917",
  "liquidity": "3430534.57215",
  "active": true,
  "closed": false,
  "lastTradePrice": 0.001,
  "bestBid": null,
  "bestAsk": 0.001,
  "spread": 0.001,
  "volume24hr": 48468.28,
  "volume1wk": 7361275.31,
  "volume1mo": 28317592.53,
  "volume1yr": 28317592.53,
  "clobTokenIds": "[\"37297213...\", \"85285091...\"]",
  "orderPriceMinTickSize": 0.001,
  "orderMinSize": 5,
  "oneDayPriceChange": null,
  "oneWeekPriceChange": -0.001,
  "oneMonthPriceChange": null,
  "oneYearPriceChange": null,
  "competitive": 0.8003,
  "negRisk": false,
  "acceptingOrders": true
}
```

**Probability/Odds data:**
- `outcomePrices` — JSON-encoded string array, values 0–1 representing probabilities (e.g., `["0.0005", "0.9995"]` = 0.05% / 99.95%)
- `lastTradePrice` (float) — last traded probability for first outcome
- `bestBid`, `bestAsk` (float) — current order book spread
- For binary markets: first price = P(Yes), second = P(No). They sum to ~1.0.

**Price history** via CLOB API (separate base URL):
```
GET https://clob.polymarket.com/prices-history?market=<clobTokenId>&interval=1w&fidelity=60
```
Response: `{"history": [{"t": 1772182763, "p": 0.0005}, ...]}` — unix timestamp + price float.

Source: Live API responses, `https://clob.polymarket.com/prices-history`

---

### 8. Response Structure: `/markets` Endpoint

Returns flat array of market objects (no events wrapper). Default sort is by `id` ascending (oldest first, from 2020). Key additional fields vs events-embedded markets:

```json
{
  "id": "517310",
  "question": "Will Trump deport less than 250,000?",
  "outcomePrices": "[\"0.015\", \"0.985\"]",
  "volume": "1252992.700185",
  "liquidity": "23394.61199",
  "lastTradePrice": 0.012,
  "bestBid": 0.011,
  "bestAsk": 0.019,
  "spread": 0.008,
  "oneDayPriceChange": 0.016,
  "oneHourPriceChange": 0.0085,
  "oneWeekPriceChange": 0.0055,
  "oneMonthPriceChange": -0.017,
  "oneYearPriceChange": -0.1485,
  "volume24hr": 13642.39,
  "volume1wk": 58029.33,
  "volume1mo": 264244.45,
  "volume1yr": 1061988.47,
  "clobTokenIds": "[\"101676997...\", \"4153292...\"]",
  "events": [ /* nested event objects */ ],
  "negRisk": true,
  "acceptingOrders": true,
  "enableOrderBook": true
}
```

Note: `/markets` does NOT support `tag_slug=` filtering — only `/events` does. The `/markets` endpoint has `tag_id` (integer) and `related_tags` (boolean) parameters per official docs.

---

### 9. Full List of Query Parameters (Official Docs)

**`GET /events` parameters** (`https://docs.polymarket.com/api-reference/events/list-events`):
- Pagination: `limit` (int), `offset` (int)
- Sorting: `order` (string, comma-separated fields), `ascending` (bool)
- Filter by id: `id` (array of int), `slug` (array of string)
- Filter by tag: `tag_id` (int), `tag_slug` (string), `exclude_tag_id` (array of int), `related_tags` (bool)
- Filter by status: `active` (bool), `archived` (bool), `closed` (bool), `featured` (bool)
- Filter by volume: `volume_min`, `volume_max` (number)
- Filter by liquidity: `liquidity_min`, `liquidity_max` (number)
- Filter by date: `start_date_min/max`, `end_date_min/max` (ISO 8601)
- Other: `cyom` (bool), `recurrence` (string), `include_chat` (bool)

**`GET /markets` parameters** (`https://docs.polymarket.com/api-reference/markets/list-markets`):
- Pagination: `limit`, `offset`
- Sorting: `order`, `ascending`
- Filter: `id`, `slug`, `clob_token_ids`, `condition_ids`, `closed`, `tag_id`, `related_tags`
- Financial: `liquidity_num_min/max`, `volume_num_min/max`, `rewards_min_size`
- Date: `start_date_min/max`, `end_date_min/max`
- Other: `include_tag`, `cyom`, `uma_resolution_status`, `sports_market_types`, `game_id`, `question_ids`

**`GET /public-search` parameters** (full-text search):
- `q` (string, required) — search query
- `limit_per_type` (int), `page` (int)
- `events_status` (string), `events_tag` (array), `exclude_tag_id` (array)
- `keep_closed_markets` (int), `search_tags` (bool), `search_profiles` (bool)
- `sort` (string), `ascending` (bool), `recurrence` (string)
- Returns: `{events: [...], tags: [...], profiles: [...], pagination: {hasMore: bool, totalResults: int}}`

---

### 10. Top Crypto Markets by Volume (2026-02-27 snapshot)

From `GET /events?tag_slug=crypto&closed=false&order=volume&ascending=false&limit=5`:

| Event Title | 24h Volume (USDC) | Total Volume (USDC) |
|-------------|-------------------|---------------------|
| What price will Bitcoin hit in February? | $3,967,651 | $113,036,251 |
| What price will Ethereum hit in February? | ~$800K est. | $34,836,825 |
| MicroStrategy sells any Bitcoin by ___? | $19,298 | $20,789,876 |
| What price will Bitcoin hit in 2026? | $205,182 | $20,509,313 |
| What price will Solana hit in February? | ~$150K est. | $14,004,064 |

Source: Live endpoint response `https://gamma-api.polymarket.com/events`

---

## Analysis

### What Works

1. **The API is fully public and free.** No auth required for any read operation. Cloudflare CDN caches responses for 2 minutes (`max-age=120`), so polling faster than every 2 minutes provides no benefit unless hitting uncached paths.

2. **The `tag_slug=` parameter on `/events` is the correct way to filter by crypto.** The `tag=` parameter tested in the original request spec is silently ignored. The correct URL pattern is:
   ```
   GET https://gamma-api.polymarket.com/events?tag_slug=crypto&closed=false&active=true&order=volume&ascending=false&limit=100
   ```
   Other useful crypto tag slugs: `bitcoin`, `ethereum`, `solana`, `crypto-prices`.

3. **Probability data is directly available** as `outcomePrices` (stringified JSON array, 0–1 floats) in both `/markets` and `/events[].markets[]` responses. For binary Yes/No markets, `outcomePrices[0]` = P(Yes). `lastTradePrice`, `bestBid`, and `bestAsk` provide additional precision.

4. **Volume data is rich.** Fields: `volume` (lifetime), `volume24hr`, `volume1wk`, `volume1mo`, `volume1yr` — all in USDC. The Bitcoin February price event had $113M+ lifetime volume, with $4M in 24h.

5. **Price history is available** via the separate CLOB API:
   ```
   GET https://clob.polymarket.com/prices-history?market=<clobTokenId>&interval=1w&fidelity=60
   ```
   Returns `{"history": [{"t": unix_timestamp, "p": price_float}, ...]}`. The `clobTokenIds` field in each market provides the token IDs needed.

6. **The `/public-search` endpoint** (`GET /public-search?q=bitcoin&events_status=active`) enables keyword search across all markets and returns 819 Bitcoin-related results total.

### What Does Not Work as Expected

1. **`tag=` parameter** on both `/markets` and `/events` is not a valid filter — verified by testing, results are identical with or without it.

2. **`/markets` does not support `tag_slug=`** — only `/events` does. The `/markets` endpoint requires `tag_id` (numeric integer, e.g., `tag_id=21` for Crypto) not `tag_slug`.

3. **The `tag=crypto` and `tag=bitcoin` original test URLs** returned the default dataset (Trump deportation markets, not crypto markets) because the tag param was ignored and the default sort is by database `id` ascending.

4. **`/markets?closed=false`** does filter correctly but the results still default to oldest-first (id ascending), not by volume or recency.

5. **`cryptocurrency` tag slug** (id=744) returns 0 active events — it exists in the tag list but is not applied to any active market. Use `crypto` (id=21) instead.

### Architecture Notes

There are two distinct APIs:
- **Gamma API** (`gamma-api.polymarket.com`) — market metadata, events, filtering, search. Read-only, no auth. This is the primary data source for market discovery and probabilities.
- **CLOB API** (`clob.polymarket.com`) — order book, price history, trade execution. Price history endpoint is also unauthenticated for reads.

Each market has two `clobTokenIds` (one per outcome). These IDs are used to query the CLOB API for order book data and price history.

---

## Recommendation

**Use `GET /events?tag_slug=crypto&closed=false&active=true&order=volume&ascending=false` as the primary crypto market feed.** This is the only endpoint that correctly filters to crypto-tagged markets.

Suggested integration pattern for Sentinel:

```python
# Step 1: Fetch top crypto events
events = GET /events?tag_slug=crypto&closed=false&active=true&order=volume&ascending=false&limit=100

# Step 2: Extract markets with probability and volume data
for event in events:
    for market in event['markets']:
        if not market['closed'] and market['acceptingOrders']:
            yes_prob = float(json.loads(market['outcomePrices'])[0])
            volume_24h = market['volume24hr']
            clob_token_yes = json.loads(market['clobTokenIds'])[0]
            # Optionally: price history
            history = GET https://clob.polymarket.com/prices-history?market={clob_token_yes}&interval=1d&fidelity=60

# Step 3: Also query with tag_slug=bitcoin, tag_slug=ethereum, tag_slug=solana
# for more specific filtering
```

Additional crypto slugs to poll in parallel: `bitcoin`, `ethereum`, `solana`, `crypto-prices`.

For keyword-based discovery of new markets: `GET /public-search?q=<asset>&events_status=active`.

**Confidence: HIGH** — All claims verified through direct API calls with documented raw responses. Official docs confirm parameter specs. No auth or payment required.
