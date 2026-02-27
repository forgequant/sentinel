# polymarket TDD Implementation Plan

**Date:** 2026-02-27
**Budget:** ~380-420 lines Python, ~40 tests
**Dependencies:** stdlib only (Python 3.12+)
**Codex rating:** 7/10 (revised with feedback)

## Task 1: Fetch & Parse Events

**Tests (~8):**
1. `test_fetch_events_parses_response` — mock urlopen, verify events parsed with title, slug, markets
2. `test_fetch_events_dedup_by_id` — two tag_slugs return same event → deduplicated
3. `test_fetch_events_network_error_returns_empty` — urlopen raises → empty list
4. `test_fetch_partial_failure_still_works` — one tag_slug fails, others succeed → returns partial results
5. `test_parse_market_probability` — outcomePrices=["0.72","0.28"] → yes_prob=0.72
6. `test_parse_market_no_yes_fallback` — outcomes without "Yes" → uses first price
7. `test_parse_market_missing_prices` — outcomePrices is None/empty → returns None
8. `test_parse_market_invalid_json_prices` — malformed JSON string → returns None

**Implementation:**
- `fetch_events(tag_slugs, limit)` → list of normalized event dicts
- `parse_probability(market)` → float or None
- Default tag_slugs: `["crypto", "bitcoin", "ethereum", "solana"]`
- Dedup by event id

## Task 2: Cache

**Tests (~3):**
1. `test_save_and_load_cache` — round-trip save/load
2. `test_load_missing_returns_none` — no file → (None, 0)
3. `test_load_corrupted_returns_none` — bad JSON → (None, 0)

**Implementation:**
- `_save_cache(data, path)` / `_load_cache(path)` → (data, timestamp)
- Same pattern as feargreed/news-scanner

## Task 3: Event Classification

**Tests (~7):**
1. `test_classify_binary_bullish` — "Will Bitcoin reach $100k?" → binary, bullish
2. `test_classify_binary_bearish` — "Will crypto market crash?" → binary, bearish
3. `test_classify_curve_event` — event with multiple numeric strikes → curve type
4. `test_classify_daily_horizon` — endDate within 7 days → daily
5. `test_classify_structural_horizon` — endDate > 7 days → structural
6. `test_classify_no_enddate` — missing endDate → structural (default)
7. `test_classify_unclassifiable` — no bullish/bearish words → neutral direction

**Implementation:**
- `classify_event(event)` → adds `_type` (binary/curve), `_horizon` (daily/structural), `_direction` (bullish/bearish/neutral)
- `is_curve_event(event)` → True if ≥2 sub-markets have parseable numeric strikes
- `parse_horizon(event)` → daily (<7d) or structural (≥7d), None → structural

## Task 4: Price Curve Extraction

**Tests (~7):**
1. `test_extract_strike_dollar_comma` — "Will BTC reach $80,000?" → 80000
2. `test_extract_strike_k_suffix` — "Will BTC reach $80k?" → 80000
3. `test_extract_strike_plain_number` — "Bitcoin above 80000" → 80000
4. `test_build_curve_sorted` — multiple strikes → sorted by value with probabilities
5. `test_compute_median_from_curve` — curve → median strike value
6. `test_compute_spread_from_curve` — curve → IQR spread
7. `test_curve_single_strike_returns_none` — only 1 parseable strike → None (need ≥2)

**Implementation:**
- `extract_strike(question)` → float or None
  - Patterns: `$80,000`, `$80k`, `$80,000.00`, `80000`, `80K`
- `build_price_curve(event)` → dict or None
  - Requires ≥2 valid strikes
  - Sort by strike, pair with yes_probabilities
  - Compute: median (interpolated 50th percentile), spread (IQR), skew

## Task 5: Coin Detection & Directional Scoring

**Tests (~5):**
1. `test_detect_bitcoin_from_title` — "Bitcoin ETF approval?" → ["BTC"]
2. `test_detect_ethereum_from_question` — "Will ETH reach $5k?" → ["ETH"]
3. `test_directional_bullish_simple` — "reach $100k" with prob 0.72 → bullish_prob=0.72
4. `test_directional_bearish_inverted` — "crash below $50k" with prob 0.60 → bullish_prob=0.40
5. `test_aggregate_directional_signal` — mix of bullish/bearish → weighted avg

**Implementation:**
- `detect_coins(text)` — same approach as news-scanner (top-30 regex)
- `bullish_probability(market)` → float or None (unclassifiable)
- `compute_signal(events)` → {signal, avg_bullish, directional_count, horizon_breakdown}

## Task 6: Confidence Scoring

**Tests (~5):**
1. `test_high_edge_high_confidence` — strong signal + good volume → high confidence
2. `test_neutral_low_confidence` — avg_bullish near 0.5 → low confidence
3. `test_volume_boosts_confidence` — more volume → higher confidence
4. `test_time_decay_reduces_confidence` — far expiry → lower time component
5. `test_confidence_always_in_range` — parametric sweep → always 15-100

**Implementation:**
- `compute_confidence(signal_edge, liquidity, volume24hr, n_markets, median_days_to_expiry)` → int 15-100
- 5 components: signal_edge(0.45), liquidity(0.20), volume(0.15), depth(0.10), time(0.10)
- Zero/missing inputs: default to 0 for that component (no NaN propagation)

## Task 7: End-to-End & CLI

**Tests (~5):**
1. `test_main_outputs_valid_signal_json` — mock fetch → stdout is valid SignalOutput v1
2. `test_main_with_horizon_filter` — --horizon daily → only daily markets
3. `test_main_with_coin_filter` — --coins BTC → only BTC markets
4. `test_main_with_min_volume` — --min-volume 10000 → filters low-volume
5. `test_main_no_events_neutral` — empty response → neutral signal with low confidence

**Implementation:**
- `main()` with argparse: --limit, --min-volume, --horizon, --coins
- SignalOutput v1 to stdout, human summary to stderr
- Graceful degradation: empty response → neutral with confidence=15

## Total: ~40 tests, ~380-420 lines
