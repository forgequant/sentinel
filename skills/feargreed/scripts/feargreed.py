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
        entry: dict[str, Any] = {"value": value, "date": date, "timestamp": ts}
        if i == 0 and "time_until_update" in item:
            entry["time_until_update"] = int(item["time_until_update"])
        entries.append(entry)
    return entries


def _fetch_with_retry(url: str) -> dict:
    """Fetch URL with exponential backoff + jitter. Returns parsed JSON."""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                delay = min(6, 0.5 * 2**attempt + random.uniform(0, 0.2))
                time.sleep(delay)
    raise ConnectionError(f"API failed after {MAX_RETRIES + 1} attempts: {last_err}")


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
    p.add_argument(
        "--mode",
        choices=["contrarian", "momentum"],
        default="contrarian",
        help="Signal interpretation mode",
    )
    p.add_argument(
        "--oversold",
        type=int,
        default=25,
        help="F&G below this = extreme fear zone",
    )
    p.add_argument(
        "--overbought",
        type=int,
        default=75,
        help="F&G above this = extreme greed zone",
    )
    p.add_argument(
        "--history-days",
        type=int,
        default=90,
        help="Days of history for analytics (default 90)",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    # Fetch data (cache-aware)
    try:
        entries = fetch_fng(days=args.history_days)
        _save_cache(entries)
        data_fresh = True
    except ConnectionError:
        cached, ts = _load_cache()
        if cached and (time.time() - ts) < STALE_WINDOW_S:
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
    zscore_30d = compute_zscore(values[-30:]) if len(values) >= MIN_ZSCORE_POINTS else None
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
        value=current,
        oversold=args.oversold,
        overbought=args.overbought,
        trend_consensus=consensus,
        regime_days=regime_days,
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
            "previous": (
                {"value": entries[1]["value"], "label": classify_label(entries[1]["value"])}
                if len(entries) > 1
                else None
            ),
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
