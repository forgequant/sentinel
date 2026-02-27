# Fear & Greed Analytics — Research

CONTEXT: The feargreed skill (sentinel v1) needs concrete implementation patterns for z-score, percentile rank, multi-timeframe trend, consensus, and regime persistence analytics on a bounded daily index (0-100, one reading per day from alternative.me).
DATE: 2026-02-27

## Question

What are the best practices and concrete implementation patterns for computing z-score, percentile rank, multi-timeframe trend signals, consensus logic, and regime persistence on a daily bounded sentiment index (Crypto Fear & Greed, 0-100)? Focus on pure Python / stdlib, minimal dependencies, practical signal quality over statistical purity.

---

## Evidence

### 1. Z-Score: Window Size and Tradeoffs

**The core tradeoff** (source: [Rolling Z-Score Analysis — AlgoTradingLib](https://algotradinglib.com/en/pedia/r/rolling_z-score_analysis.html)):
- Smaller windows (10-20d): high responsiveness, picks up fresh moves, but noisy; can generate false signals.
- Larger windows (60-90d): smooth, stable baseline, but z-score "gets used to" elevated levels and fails to flag new extremes.
- A practical recommendation is to use a shorter rolling window so the z-score does not "get used to" high levels and fails to highlight new, big moves.

**Common choices in financial literature** (source: [Unlocking Market Insights — Medium](https://medium.com/@crisvelasquez/unlocking-market-signals-with-python-analyzing-rolling-z-scores-in-stock-trading-5b2ff34a6c5c)):
- 15-20d: three to four trading weeks — the dominant practitioner choice for short-term signals.
- 30d: one calendar month — balances responsiveness with stability; common in academic work.
- 60d: two months — preferred for regime-level context, not intraday sensitivity.

**Small-sample caveat** (source: [Bessel's Correction — Wikipedia](https://en.wikipedia.org/wiki/Bessel%27s_correction), [Towards Data Science](https://towardsdatascience.com/bessels-correction-why-do-we-divide-by-n-1-instead-of-n-in-sample-variance-30b074503bd9/)):
- For n < 10, Bessel's correction (dividing by n-1) is aggressive and the sample std is a poor population estimate anyway.
- Bessel's correction does not yield an unbiased estimator of stddev — it only corrects variance.
- For a bounded index like F&G (0-100), the population distribution is known to be non-normal and heavy-tailed around extremes; stddev estimates from 20d windows are inherently rough approximations.
- Mitigation: clamp the window to a minimum of 10 valid data points before computing z-score; also clamp stddev to a floor value (e.g. 1.0) to avoid division-by-near-zero when the index flatlines.

**Implementation pattern (stdlib only)**:
```python
from statistics import mean, stdev

def zscore(window: list[float], min_periods: int = 10) -> float | None:
    """Rolling z-score of the last value against its window.

    window: list of floats ordered oldest-to-newest; last element is current.
    Returns None if insufficient data or flat distribution.
    """
    if len(window) < min_periods:
        return None
    mu = mean(window)
    try:
        sigma = stdev(window)  # uses Bessel correction (n-1)
    except Exception:
        return None
    if sigma < 1.0:          # floor: bounded index rarely has stddev < 1
        sigma = 1.0
    return (window[-1] - mu) / sigma
```

**Chosen window for feargreed**: 30d. Rationale: one calendar month aligns with the natural cycle of market sentiment; alternative.me provides 7 years of daily data so 30d is cheap to compute; sensitive enough to flag fresh extremes without the noise of a 20d window.

---

### 2. Percentile Rank: scipy vs Manual, Window Size

**scipy.stats.percentileofscore** (source: [SciPy docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.percentileofscore.html)):
- Signature: `percentileofscore(a, score, kind='rank')`
- `kind='rank'`: averages percentage rankings of ties (best for a bounded integer-valued index).
- `kind='weak'`: counts values <= score (CDF interpretation, slightly more natural for signal thresholds).
- Returns 0-100 float.
- Requires scipy — acceptable but adds a dependency for a single function.

**Manual pure-stdlib alternative**:
```python
def percentile_rank(window: list[float], current: float) -> float | None:
    """Return 0-100 percentile rank of current in window.

    Uses 'weak' semantics: fraction of window values <= current.
    """
    if not window:
        return None
    count_le = sum(1 for v in window if v <= current)
    return (count_le / len(window)) * 100.0
```
This is O(n) and exactly equivalent to `scipy.stats.percentileofscore(window, current, kind='weak')`. For a 365-element window this is negligible.

**Window size**:
- 90d: captures one quarter — good for current-regime context (is the index historically low/high this quarter?). Recommended for primary signal.
- 365d: captures one year — detects true historical extremes. Useful as secondary annotation ("lowest in 12 months").
- Source: [Applications of Rolling Windows for Time Series — Towards Data Science](https://towardsdatascience.com/applications-of-rolling-windows-for-time-series-with-python-1a4bbe44901d/), [Statalist discussion on 252-day rolling rank](https://www.statalist.org/forums/forum/general-stata-discussion/general/1382327-creating-a-moving-percentile-rank-based-on-a-look-back-window-of-252-days)

**Decision for feargreed**: use manual `percentile_rank` (no scipy dependency), 90d window as primary. Optionally pass 365d window as secondary if data available.

---

### 3. Multi-Timeframe Trend Signals

**Three approaches** (source: [Slope — StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/slope), [Linear Regression Slope — QuantifiedStrategies](https://www.quantifiedstrategies.com/linear-regression-slope/)):

| Approach | Computes | Pro | Con |
|----------|----------|-----|-----|
| Simple delta | `current - value_Nd_ago` | trivial, fast, interpretable | sensitive to single-day outliers at endpoints |
| Rate of change | `(current / value_Nd_ago - 1) * 100` | normalized | meaningless for bounded index near 0 |
| Linear regression slope | `statistics.linear_regression(x, y).slope` | robust to noise, uses all window points | slightly more complex; can mislead if non-linear |

**For a bounded index (0-100)**, simple delta is the most interpretable because the unit is already the same scale as the index itself. A delta of -8 means "the index fell 8 points over N days" — directly meaningful. Regression slope has units of "points per day" which is equally clear but adds stdlib complexity.

**Recommendation for feargreed**: use **simple delta** for primary trend_Nd fields (already in the SKILL.md spec: `trend_7d`, `trend_30d`, `trend_90d`). Optionally compute OLS slope as an `analytics.slope_7d` secondary field using stdlib.

**Simple delta pattern**:
```python
def trend_delta(series: list[float], lookback: int) -> float | None:
    """Absolute change from lookback days ago to today.

    series: ordered oldest-to-newest.
    Returns None if insufficient data.
    """
    if len(series) <= lookback:
        return None
    return series[-1] - series[-(lookback + 1)]
```

**OLS slope (stdlib, Python 3.10+)**:
```python
from statistics import linear_regression

def trend_slope(series: list[float]) -> float | None:
    """Points-per-day slope of linear regression over the window.

    Positive = index rising, negative = falling.
    """
    if len(series) < 2:
        return None
    x = list(range(len(series)))
    try:
        result = linear_regression(x, series)
        return round(result.slope, 3)
    except Exception:
        return None
```

**Note**: `statistics.linear_regression` was added in Python 3.10. For compatibility with earlier Python, compute manually:
```python
def trend_slope_compat(series: list[float]) -> float | None:
    n = len(series)
    if n < 2:
        return None
    x = list(range(n))
    xbar = (n - 1) / 2.0       # mean of 0..n-1
    ybar = sum(series) / n
    num = sum((x[i] - xbar) * (series[i] - ybar) for i in range(n))
    den = sum((xi - xbar) ** 2 for xi in x)
    return round(num / den, 3) if den else None
```

---

### 4. Consensus Logic

**Industry pattern** (source: [MQL5 Multi-Timeframe Harmony Index](https://www.mql5.com/en/articles/20097), [TradingView multi-timeframe voting systems](https://tradewiththepros.com/multi-timeframe-analysis/)):

The standard practitioner approach is a **2-of-N majority vote** with optional weighting. The MQL5 Harmony Index defaults to "minimum consensus threshold: 2 of 3". Weighted variants normalize to [-1, 1] and apply a 0.4 moderate / 0.8 strong threshold.

**For feargreed** the three signals are trend_7d, trend_30d, trend_90d. Each carries a directional label:
- `"rising"` if delta > threshold (e.g. +3 points)
- `"falling"` if delta < -threshold
- `"flat"` if within threshold

```python
def classify_trend(delta: float | None, threshold: float = 3.0) -> str:
    """Classify a delta as rising/falling/flat."""
    if delta is None:
        return "unknown"
    if delta > threshold:
        return "rising"
    if delta < -threshold:
        return "falling"
    return "flat"

def consensus(labels: list[str]) -> str:
    """Return 'aligned', 'mixed', or 'unknown' from a list of trend labels.

    'aligned' = 2 or more labels agree on rising or falling (not flat).
    'mixed'   = no clear majority.
    """
    valid = [l for l in labels if l in ("rising", "falling")]
    if not valid:
        return "unknown"
    rising_count = sum(1 for l in valid if l == "rising")
    falling_count = sum(1 for l in valid if l == "falling")
    majority = len(labels) // 2 + 1          # e.g. 2 out of 3
    if rising_count >= majority:
        return "aligned"
    if falling_count >= majority:
        return "aligned"
    return "mixed"
```

**Threshold of +/-3 points**: for a 0-100 bounded index updated once per day, movement < 3 points is within normal day-to-day noise (stddev of daily changes is typically 5-8 points in normal periods, higher during volatility). A 3-point threshold filters noise without being too conservative. This is empirically reasonable — not derived from a formal test.

---

### 5. Regime Persistence: Consecutive Days in a Zone

**The standard pattern** (source: [Calculating Streaks in Pandas — Josh Devlin](https://joshdevlin.com/blog/calculate-streaks-in-pandas/), [Count Consecutive Events — Predictive Hacks](https://predictivehacks.com/count-the-consecutive-events-in-python/)):

```python
def consecutive_days_in_zone(
    series: list[float],
    low: float,
    high: float,
) -> int:
    """Count how many trailing consecutive days the last value has been in [low, high].

    series: ordered oldest-to-newest.
    Returns 0 if current value is not in zone.
    """
    if not series:
        return 0
    count = 0
    for value in reversed(series):
        if low <= value <= high:
            count += 1
        else:
            break
    return count
```

This avoids pandas entirely. It's O(k) where k is the streak length, which is always short (typical streaks are 1-30 days).

**Zone boundaries** for feargreed should mirror the `--oversold` / `--overbought` thresholds passed at runtime. For the default 25/75 split, regime_days counts how long the index has been below 25 (extreme fear zone) or above 75 (extreme greed zone).

**Research backing** (source: [Decoding Crypto Market Sentiment — AInvest](https://www.ainvest.com/news/decoding-crypto-market-sentiment-fear-greed-index-contrarian-compass-2509/)): markets rebound 80% of the time after the index signals extreme fear below 20. Regime persistence amplifies this — the longer the streak in extreme fear, the more statistically meaningful the contrarian signal.

---

### 6. Edge Cases: Missing Days, API Gaps

**Alternative.me API behavior** (source: [Alternative.me Crypto Fear & Greed](https://alternative.me/crypto/fear-and-greed-index/), [QuantConnect Fear and Greed docs](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/quantconnect/fear-and-greed)):
- The index publishes **every day including weekends** — it is not exchange-day aligned. Unlike stock market sentiment indices, crypto F&G has no gap for Saturday/Sunday.
- QuantConnect docs note: "Each data point shows the index value at the end of the trading day" and "each data point is valued the same as the day before in order to visualize meaningful progress." Forward fill is used internally when a source component is unavailable.
- The API returns Unix timestamps. When fetching N days, the response may occasionally have fewer entries if the API has an outage or rate-limits. Always validate `len(data) == requested_days` before computing analytics.

**Handling strategy**:
```python
from datetime import datetime, timedelta

def fill_gaps(
    records: list[dict],          # [{"timestamp": int, "value": float}, ...]
    expected_days: int,
) -> list[float]:
    """
    Sort records by timestamp, forward-fill missing days, return ordered values.

    If fewer records than expected, fills remaining head with first available value.
    If a date gap exists mid-series, forward-fills the gap with the prior value.
    """
    if not records:
        return []

    records_sorted = sorted(records, key=lambda r: r["timestamp"])

    # Build a date-keyed dict
    by_date: dict[str, float] = {}
    for r in records_sorted:
        dt = datetime.utcfromtimestamp(r["timestamp"]).date()
        by_date[str(dt)] = float(r["value"])

    # Walk expected_days backwards from the latest date
    latest_date = datetime.utcfromtimestamp(records_sorted[-1]["timestamp"]).date()
    values: list[float] = []
    last_known: float | None = None

    for i in range(expected_days - 1, -1, -1):
        d = str(latest_date - timedelta(days=i))
        if d in by_date:
            last_known = by_date[d]
        if last_known is not None:
            values.append(last_known)

    return values
```

**Key rule**: forward-fill (carry-forward) is the correct policy — not interpolation, not zero-fill. Interpolation introduces lookahead on a live system (you don't know tomorrow's value). Carry-forward matches how the index itself is defined on weekends.

---

### 7. Statistical Pitfalls

**Short-window z-scores are unstable** (source: [Nonstationary Z-score measures — Munich MPRA](https://mpra.ub.uni-muenchen.de/67840/1/MPRA_paper_67840.pdf), [A Case for the T-statistic — Towards Data Science](https://towardsdatascience.com/a-case-for-the-t-statistic/)):

1. **Flat-period blow-up**: if the index is unchanged for 10+ days (rare but possible), stddev approaches 0. The z-score becomes ±infinity. Fix: `sigma = max(sigma, floor_value)` with floor = 1.0 for a 0-100 scale.

2. **Non-normality**: F&G values cluster near the boundaries (extreme readings are sticky). The z-score assumes normality. For a bounded [0,100] index this is systematically violated at the tails. Treat z-score as a relative position indicator, not a probabilistic statement about how "many standard deviations" rare the reading is. Do not use `NormalDist.cdf(zscore)` to derive probabilities.

3. **Bessel overcorrection at small n**: for n=10, dividing by n-1=9 instead of n=10 adds ~11% to the std estimate. For n=30 this is ~3.4% — acceptable. Minimum window of 10 before computing; prefer 20+.

4. **Endpoint sensitivity in deltas**: `trend_7d = current - value_7d_ago` is sensitive to noise at both endpoints. A single-day spike 7 days ago inflates the apparent trend. Mitigation: use a 3-day average at each endpoint instead of a single point.

```python
def robust_delta(series: list[float], lookback: int, smooth: int = 1) -> float | None:
    """Delta with optional endpoint smoothing.

    smooth=1 means no smoothing (raw delta).
    smooth=3 means average the 3 days around each endpoint.
    """
    if len(series) < lookback + smooth:
        return None
    current_avg = sum(series[-smooth:]) / smooth
    prior_avg = sum(series[-(lookback + smooth):-(lookback)]) / smooth
    return current_avg - prior_avg
```

5. **Bounded index and z-score symmetry**: at an index value of 5 (near-minimum), a negative z-score of -2.0 implies values would need to go to approximately `mean - 2*sigma`, which could be negative — impossible for a 0-100 bounded index. Clamp z-scores to [-3, 3] in output for interpretability.

---

### 8. Academic and Practitioner References

**Academic findings on F&G contrarian signals**:
- Contrarian pattern holds in 14 of 18 rolling 6-month windows (77.8%), markets rebound 80% of the time after index below 20. Source: [Decoding Crypto Market Sentiment — AInvest](https://www.ainvest.com/news/decoding-crypto-market-sentiment-fear-greed-index-contrarian-compass-2509/)
- Extreme fear/greed regimes exhibit "extremity premium" — significantly higher bid-ask spreads than neutral periods. Sentiment extremity predicts excess uncertainty beyond realized volatility. Source: [Arxiv 2602.07018](https://arxiv.org/html/2602.07018)
- Sentiment-enhanced models show durable edge across 10-, 15-, 20-day lookback windows in crypto. Source: [Sentiment-Aware Portfolio Optimization — Arxiv 2508.16378](https://arxiv.org/pdf/2508.16378)
- Combining multimodal sentiment (social + index) improves forecasts 20-35% vs single-source. Source: [Enhancing Cryptocurrency Sentiment Analysis — Arxiv 2508.15825](https://arxiv.org/html/2508.15825v1)

**Practitioner references on z-score in finance**:
- [Rolling Z-Score Analysis — AlgoTradingLib](https://algotradinglib.com/en/pedia/r/rolling_z-score_analysis.html): window=20 as baseline, threshold ±2 for signals.
- [PyQuant News — Rolling Statistics](https://www.pyquantnews.com/the-pyquant-newsletter/visualize-the-trend-with-pandas-rolling): rolling statistics for trend context in financial data.
- [QuantInsti — Standard Deviation in Trading](https://blog.quantinsti.com/standard-deviation/): stddev floor practices in live signal systems.

**Python stdlib references**:
- [Python statistics module — docs.python.org](https://docs.python.org/3/library/statistics.html): `statistics.mean`, `statistics.stdev`, `statistics.linear_regression` (3.10+), `statistics.NormalDist`.
- `statistics.linear_regression` returns a named tuple with `.slope` and `.intercept`; raises `StatisticsError` if x is constant or fewer than 2 points.

---

## Analysis

### Why 30d for z-score (not 20d or 60d)

20d (one trading month) is the most common choice in equity markets but crypto operates 24/7 with weekend readings. 30d = 30 calendar days = one natural month, aligns with monthly reporting cycles and human cognitive framing of "the last month." It is responsive enough (30 daily points is adequate for a stable mean/std estimate for a bounded-range 0-100 index) without the instability of a 20d window where a single outlier moves the mean by ~5%.

60d is better for characterizing regime context but too sluggish for actionable short-term signals. It should be reserved for a secondary context field if needed.

### Why simple delta (not slope) for trend_Nd

The SKILL.md spec already defines `trend_7d`, `trend_30d`, `trend_90d` as "change from N days ago (absolute)". Simple delta is interpretable without explanation: "the index fell 8 points in the last 7 days" is immediately actionable. OLS slope (e.g., "-0.4 points/day over 90 days") requires more mental arithmetic. However, slope should be added as an optional `analytics.slope_7d` field because it is more robust to endpoint noise — it uses all 7 data points rather than just day 1 and day 7.

### Why carry-forward (not interpolation) for gaps

Crypto F&G publishes 7 days a week, so true gaps are rare (API outages). When a gap does appear, we do not know the "true" missing value — interpolation assumes we do, which introduces lookahead contamination in any live system. Carry-forward matches the API's own gap-filling policy (confirmed by multiple data provider docs).

### Why manual percentile (not scipy)

scipy is not a stdlib module. For a 90-element window, `sum(1 for v in window if v <= current) / len(window) * 100` is O(90) = negligible. The `kind='weak'` semantics (count values ≤ current) are the most natural for a "where does today sit in recent history" question. This avoids importing scipy for a trivially simple calculation, keeping the skill dependency-minimal per the project's constraints.

### Consensus threshold: 2 of 3

Two-of-three is the industry default (confirmed by MQL5 Harmony Index, TradingView multi-timeframe systems). For F&G with three timeframes (7d/30d/90d), requiring all three to agree would be too strict (the 90d trend is inherently slower and often lags). Requiring only one would be too loose. Two of three "filters noise by requiring quantitative agreement between non-correlated timeframes" (MQL5 source). The directional threshold of +/-3 points is calibrated for the 0-100 scale; it should be a runtime parameter so users can tune it.

---

## Recommendation

**Use these patterns in the feargreed skill implementation:**

| Analytic | Implementation | Window | Notes |
|----------|---------------|--------|-------|
| `zscore_30d` | Manual (statistics.mean / stdev) | 30d | Floor sigma at 1.0, clamp output to [-3, 3], min 10 periods |
| `percentile_90d` | Manual count (no scipy) | 90d | kind='weak' semantics, return 0-100 |
| `trend_7d/30d/90d` | Simple delta (last - Nd_ago) | 7/30/90d | Optionally smooth with 3-day endpoint average |
| `slope_7d` | statistics.linear_regression or compat | 7d | Secondary field; points/day |
| `regime_days` | Reverse-scan from tail | Trailing | Stop at first out-of-zone day |
| `consensus` | 2-of-3 majority vote | 3 labels | Threshold ±3 points for rising/falling/flat |
| Gap fill | Carry-forward by date | Full window | Sort by timestamp, fill by calendar date |

**Confidence: HIGH** — all six calculation patterns are backed by multiple practitioner sources, confirmed by academic findings on F&G contrarian signal efficacy, and cross-validated against Python stdlib documentation. The specific numeric parameters (30d, 90d, ±3 threshold, 2-of-3 vote) are grounded in practitioner convention and the bounded nature of the 0-100 index, though they should remain configurable runtime parameters rather than hardcoded constants.

**One open question (LOW confidence)**: whether the ±3-point trend threshold is optimal for a particular market regime (trending vs. flat). A formal threshold derivation would require backtesting against historical F&G data, which is out of scope for this research pass but is a natural next step.
