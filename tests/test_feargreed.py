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
        entry = {
            "value": str(v),
            "value_classification": "Fear",
            "timestamp": str(ts - i * 86400),
        }
        if i == 0:
            entry["time_until_update"] = str(time_until_update)
        data.append(entry)
    return json.dumps(
        {"name": "Fear and Greed Index", "data": data, "metadata": {"error": None}}
    ).encode()


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class TestCache:
    def test_save_and_load_cache(self, tmp_path):
        from feargreed import _load_cache, _save_cache

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
        from feargreed import _is_cache_fresh, _save_cache

        cache_file = tmp_path / "fg.json"
        _save_cache([], cache_file)
        # Fresh with generous TTL
        assert _is_cache_fresh(cache_file, ttl=99999)
        # Stale with 0 TTL
        assert not _is_cache_fresh(cache_file, ttl=0)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class TestAnalytics:
    def test_zscore_normal_data(self):
        from feargreed import compute_zscore

        # Mean ~50, stddev ~10
        window = [
            40, 45, 50, 55, 60, 50, 45, 55, 50, 48,
            52, 47, 53, 49, 51, 46, 54, 50, 48, 52,
            50, 45, 55, 50, 48, 52, 47, 53, 49, 51,
        ]
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


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_extreme_fear_high_confidence(self):
        from feargreed import compute_confidence

        # Extreme fear, aligned trends, 10 days in zone
        score = compute_confidence(
            value=10,
            oversold=25,
            overbought=75,
            trend_consensus="aligned",
            regime_days=10,
            data_fresh=True,
        )
        assert 70 <= score <= 100

    def test_neutral_low_confidence(self):
        from feargreed import compute_confidence

        score = compute_confidence(
            value=50,
            oversold=25,
            overbought=75,
            trend_consensus="mixed",
            regime_days=1,
            data_fresh=True,
        )
        assert score <= 50

    def test_stale_data_penalty(self):
        from feargreed import compute_confidence

        fresh = compute_confidence(
            value=15,
            oversold=25,
            overbought=75,
            trend_consensus="aligned",
            regime_days=5,
            data_fresh=True,
        )
        stale = compute_confidence(
            value=15,
            oversold=25,
            overbought=75,
            trend_consensus="aligned",
            regime_days=5,
            data_fresh=False,
        )
        assert stale < fresh

    def test_confidence_always_in_range(self):
        from feargreed import compute_confidence

        for v in range(0, 101):
            for consensus in ("aligned", "mixed"):
                score = compute_confidence(
                    value=v,
                    oversold=25,
                    overbought=75,
                    trend_consensus=consensus,
                    regime_days=0,
                    data_fresh=True,
                )
                assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# Signal classification
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @patch("urllib.request.urlopen")
    def test_main_outputs_valid_signal_json(self, mock_urlopen, capsys, tmp_path, monkeypatch):
        values = [
            25, 30, 35, 40, 45, 50, 55, 50, 45, 40,
            35, 30, 28, 26, 25, 30, 35, 40, 45, 50,
            55, 50, 45, 40, 35, 30, 28, 26, 25, 30,
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_api_response(values)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        # Use tmp_path for cache to avoid polluting real cache
        import feargreed

        monkeypatch.setattr(feargreed, "CACHE_FILE", tmp_path / "fg.json")

        sys.argv = ["feargreed", "--mode", "contrarian", "--history-days", "30"]
        feargreed.main()

        output = json.loads(capsys.readouterr().out)
        assert output["schema"] == "signal/v1"
        assert output["signal"] in ("bullish", "bearish", "neutral")
        assert 0 <= output["confidence"] <= 100
        assert "analytics" in output
        assert "zscore_30d" in output["analytics"]
