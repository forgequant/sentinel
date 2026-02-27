"""Tests for LunarCrush social intelligence skill."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "lunarcrush" / "scripts"))
import lunarcrush  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coin(
    symbol: str = "BTC",
    galaxy_score: float | None = 72,
    galaxy_score_previous: float | None = 68,
    alt_rank: float | None = 3,
    alt_rank_previous: float | None = 5,
    sentiment: float | None = 65,
    social_dominance: float | None = 28.0,
    interactions_24h: float | None = 3_000_000,
    **kwargs: object,
) -> dict:
    d: dict = {
        "symbol": symbol,
        "galaxy_score": galaxy_score,
        "galaxy_score_previous": galaxy_score_previous,
        "alt_rank": alt_rank,
        "alt_rank_previous": alt_rank_previous,
        "sentiment": sentiment,
        "social_dominance": social_dominance,
        "interactions_24h": interactions_24h,
    }
    d.update(kwargs)
    return d


def _mock_response(data: list[dict], status: int = 200) -> mock.MagicMock:
    body = json.dumps({"data": data}).encode()
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


# ===================================================================
# Task 1: Auth & Fetch
# ===================================================================


class TestFetch:
    def test_fetch_coins_parses_response(self):
        coins = [_make_coin("BTC"), _make_coin("ETH", galaxy_score=65)]
        with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "test-key"}):
            with mock.patch("urllib.request.urlopen", return_value=_mock_response(coins)):
                result = lunarcrush.fetch_coins(limit=10)
        assert len(result) == 2
        assert result[0]["symbol"] == "BTC"
        assert result[1]["galaxy_score"] == 65

    def test_fetch_coins_empty_response(self):
        with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "test-key"}):
            with mock.patch("urllib.request.urlopen", return_value=_mock_response([])):
                result = lunarcrush.fetch_coins()
        assert result == []

    def test_fetch_coins_network_error_returns_empty(self):
        with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "test-key"}):
            with mock.patch("urllib.request.urlopen", side_effect=OSError("timeout")):
                result = lunarcrush.fetch_coins()
        assert result == []

    def test_fetch_no_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LUNARCRUSH_API_KEY", None)
            with pytest.raises(lunarcrush.AuthError, match="LUNARCRUSH_API_KEY"):
                lunarcrush.fetch_coins()

    def test_fetch_empty_api_key(self):
        with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "  "}):
            with pytest.raises(lunarcrush.AuthError, match="LUNARCRUSH_API_KEY"):
                lunarcrush.fetch_coins()

    def test_fetch_auth_error_401(self):
        import urllib.error
        err = urllib.error.HTTPError("url", 401, "Unauthorized", {}, BytesIO(b""))
        with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "bad-key"}):
            with mock.patch("urllib.request.urlopen", side_effect=err):
                with pytest.raises(lunarcrush.AuthError, match="401"):
                    lunarcrush.fetch_coins()

    def test_fetch_rate_limited_429(self):
        import urllib.error
        err = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, BytesIO(b""))
        with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "test-key"}):
            with mock.patch("urllib.request.urlopen", side_effect=err):
                with pytest.raises(lunarcrush.RateLimitError):
                    lunarcrush.fetch_coins()

    def test_fetch_partial_coins_skip_null_galaxy(self):
        coins = [_make_coin("BTC"), _make_coin("BAD", galaxy_score=None)]
        with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "test-key"}):
            with mock.patch("urllib.request.urlopen", return_value=_mock_response(coins)):
                result = lunarcrush.fetch_coins()
        assert len(result) == 1
        assert result[0]["symbol"] == "BTC"


# ===================================================================
# Task 2: Cache
# ===================================================================


class TestCache:
    def test_save_and_load_cache(self, tmp_path: Path):
        p = tmp_path / "test_cache.json"
        data = [{"symbol": "BTC", "galaxy_score": 72}]
        lunarcrush._save_cache(data, p)
        loaded, ts = lunarcrush._load_cache(p)
        assert loaded == data
        assert ts > 0

    def test_load_missing_returns_none(self, tmp_path: Path):
        p = tmp_path / "nonexistent.json"
        loaded, ts = lunarcrush._load_cache(p)
        assert loaded is None
        assert ts == 0

    def test_load_corrupted_returns_none(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("not json{{{")
        loaded, ts = lunarcrush._load_cache(p)
        assert loaded is None
        assert ts == 0


# ===================================================================
# Task 3: Signal Computation
# ===================================================================


class TestSignal:
    def test_normalize_coin_all_fields(self):
        coin = _make_coin(galaxy_score=78, sentiment=72, alt_rank=3, alt_rank_previous=5)
        score = lunarcrush.normalize_coin(coin)
        # galaxy: 0.78*0.4=0.312, sentiment: 0.72*0.4=0.288
        # altrank: (5-3)/max(5,10) = 0.2, norm=(0.2+1)/2=0.6, *0.2=0.12
        expected = 0.312 + 0.288 + 0.12
        assert abs(score - expected) < 0.001

    def test_normalize_coin_missing_sentiment(self):
        coin = _make_coin(galaxy_score=60, sentiment=None, alt_rank=10, alt_rank_previous=10)
        score = lunarcrush.normalize_coin(coin)
        # galaxy: 0.6*0.4=0.24, sentiment: 0*0.4=0
        # altrank: (10-10)/max(10,10)=0, norm=0.5, *0.2=0.1
        expected = 0.24 + 0.0 + 0.1
        assert abs(score - expected) < 0.001

    def test_normalize_coin_altrank_no_previous(self):
        coin = _make_coin(galaxy_score=50, sentiment=50, alt_rank=10, alt_rank_previous=0)
        score = lunarcrush.normalize_coin(coin)
        # altrank_norm = 0.5 (no previous)
        # galaxy: 0.5*0.4=0.2, sentiment: 0.5*0.4=0.2, alt: 0.5*0.2=0.1
        expected = 0.2 + 0.2 + 0.1
        assert abs(score - expected) < 0.001

    def test_normalize_coin_altrank_small_previous(self):
        coin = _make_coin(galaxy_score=50, sentiment=50, alt_rank=1, alt_rank_previous=1)
        score = lunarcrush.normalize_coin(coin)
        # altrank: (1-1)/max(1,10) = 0, norm = 0.5, *0.2=0.1
        expected = 0.2 + 0.2 + 0.1
        assert abs(score - expected) < 0.001

    def test_aggregate_bullish(self):
        # High galaxy + high sentiment → bullish
        coins = [_make_coin(galaxy_score=80, sentiment=80, social_dominance=10)]
        sig = lunarcrush.compute_signal(coins)
        assert sig["signal"] == "bullish"
        assert sig["avg_social"] > 0.60

    def test_aggregate_bearish(self):
        # Low galaxy + low sentiment → bearish
        coins = [_make_coin(galaxy_score=20, sentiment=20, social_dominance=10)]
        sig = lunarcrush.compute_signal(coins)
        assert sig["signal"] == "bearish"
        assert sig["avg_social"] < 0.40

    def test_aggregate_weighted_by_dominance(self):
        # BTC with high dominance should pull average toward its score
        btc = _make_coin("BTC", galaxy_score=80, sentiment=80, social_dominance=90)
        alt = _make_coin("DOGE", galaxy_score=20, sentiment=20, social_dominance=10)
        sig = lunarcrush.compute_signal([btc, alt])
        assert sig["signal"] == "bullish"  # BTC dominance wins


# ===================================================================
# Task 4: Movers Detection
# ===================================================================


class TestMovers:
    def test_movers_improving(self):
        coins = [_make_coin("SOL", alt_rank=12, alt_rank_previous=45)]
        movers = lunarcrush.detect_movers(coins)
        assert len(movers["improving"]) == 1
        assert movers["improving"][0]["symbol"] == "SOL"
        assert movers["improving"][0]["delta"] == 33

    def test_movers_declining(self):
        coins = [_make_coin("DOGE", alt_rank=89, alt_rank_previous=34)]
        movers = lunarcrush.detect_movers(coins)
        assert len(movers["declining"]) == 1
        assert movers["declining"][0]["symbol"] == "DOGE"
        assert movers["declining"][0]["delta"] == -55

    def test_movers_skip_no_delta(self):
        coins = [_make_coin("XRP", alt_rank=5, alt_rank_previous=0)]
        movers = lunarcrush.detect_movers(coins)
        assert movers["improving"] == []
        assert movers["declining"] == []


# ===================================================================
# Task 5: Confidence Scoring
# ===================================================================


class TestConfidence:
    def test_high_galaxy_high_confidence(self):
        conf = lunarcrush.compute_confidence(
            signal_edge=0.8, avg_galaxy=75, total_interactions=20_000_000, avg_altrank_delta=0.3
        )
        assert conf >= 70

    def test_neutral_low_confidence(self):
        conf = lunarcrush.compute_confidence(
            signal_edge=0.05, avg_galaxy=30, total_interactions=100_000, avg_altrank_delta=0.01
        )
        assert conf <= 40

    def test_engagement_boosts_confidence(self):
        low = lunarcrush.compute_confidence(signal_edge=0.5, avg_galaxy=50, total_interactions=1000)
        high = lunarcrush.compute_confidence(signal_edge=0.5, avg_galaxy=50, total_interactions=30_000_000)
        assert high > low

    def test_momentum_boosts_confidence(self):
        low = lunarcrush.compute_confidence(signal_edge=0.5, avg_galaxy=50, avg_altrank_delta=0.01)
        high = lunarcrush.compute_confidence(signal_edge=0.5, avg_galaxy=50, avg_altrank_delta=0.5)
        assert high > low

    def test_confidence_always_in_range(self):
        """Parametric sweep: confidence always in [15, 100]."""
        for edge in [0, 0.1, 0.5, 0.9, 1.0]:
            for galaxy in [0, 30, 60, 80, 100]:
                for interact in [0, 1000, 1_000_000, 100_000_000]:
                    for delta in [0, 0.1, 0.5, 1.0]:
                        conf = lunarcrush.compute_confidence(edge, galaxy, interact, delta)
                        assert 15 <= conf <= 100, f"conf={conf} for edge={edge}, galaxy={galaxy}"


# ===================================================================
# Task 6: End-to-End & CLI
# ===================================================================


class TestMain:
    def _run_main(self, coins: list[dict], args: list[str] | None = None,
                  env_key: str = "test-key", cache_path: Path | None = None) -> tuple[dict, str]:
        """Helper: run main() with mocked fetch, capture stdout/stderr."""
        env = {"LUNARCRUSH_API_KEY": env_key} if env_key else {}
        with tempfile.TemporaryDirectory() as tmpdir:
            cp = cache_path or Path(tmpdir) / "coins.json"
            with mock.patch.object(lunarcrush, "CACHE_FILE", cp):
                with mock.patch.dict(os.environ, env, clear=True):
                    with mock.patch.object(sys, "argv", ["lunarcrush"] + (args or [])):
                        with mock.patch("lunarcrush.fetch_coins", return_value=coins):
                            from io import StringIO
                            out, err = StringIO(), StringIO()
                            with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
                                lunarcrush.main()
            stdout_str = out.getvalue()
            stderr_str = err.getvalue()
        result = json.loads(stdout_str) if stdout_str.strip() else {}
        return result, stderr_str

    def test_main_outputs_valid_signal_json(self):
        coins = [_make_coin("BTC"), _make_coin("ETH", galaxy_score=65, sentiment=60)]
        result, _ = self._run_main(coins)
        assert result["schema"] == "signal/v1"
        assert result["signal"] in ("bullish", "bearish", "neutral")
        assert 0 <= result["confidence"] <= 100
        assert "data" in result
        assert "analytics" in result

    def test_main_no_api_key_neutral(self):
        def no_key_fetch(**kw):
            raise lunarcrush.AuthError("LUNARCRUSH_API_KEY not set")
        with tempfile.TemporaryDirectory() as tmpdir:
            cp = Path(tmpdir) / "coins.json"
            with mock.patch.object(lunarcrush, "CACHE_FILE", cp):
                with mock.patch.dict(os.environ, {}, clear=True):
                    with mock.patch.object(sys, "argv", ["lunarcrush"]):
                        with mock.patch("lunarcrush.fetch_coins", side_effect=no_key_fetch):
                            from io import StringIO
                            out, err = StringIO(), StringIO()
                            with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
                                lunarcrush.main()
            result = json.loads(out.getvalue())
        assert result["signal"] == "neutral"
        assert result["confidence"] == 0

    def test_main_with_coin_filter(self):
        coins = [
            _make_coin("BTC", galaxy_score=70, sentiment=70),
            _make_coin("ETH", galaxy_score=60, sentiment=60),
            _make_coin("DOGE", galaxy_score=40, sentiment=40),
        ]
        result, _ = self._run_main(coins, args=["--coins", "BTC,ETH"])
        symbols = [c["symbol"] for c in result["data"]["top_coins"]]
        assert "DOGE" not in symbols
        assert result["data"]["count"] == 2

    def test_main_with_min_galaxy(self):
        coins = [
            _make_coin("BTC", galaxy_score=70),
            _make_coin("LOW", galaxy_score=30),
        ]
        result, _ = self._run_main(coins, args=["--min-galaxy", "50"])
        assert result["data"]["count"] == 1

    def test_main_empty_response_neutral(self):
        result, stderr = self._run_main([], args=[])
        assert result["signal"] == "neutral"
        assert result["confidence"] <= 20

    def test_main_auth_error(self):
        def auth_fail(**kw):
            raise lunarcrush.AuthError("Invalid or expired API key (HTTP 401)")
        with tempfile.TemporaryDirectory() as tmpdir:
            cp = Path(tmpdir) / "coins.json"
            with mock.patch.object(lunarcrush, "CACHE_FILE", cp):
                with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "bad"}, clear=True):
                    with mock.patch.object(sys, "argv", ["lunarcrush"]):
                        with mock.patch("lunarcrush.fetch_coins", side_effect=auth_fail):
                            from io import StringIO
                            out, err = StringIO(), StringIO()
                            with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
                                lunarcrush.main()
            result = json.loads(out.getvalue())
        assert result["signal"] == "neutral"
        assert result["confidence"] == 0
        assert "401" in err.getvalue()

    def test_main_cache_fresh_fallback(self):
        """Network error + fresh cache → uses cached data."""
        coins = [_make_coin("BTC", galaxy_score=70, sentiment=70)]
        with tempfile.TemporaryDirectory() as tmpdir:
            cp = Path(tmpdir) / "coins.json"
            # Pre-populate fresh cache
            lunarcrush._save_cache(coins, cp)
            with mock.patch.object(lunarcrush, "CACHE_FILE", cp):
                with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "key"}, clear=True):
                    with mock.patch.object(sys, "argv", ["lunarcrush"]):
                        with mock.patch("lunarcrush.fetch_coins", return_value=[]):
                            from io import StringIO
                            out, err = StringIO(), StringIO()
                            with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
                                lunarcrush.main()
            result = json.loads(out.getvalue())
        assert result["data"]["count"] == 1

    def test_main_cache_stale_fallback(self):
        """Network error + stale cache (<30m) → uses cached data, lower confidence."""
        coins = [_make_coin("BTC", galaxy_score=70, sentiment=70)]
        with tempfile.TemporaryDirectory() as tmpdir:
            cp = Path(tmpdir) / "coins.json"
            # Write cache with timestamp 5 minutes ago
            payload = json.dumps({"data": coins, "ts": time.time() - 300})
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(payload)
            with mock.patch.object(lunarcrush, "CACHE_FILE", cp):
                with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "key"}, clear=True):
                    with mock.patch.object(sys, "argv", ["lunarcrush"]):
                        with mock.patch("lunarcrush.fetch_coins", return_value=[]):
                            from io import StringIO
                            out, err = StringIO(), StringIO()
                            with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
                                lunarcrush.main()
            result = json.loads(out.getvalue())
        assert result["data"]["count"] == 1
        # Stale cache should still work
        assert result["confidence"] > 0

    def test_main_cache_expired_neutral(self):
        """Network error + expired cache (>30m) → neutral."""
        coins = [_make_coin("BTC")]
        with tempfile.TemporaryDirectory() as tmpdir:
            cp = Path(tmpdir) / "coins.json"
            # Write cache with timestamp 2 hours ago
            payload = json.dumps({"data": coins, "ts": time.time() - 7200})
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(payload)
            with mock.patch.object(lunarcrush, "CACHE_FILE", cp):
                with mock.patch.dict(os.environ, {"LUNARCRUSH_API_KEY": "key"}, clear=True):
                    with mock.patch.object(sys, "argv", ["lunarcrush"]):
                        with mock.patch("lunarcrush.fetch_coins", return_value=[]):
                            from io import StringIO
                            out, err = StringIO(), StringIO()
                            with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
                                lunarcrush.main()
            result = json.loads(out.getvalue())
        assert result["signal"] == "neutral"
        assert result["confidence"] <= 20
