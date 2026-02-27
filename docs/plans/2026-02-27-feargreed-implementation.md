# feargreed v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the feargreed skill for sentinel plugin — a robust, stdlib-only Python script that fetches the Crypto Fear & Greed Index with configurable thresholds, weighted confidence scoring, and multi-timeframe analytics.

**Architecture:** Single file `feargreed.py` with logical sections: fetch → cache → analytics → scoring → cli. Uses `lib/protocols.py` for SignalOutput. All stdlib — no external dependencies. PEP 723 inline metadata for `uv run`.

**Tech Stack:** Python 3.12+, stdlib only (argparse, json, statistics, urllib.request, dataclasses, pathlib)

**Research:** See `docs/research/feargreed-*.md` for API details, analytics patterns, community findings.

---

### Task 1: Test infrastructure + fetch_fng

**Files:**
- Create: `skills/feargreed/scripts/feargreed.py`
- Create: `tests/test_feargreed.py`

**Step 1: Write the test file with fetch tests**

```python
# tests/test_feargreed.py
"""Tests for feargreed skill."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts to path for import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "feargreed" / "scripts"))


def _make_api_response(values: list[int], time_until_update: int = 3600) -> bytes:
    """Build a fake alternative.me API response."""
    data = []
    ts = 1740700800  # 2025-02-28 00:00:00 UTC
    for i, v in enumerate(values):
        entry = {"value": str(v), "value_classification": "Fear",
                 "timestamp": str(ts - i * 86400)}
        if i == 0:
            entry["time_until_update"] = str(time_until_update)
        data.append(entry)
    return json.dumps({"name": "Fear and Greed Index", "data": data,
                        "metadata": {"error": None}}).encode()


class TestFetchFng:
    """Tests for fetch_fng function."""

    @patch("urllib.request.urlopen")
    def test_fetch_parses_string_values_to_int(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_api_response([42, 38, 55])
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from feargreed import fetch_fng
        entries = fetch_fng(days=3)

        assert len(entries) == 3
        assert entries[0]["value"] == 42
        assert isinstance(entries[0]["value"], int)

    @patch("urllib.request.urlopen")
    def test_fetch_validates_value_range(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_api_response([150])
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from feargreed import fetch_fng
        with pytest.raises(ValueError, match="out of range"):
            fetch_fng(days=1)

    @patch("urllib.request.urlopen")
    def test_fetch_returns_time_until_update(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_api_response([50], time_until_update=7200)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from feargreed import fetch_fng
        entries = fetch_fng(days=1)
        assert entries[0].get("time_until_update") == 7200
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/vi/personal/forgequant/crucible/sentinel && python -m pytest tests/test_feargreed.py -v`
Expected: FAIL — `feargreed` module not found

**Step 3: Write minimal fetch_fng**

```python
# skills/feargreed/scripts/feargreed.py
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Crypto Fear & Greed Index — contrarian/momentum sentiment signal.

Part of the Crucible Sentinel plugin.
API: api.alternative.me/fng/ (free, no auth)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import linear_regression, mean, stdev
from typing import Any

# ---------------------------------------------------------------------------
# Protocols (inline to keep single-file; mirrors lib/protocols.py)
# ---------------------------------------------------------------------------

@dataclass
class SignalOutput:
    signal: str
    confidence: int
    reasoning: str
    data: dict[str, Any] = field(default_factory=dict)
    analytics: dict[str, Any] = field(default_factory=dict)
    schema: str = "signal/v1"

    def emit(self) -> None:
        print(json.dumps(asdict(self), ensure_ascii=False))

    def summary(self, text: str) -> None:
        print(text, file=sys.stderr)


@dataclass
class ErrorOutput:
    error: str
    details: str = ""
    schema: str = "error/v1"

    def emit(self) -> None:
        print(json.dumps(asdict(self), ensure_ascii=False))
        sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_URL = "https://api.alternative.me/fng/"
CACHE_DIR = Path.home() / ".cache" / "crucible"
CACHE_FILE = CACHE_DIR / "feargreed.json"
STALE_WINDOW_S = 36 * 3600  # 36 hours
MAX_RETRIES = 3
TIMEOUT_S = 8

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_fng(days: int = 0) -> list[dict]:
    """Fetch Fear & Greed data. days=0 means all history."""
    url = f"{API_URL}?limit={days}&format=json"
    data = _fetch_with_retry(url)

    entries = []
    for i, item in enumerate(data.get("data", [])):
        value = int(item["value"])
        if not 0 <= value <= 100:
            raise ValueError(f"FGI value out of range: {value}")
        ts = int(item["timestamp"])
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        entry = {"value": value, "date": date, "timestamp": ts}
        if i == 0 and "time_until_update" in item:
            entry["time_until_update"] = int(item["time_until_update"])
        entries.append(entry)
    return entries


def _fetch_with_retry(url: str) -> dict:
    """Fetch URL with exponential backoff + jitter. Returns parsed JSON."""
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                delay = min(6, 0.5 * 2 ** attempt + random.uniform(0, 0.2))
                time.sleep(delay)
    raise ConnectionError(f"API failed after {MAX_RETRIES + 1} attempts: {last_err}")
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/vi/personal/forgequant/crucible/sentinel && python -m pytest tests/test_feargreed.py -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
cd /Users/vi/personal/forgequant/crucible/sentinel
git add skills/feargreed/scripts/feargreed.py tests/test_feargreed.py
git commit -m "feat(feargreed): fetch with retry, int cast, range validation"
```

---

### Task 2: Cache layer

**Files:**
- Modify: `skills/feargreed/scripts/feargreed.py` (add cache functions)
- Modify: `tests/test_feargreed.py` (add cache tests)

**Step 1: Write cache tests**

```python
class TestCache:
    def test_save_and_load_cache(self, tmp_path):
        from feargreed import _save_cache, _load_cache
        cache_file = tmp_path / "fg.json"
        data = [{"value": 42, "date": "2026-02-27"}]
        _save_cache(data, cache_file)
        loaded, ts = _load_cache(cache_file)
        assert loaded == data
        assert ts > 0

    def test_load_missing_cache_returns_none(self, tmp_path):
        from feargreed import _load_cache
        result = _load_cache(tmp_path / "nonexistent.json")
        assert result == (None, 0)

    def test_stale_cache_detected(self, tmp_path):
        from feargreed import _save_cache, _is_cache_fresh
        cache_file = tmp_path / "fg.json"
        _save_cache([], cache_file)
        # Fresh with generous TTL
        assert _is_cache_fresh(cache_file, ttl=99999)
        # Stale with 0 TTL
        assert not _is_cache_fresh(cache_file, ttl=0)
```

**Step 2: Run tests — expect FAIL**

**Step 3: Implement cache functions**

```python
# Add to feargreed.py after fetch section

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _save_cache(data: list[dict], path: Path = CACHE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {"timestamp": time.time(), "data": data}
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.rename(path)  # atomic on POSIX


def _load_cache(path: Path = CACHE_FILE) -> tuple[list[dict] | None, float]:
    try:
        payload = json.loads(path.read_text())
        return payload["data"], payload["timestamp"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None, 0


def _is_cache_fresh(path: Path = CACHE_FILE, ttl: float = 3600) -> bool:
    _, ts = _load_cache(path)
    return (time.time() - ts) < ttl
```

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat(feargreed): two-layer cache with atomic writes"
```

---

### Task 3: Analytics — z-score, percentile, trends, consensus, regime

**Files:**
- Modify: `skills/feargreed/scripts/feargreed.py` (add analytics functions)
- Modify: `tests/test_feargreed.py` (add analytics tests)

**Step 1: Write analytics tests**

```python
class TestAnalytics:
    def test_zscore_normal_data(self):
        from feargreed import compute_zscore
        # Mean ~50, stddev ~10
        window = [40, 45, 50, 55, 60, 50, 45, 55, 50, 48,
                  52, 47, 53, 49, 51, 46, 54, 50, 48, 52,
                  50, 45, 55, 50, 48, 52, 47, 53, 49, 51]
        result = compute_zscore(window)
        assert result is not None
        assert -3.0 <= result <= 3.0

    def test_zscore_constant_data_returns_zero(self):
        from feargreed import compute_zscore
        # All same value — sigma floored to 1.0, so zscore = 0
        window = [50] * 30
        result = compute_zscore(window)
        assert result == 0.0

    def test_zscore_too_few_points_returns_none(self):
        from feargreed import compute_zscore
        result = compute_zscore([50, 60, 70])
        assert result is None

    def test_percentile_rank(self):
        from feargreed import compute_percentile
        window = list(range(1, 101))  # 1..100
        assert compute_percentile(window, 50) == 50.0
        assert compute_percentile(window, 1) == 1.0
        assert compute_percentile(window, 100) == 100.0

    def test_percentile_empty_returns_none(self):
        from feargreed import compute_percentile
        assert compute_percentile([], 50) is None

    def test_trend_delta(self):
        from feargreed import compute_trend_delta
        series = [30, 35, 40, 45, 50, 55, 60]  # rising
        assert compute_trend_delta(series, 7) == 30  # 60 - 30

    def test_trend_delta_insufficient_data(self):
        from feargreed import compute_trend_delta
        assert compute_trend_delta([50], 7) is None

    def test_consensus_aligned(self):
        from feargreed import compute_consensus
        assert compute_consensus(["rising", "rising", "flat"]) == "aligned"
        assert compute_consensus(["falling", "falling", "rising"]) == "aligned"

    def test_consensus_mixed(self):
        from feargreed import compute_consensus
        assert compute_consensus(["rising", "falling", "flat"]) == "mixed"

    def test_regime_days(self):
        from feargreed import compute_regime_days
        # Last 5 values all in fear zone (< 45)
        values = [60, 55, 40, 35, 30, 25, 20]
        assert compute_regime_days(values, low=0, high=45) == 5

    def test_regime_days_none_in_zone(self):
        from feargreed import compute_regime_days
        values = [80, 75, 70]
        assert compute_regime_days(values, low=0, high=45) == 0
```

**Step 2: Run tests — expect FAIL**

**Step 3: Implement analytics functions**

```python
# Add to feargreed.py

# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

MIN_ZSCORE_POINTS = 10
SIGMA_FLOOR = 1.0


def compute_zscore(window: list[float], min_periods: int = MIN_ZSCORE_POINTS) -> float | None:
    if len(window) < min_periods:
        return None
    mu = mean(window)
    sigma = max(stdev(window), SIGMA_FLOOR)
    return max(-3.0, min(3.0, round((window[-1] - mu) / sigma, 2)))


def compute_percentile(window: list[float], current: float) -> float | None:
    if not window:
        return None
    return round(sum(1 for v in window if v <= current) / len(window) * 100, 1)


def compute_trend_delta(series: list[float], n: int) -> int | None:
    """Delta between last value and value n days ago. series[0]=oldest."""
    if len(series) < n:
        return None
    return int(series[-1] - series[-n])


def compute_trend_slope(series: list[float]) -> float | None:
    """OLS slope (points/day) via statistics.linear_regression."""
    if len(series) < 2:
        return None
    x = list(range(len(series)))
    result = linear_regression(x, series)
    return round(result.slope, 3)


def compute_consensus(labels: list[str]) -> str:
    """2-of-3 majority vote. Labels: 'rising', 'falling', 'flat'."""
    rising = sum(1 for l in labels if l == "rising")
    falling = sum(1 for l in labels if l == "falling")
    majority = len(labels) // 2 + 1
    if rising >= majority or falling >= majority:
        return "aligned"
    return "mixed"


def compute_regime_days(values: list[float], low: float, high: float) -> int:
    """Count consecutive days from end of series within [low, high]."""
    count = 0
    for v in reversed(values):
        if low <= v <= high:
            count += 1
        else:
            break
    return count


def classify_trend(delta: int | None, threshold: int = 3) -> str:
    if delta is None:
        return "unknown"
    if delta > threshold:
        return "rising"
    if delta < -threshold:
        return "falling"
    return "flat"
```

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat(feargreed): analytics — zscore, percentile, trends, consensus, regime"
```

---

### Task 4: Confidence scoring

**Files:**
- Modify: `skills/feargreed/scripts/feargreed.py`
- Modify: `tests/test_feargreed.py`

**Step 1: Write confidence tests**

```python
class TestConfidence:
    def test_extreme_fear_high_confidence(self):
        from feargreed import compute_confidence
        # Extreme fear, aligned trends, 10 days in zone
        score = compute_confidence(
            value=10, oversold=25, overbought=75,
            trend_consensus="aligned", regime_days=10,
            data_fresh=True,
        )
        assert 70 <= score <= 100

    def test_neutral_low_confidence(self):
        from feargreed import compute_confidence
        score = compute_confidence(
            value=50, oversold=25, overbought=75,
            trend_consensus="mixed", regime_days=1,
            data_fresh=True,
        )
        assert score <= 50

    def test_stale_data_penalty(self):
        from feargreed import compute_confidence
        fresh = compute_confidence(
            value=15, oversold=25, overbought=75,
            trend_consensus="aligned", regime_days=5,
            data_fresh=True,
        )
        stale = compute_confidence(
            value=15, oversold=25, overbought=75,
            trend_consensus="aligned", regime_days=5,
            data_fresh=False,
        )
        assert stale < fresh

    def test_confidence_always_in_range(self):
        from feargreed import compute_confidence
        for v in range(0, 101):
            for consensus in ("aligned", "mixed"):
                score = compute_confidence(
                    value=v, oversold=25, overbought=75,
                    trend_consensus=consensus, regime_days=0,
                    data_fresh=True,
                )
                assert 0 <= score <= 100
```

**Step 2: Run tests — expect FAIL**

**Step 3: Implement confidence scoring**

```python
# Add to feargreed.py

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_confidence(
    value: int,
    oversold: int,
    overbought: int,
    trend_consensus: str,
    regime_days: int,
    data_fresh: bool,
) -> int:
    """Weighted confidence: extremeness 45% + trend 30% + regime 15% + quality 10%."""
    # Extremeness: distance from 50, normalized to 0..1
    extremeness = abs(value - 50) / 50.0

    # Trend alignment: 1.0 if aligned, 0.3 if mixed
    trend_align = 1.0 if trend_consensus == "aligned" else 0.3

    # Regime persistence: saturates near 1.0 after ~30 days
    regime = 1.0 - math.exp(-regime_days / 12.0)

    # Data quality: 1.0 if fresh, 0.5 if stale
    quality = 1.0 if data_fresh else 0.5

    raw = 45 * extremeness + 30 * trend_align + 15 * regime + 10 * quality
    confidence = round(12 + raw * 0.88)  # range 12..100

    # Cap at 75 if value is in neutral zone (not extreme)
    if oversold <= value <= overbought:
        confidence = min(confidence, 75)

    return max(0, min(100, confidence))
```

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat(feargreed): weighted confidence scoring (4 components)"
```

---

### Task 5: Signal classification + CLI + main()

**Files:**
- Modify: `skills/feargreed/scripts/feargreed.py`
- Modify: `tests/test_feargreed.py`

**Step 1: Write signal + CLI tests**

```python
class TestClassifySignal:
    def test_contrarian_extreme_fear_is_bullish(self):
        from feargreed import classify_signal
        assert classify_signal(10, mode="contrarian", oversold=25, overbought=75) == "bullish"

    def test_contrarian_extreme_greed_is_bearish(self):
        from feargreed import classify_signal
        assert classify_signal(85, mode="contrarian", oversold=25, overbought=75) == "bearish"

    def test_momentum_fear_is_bearish(self):
        from feargreed import classify_signal
        assert classify_signal(10, mode="momentum", oversold=25, overbought=75) == "bearish"

    def test_neutral_zone(self):
        from feargreed import classify_signal
        assert classify_signal(50, mode="contrarian", oversold=25, overbought=75) == "neutral"


class TestEndToEnd:
    @patch("urllib.request.urlopen")
    def test_main_outputs_valid_signal_json(self, mock_urlopen, capsys):
        values = [25, 30, 35, 40, 45, 50, 55, 50, 45, 40,
                  35, 30, 28, 26, 25, 30, 35, 40, 45, 50,
                  55, 50, 45, 40, 35, 30, 28, 26, 25, 30]
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_api_response(values)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from feargreed import main
        sys.argv = ["feargreed", "--mode", "contrarian",
                     "--history-days", "30"]
        main()

        output = json.loads(capsys.readouterr().out)
        assert output["schema"] == "signal/v1"
        assert output["signal"] in ("bullish", "bearish", "neutral")
        assert 0 <= output["confidence"] <= 100
        assert "analytics" in output
        assert "zscore_30d" in output["analytics"]
```

**Step 2: Run tests — expect FAIL**

**Step 3: Implement classify_signal + main**

```python
# Add to feargreed.py

# ---------------------------------------------------------------------------
# Signal Classification
# ---------------------------------------------------------------------------

def classify_signal(value: int, mode: str, oversold: int, overbought: int) -> str:
    if value < oversold:
        return "bullish" if mode == "contrarian" else "bearish"
    if value > overbought:
        return "bearish" if mode == "contrarian" else "bullish"
    return "neutral"


LABEL_MAP = {
    (0, 25): "Extreme Fear",
    (25, 45): "Fear",
    (45, 55): "Neutral",
    (55, 75): "Greed",
    (75, 101): "Extreme Greed",
}


def classify_label(value: int) -> str:
    for (lo, hi), label in LABEL_MAP.items():
        if lo <= value < hi:
            return label
    return "Unknown"


# ---------------------------------------------------------------------------
# CLI + Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Crypto Fear & Greed Index — sentiment signal",
        prog="feargreed",
    )
    p.add_argument("--mode", choices=["contrarian", "momentum"],
                   default="contrarian", help="Signal interpretation mode")
    p.add_argument("--oversold", type=int, default=25,
                   help="F&G below this = extreme fear zone")
    p.add_argument("--overbought", type=int, default=75,
                   help="F&G above this = extreme greed zone")
    p.add_argument("--history-days", type=int, default=90,
                   help="Days of history for analytics (default 90)")
    return p


def main() -> None:
    args = build_parser().parse_args()

    # Fetch data (all history for analytics, cache-aware)
    try:
        entries = fetch_fng(days=args.history_days)
        _save_cache(entries)
        data_fresh = True
    except ConnectionError:
        cached, _ = _load_cache()
        if cached and (time.time() - _) < STALE_WINDOW_S:
            entries = cached
            data_fresh = False
        else:
            ErrorOutput(error="API unreachable and no valid cache").emit()
            return

    if not entries:
        ErrorOutput(error="No data returned from API").emit()
        return

    current = entries[0]["value"]
    label = classify_label(current)

    # Build value series (oldest first for analytics)
    values = [e["value"] for e in reversed(entries)]

    # Analytics
    zscore_30d = compute_zscore(values[-30:]) if len(values) >= 10 else None
    percentile_90d = compute_percentile(values[-90:], current) if values else None

    delta_7d = compute_trend_delta(values, 7)
    delta_30d = compute_trend_delta(values, 30)
    delta_90d = compute_trend_delta(values, 90)

    trend_labels = [
        classify_trend(delta_7d),
        classify_trend(delta_30d),
        classify_trend(delta_90d),
    ]
    consensus = compute_consensus(trend_labels)

    # Regime: days in current signal zone
    if current < args.oversold:
        regime_days = compute_regime_days(values, 0, args.oversold - 1)
    elif current > args.overbought:
        regime_days = compute_regime_days(values, args.overbought + 1, 100)
    else:
        regime_days = compute_regime_days(values, args.oversold, args.overbought)

    # Signal + confidence
    signal = classify_signal(current, args.mode, args.oversold, args.overbought)
    confidence = compute_confidence(
        value=current, oversold=args.oversold, overbought=args.overbought,
        trend_consensus=consensus, regime_days=regime_days,
        data_fresh=data_fresh,
    )

    reasoning = (
        f"F&G at {current} ({label}), mode={args.mode}. "
        f"Trend 7d: {classify_trend(delta_7d)}, 30d: {classify_trend(delta_30d)}, "
        f"90d: {classify_trend(delta_90d)} → {consensus}. "
        f"In zone for {regime_days} days."
    )
    if not data_fresh:
        reasoning += " [STALE DATA — using cache]"

    out = SignalOutput(
        signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        data={
            "current": {"value": current, "label": label},
            "previous": {"value": entries[1]["value"], "label": classify_label(entries[1]["value"])} if len(entries) > 1 else None,
            "mode": args.mode,
            "data_fresh": data_fresh,
        },
        analytics={
            "zscore_30d": zscore_30d,
            "percentile_90d": percentile_90d,
            "trend_7d": delta_7d,
            "trend_30d": delta_30d,
            "trend_90d": delta_90d,
            "trend_7d_label": classify_trend(delta_7d),
            "trend_30d_label": classify_trend(delta_30d),
            "trend_90d_label": classify_trend(delta_90d),
            "consensus": consensus,
            "regime_days": regime_days,
        },
    )

    # Human summary to stderr
    out.summary(
        f"  Fear & Greed: {current} ({label}) | Signal: {signal} ({args.mode})\n"
        f"  Confidence: {confidence}/100 | Trend: {consensus} | Zone: {regime_days}d\n"
        f"  Z-score(30d): {zscore_30d} | Percentile(90d): {percentile_90d}%"
    )
    out.emit()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests — expect PASS**

Run: `cd /Users/vi/personal/forgequant/crucible/sentinel && python -m pytest tests/test_feargreed.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat(feargreed): complete skill — signal, confidence, analytics, CLI"
```

---

### Task 6: Smoke test with live API

**Step 1: Run against live API**

```bash
cd /Users/vi/personal/forgequant/crucible/sentinel
uv run skills/feargreed/scripts/feargreed.py --mode contrarian --history-days 90
```

Expected: valid SignalOutput JSON to stdout, human summary to stderr.

**Step 2: Run in momentum mode**

```bash
uv run skills/feargreed/scripts/feargreed.py --mode momentum --oversold 20 --overbought 80
```

**Step 3: Verify cache was created**

```bash
cat ~/.cache/crucible/feargreed.json | python -m json.tool | head -5
```

**Step 4: Run all tests one final time**

```bash
python -m pytest tests/test_feargreed.py -v --tb=short
```

**Step 5: Commit**

```bash
git add -A && git commit -m "test(feargreed): all tests passing, live smoke test verified"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | fetch_fng + retry + validation | 3 tests |
| 2 | Cache layer (save/load/fresh) | 3 tests |
| 3 | Analytics (zscore, percentile, trends, consensus, regime) | 10 tests |
| 4 | Confidence scoring (weighted 4-component) | 4 tests |
| 5 | Signal classification + CLI + main | 5 tests |
| 6 | Smoke test (live API) | manual |

**Total: ~25 tests, 1 file (~280 lines), stdlib only, 6 commits.**
