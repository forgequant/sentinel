# LunarCrush TDD Implementation Plan

**Date:** 2026-02-27
**Budget:** ~300-350 lines Python, ~35 tests
**Dependencies:** stdlib only (Python 3.12+)
**Codex rating:** 8/10 (revised with feedback)

## Task 1: Auth & Fetch

**Tests (~8):**
1. `test_fetch_coins_parses_response` — mock urlopen, verify coins parsed with galaxy_score, sentiment, alt_rank
2. `test_fetch_coins_empty_response` — API returns empty data → empty list
3. `test_fetch_coins_network_error_returns_empty` — urlopen raises → empty list
4. `test_fetch_no_api_key` — LUNARCRUSH_API_KEY not set → raises AuthError
5. `test_fetch_empty_api_key` — LUNARCRUSH_API_KEY="" or whitespace → raises AuthError
6. `test_fetch_auth_error_401` — HTTP 401 → raises AuthError with message
7. `test_fetch_rate_limited_429` — HTTP 429 → raises RateLimitError
8. `test_fetch_partial_coins_skip_null_galaxy` — some coins have galaxy_score=None → filtered out

**Implementation:**
- `fetch_coins(limit, sort)` → list of coin dicts
- `AuthError(Exception)` / `RateLimitError(Exception)` custom exceptions
- Bearer token from `LUNARCRUSH_API_KEY` env var, strip whitespace
- Filter coins where galaxy_score is None

## Task 2: Cache

**Tests (~3):**
1. `test_save_and_load_cache` — round-trip save/load with atomic write
2. `test_load_missing_returns_none` — no file → (None, 0)
3. `test_load_corrupted_returns_none` — bad JSON → (None, 0)

**Implementation:**
- `_save_cache(data, path)` / `_load_cache(path)` → (data, timestamp)
- Atomic writes: write to `.tmp` → `os.replace()`
- Same pattern as feargreed/news-scanner/polymarket

## Task 3: Signal Computation

**Tests (~7):**
1. `test_normalize_coin_all_fields` — galaxy=78, sentiment=72, alt_rank=3, prev=5 → social_score
2. `test_normalize_coin_missing_sentiment` — sentiment=None → treated as 0
3. `test_normalize_coin_altrank_no_previous` — alt_rank_previous=None → altrank_norm=0.5
4. `test_normalize_coin_altrank_small_previous` — alt_rank_previous=1 → uses max(prev, 10) denominator
5. `test_aggregate_bullish` — avg_social > 0.60 → bullish
6. `test_aggregate_bearish` — avg_social < 0.40 → bearish
7. `test_aggregate_weighted_by_dominance` — coins with high social_dominance weight more

**Implementation:**
- `normalize_coin(coin)` → social_score float
- `compute_signal(coins)` → {signal, avg_social, avg_galaxy, avg_sentiment, avg_alt_rank, total_interactions, movers}
- Weight by social_dominance, fallback to simple average
- Clamp all inputs to valid ranges before normalization

## Task 4: Movers Detection

**Tests (~3):**
1. `test_movers_improving` — alt_rank dropped significantly → in improving list
2. `test_movers_declining` — alt_rank rose significantly → in declining list
3. `test_movers_skip_no_delta` — coins with no alt_rank_previous → excluded from movers

**Implementation:**
- `detect_movers(coins, top_n=5)` → {improving: [...], declining: [...]}
- Sort by absolute delta, take top N each direction
- Exclude coins with None/0 delta

## Task 5: Confidence Scoring

**Tests (~5):**
1. `test_high_galaxy_high_confidence` — strong signal + high galaxy → high confidence
2. `test_neutral_low_confidence` — avg_social near 0.5 → low confidence
3. `test_engagement_boosts_confidence` — more interactions → higher engagement component
4. `test_momentum_boosts_confidence` — large altrank delta → higher momentum component
5. `test_confidence_always_in_range` — parametric sweep → always 15-100

**Implementation:**
- `compute_confidence(signal_edge, avg_galaxy, total_interactions, avg_altrank_delta)` → int 15-100
- 4 components: signal_edge(0.35), galaxy_strength(0.25), engagement(0.20), momentum(0.20)

## Task 6: End-to-End & CLI

**Tests (~9):**
1. `test_main_outputs_valid_signal_json` — mock fetch → stdout is valid SignalOutput v1
2. `test_main_no_api_key_neutral` — no key → neutral, confidence=0, stderr warning
3. `test_main_with_coin_filter` — --coins BTC,ETH → only those symbols in output
4. `test_main_with_min_galaxy` — --min-galaxy 50 → filters low-galaxy coins
5. `test_main_empty_response_neutral` — empty API response → neutral, confidence=15
6. `test_main_auth_error` — 401 → neutral, confidence=0, stderr auth error
7. `test_main_cache_fresh_fallback` — network error + fresh cache (<60s) → uses cached data
8. `test_main_cache_stale_fallback` — network error + stale cache (<30m) → uses cached, lower confidence
9. `test_main_cache_expired_neutral` — network error + expired cache (>30m) → neutral, confidence=15

**Implementation:**
- `main()` with argparse: --limit, --sort, --coins, --min-galaxy
- SignalOutput v1 to stdout, human summary to stderr
- Graceful degradation chain: fetch → fresh cache → stale cache → neutral

## Total: ~35 tests, ~300-350 lines
