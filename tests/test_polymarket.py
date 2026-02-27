"""Tests for polymarket skill."""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "polymarket" / "scripts"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_market(question="Will BTC reach $100k?", yes_prob=0.72, volume=50000, **kw):
    prices = [str(yes_prob), str(round(1 - yes_prob, 4))]
    outcomes = ["Yes", "No"]
    return {
        "id": kw.get("id", "12345"),
        "question": question,
        "outcomePrices": json.dumps(prices),
        "outcomes": json.dumps(outcomes),
        "volume": str(volume),
        "volume24hr": str(kw.get("volume24hr", volume / 10)),
        "liquidity": str(kw.get("liquidity", volume / 5)),
        "endDate": kw.get("endDate", "2026-03-15T00:00:00Z"),
        "closed": kw.get("closed", False),
        "active": kw.get("active", True),
    }


def _make_event(title="Bitcoin price prediction", markets=None, **kw):
    end = kw.get("endDate", "2026-03-15T00:00:00Z")
    return {
        "id": kw.get("id", "100"),
        "slug": kw.get("slug", "btc-price"),
        "title": title,
        "volume": str(kw.get("volume", 1000000)),
        "volume24hr": str(kw.get("volume24hr", 50000)),
        "liquidity": str(kw.get("liquidity", 200000)),
        "startDate": kw.get("startDate", "2026-02-01T00:00:00Z"),
        "endDate": end,
        "tags": kw.get("tags", [{"label": "Crypto", "slug": "crypto"}]),
        "markets": markets or [_make_market()],
    }


def _mock_urlopen(data: bytes):
    mock_resp = MagicMock()
    mock_resp.read.return_value = data
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


SAMPLE_EVENTS = json.dumps([_make_event()]).encode()


# ---------------------------------------------------------------------------
# Task 1: Fetch & Parse Events
# ---------------------------------------------------------------------------

class TestFetchEvents:
    @patch("urllib.request.urlopen")
    def test_fetch_events_parses_response(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(SAMPLE_EVENTS)
        from polymarket import fetch_events
        events = fetch_events(tag_slugs=["crypto"], limit=10)
        assert len(events) >= 1
        assert events[0]["title"] == "Bitcoin price prediction"

    @patch("urllib.request.urlopen")
    def test_fetch_events_dedup_by_id(self, mock_urlopen):
        # Both tag_slugs return same event id → only 1 result
        mock_urlopen.return_value = _mock_urlopen(SAMPLE_EVENTS)
        from polymarket import fetch_events
        events = fetch_events(tag_slugs=["crypto", "bitcoin"], limit=10)
        assert len(events) == 1

    @patch("urllib.request.urlopen")
    def test_fetch_events_network_error_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")
        from polymarket import fetch_events
        assert fetch_events(tag_slugs=["crypto"]) == []

    @patch("urllib.request.urlopen")
    def test_fetch_partial_failure_still_works(self, mock_urlopen):
        # First call fails, second succeeds
        ev2 = _make_event(id="200", title="Ethereum event")
        mock_urlopen.side_effect = [
            Exception("timeout"),
            _mock_urlopen(json.dumps([ev2]).encode()),
        ]
        from polymarket import fetch_events
        events = fetch_events(tag_slugs=["crypto", "ethereum"], limit=10)
        assert len(events) == 1
        assert events[0]["title"] == "Ethereum event"

    def test_parse_market_probability(self):
        from polymarket import parse_probability
        m = _make_market(yes_prob=0.72)
        assert parse_probability(m) == pytest.approx(0.72, abs=0.001)

    def test_parse_market_no_yes_fallback(self):
        from polymarket import parse_probability
        m = {"outcomePrices": '["0.65", "0.35"]', "outcomes": '["Win", "Lose"]'}
        assert parse_probability(m) == pytest.approx(0.65, abs=0.001)

    def test_parse_market_missing_prices(self):
        from polymarket import parse_probability
        assert parse_probability({"outcomePrices": None}) is None
        assert parse_probability({}) is None

    def test_parse_market_invalid_json_prices(self):
        from polymarket import parse_probability
        assert parse_probability({"outcomePrices": "not json{{{"}) is None


# ---------------------------------------------------------------------------
# Task 2: Cache
# ---------------------------------------------------------------------------

class TestCache:
    def test_save_and_load_cache(self, tmp_path):
        from polymarket import _load_cache, _save_cache
        cache_file = tmp_path / "test.json"
        data = [{"title": "Test event"}]
        _save_cache(data, cache_file)
        loaded, ts = _load_cache(cache_file)
        assert loaded == data
        assert ts > 0

    def test_load_missing_returns_none(self, tmp_path):
        from polymarket import _load_cache
        assert _load_cache(tmp_path / "nope.json") == (None, 0)

    def test_load_corrupted_returns_none(self, tmp_path):
        from polymarket import _load_cache
        f = tmp_path / "bad.json"
        f.write_text("not json{{{")
        assert _load_cache(f) == (None, 0)


# ---------------------------------------------------------------------------
# Task 3: Event Classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_classify_binary_bullish(self):
        from polymarket import classify_event
        ev = _make_event(
            title="Will Bitcoin reach $100k?",
            markets=[_make_market(question="Will Bitcoin reach $100,000?")],
        )
        classify_event(ev)
        assert ev["_type"] == "binary"
        assert ev["_direction"] == "bullish"

    def test_classify_binary_bearish(self):
        from polymarket import classify_event
        ev = _make_event(
            title="Will crypto market crash?",
            markets=[_make_market(question="Will crypto crash below $50k?")],
        )
        classify_event(ev)
        assert ev["_direction"] == "bearish"

    def test_classify_curve_event(self):
        from polymarket import classify_event
        markets = [
            _make_market(question="Will BTC reach $80,000?", yes_prob=0.90),
            _make_market(question="Will BTC reach $100,000?", yes_prob=0.50),
            _make_market(question="Will BTC reach $120,000?", yes_prob=0.20),
        ]
        ev = _make_event(markets=markets)
        classify_event(ev)
        assert ev["_type"] == "curve"

    def test_classify_daily_horizon(self):
        from polymarket import classify_event
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        ev = _make_event(endDate=tomorrow)
        classify_event(ev)
        assert ev["_horizon"] == "daily"

    def test_classify_structural_horizon(self):
        from polymarket import classify_event
        far = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        ev = _make_event(endDate=far)
        classify_event(ev)
        assert ev["_horizon"] == "structural"

    def test_classify_no_enddate(self):
        from polymarket import classify_event
        ev = _make_event()
        ev["endDate"] = None
        classify_event(ev)
        assert ev["_horizon"] == "structural"

    def test_classify_unclassifiable(self):
        from polymarket import classify_event
        ev = _make_event(
            title="Kraken IPO timing",
            markets=[_make_market(question="When will Kraken IPO?")],
        )
        classify_event(ev)
        assert ev["_direction"] == "neutral"


# ---------------------------------------------------------------------------
# Task 4: Price Curve Extraction
# ---------------------------------------------------------------------------

class TestPriceCurve:
    def test_extract_strike_dollar_comma(self):
        from polymarket import extract_strike
        assert extract_strike("Will BTC reach $80,000?") == 80000

    def test_extract_strike_k_suffix(self):
        from polymarket import extract_strike
        assert extract_strike("Will BTC reach $80k?") == 80000

    def test_extract_strike_plain_number(self):
        from polymarket import extract_strike
        assert extract_strike("Bitcoin above 80000 on March 1?") == 80000

    def test_build_curve_sorted(self):
        from polymarket import build_price_curve
        markets = [
            _make_market(question="Will BTC reach $120,000?", yes_prob=0.20),
            _make_market(question="Will BTC reach $80,000?", yes_prob=0.90),
            _make_market(question="Will BTC reach $100,000?", yes_prob=0.50),
        ]
        ev = _make_event(markets=markets)
        curve = build_price_curve(ev)
        assert curve is not None
        assert curve["strikes"] == [80000, 100000, 120000]
        assert curve["probabilities"] == [0.9, 0.5, 0.2]

    def test_compute_median_from_curve(self):
        from polymarket import build_price_curve
        markets = [
            _make_market(question="Will BTC reach $80,000?", yes_prob=0.90),
            _make_market(question="Will BTC reach $100,000?", yes_prob=0.50),
            _make_market(question="Will BTC reach $120,000?", yes_prob=0.20),
        ]
        ev = _make_event(markets=markets)
        curve = build_price_curve(ev)
        # Median should be around $100k (where prob crosses 0.5)
        assert curve is not None
        assert 95000 <= curve["median"] <= 105000

    def test_compute_spread_from_curve(self):
        from polymarket import build_price_curve
        markets = [
            _make_market(question="Will BTC reach $80,000?", yes_prob=0.90),
            _make_market(question="Will BTC reach $100,000?", yes_prob=0.50),
            _make_market(question="Will BTC reach $120,000?", yes_prob=0.20),
        ]
        ev = _make_event(markets=markets)
        curve = build_price_curve(ev)
        assert curve is not None
        assert curve["spread"] > 0

    def test_curve_single_strike_returns_none(self):
        from polymarket import build_price_curve
        markets = [_make_market(question="Will BTC reach $100,000?", yes_prob=0.50)]
        ev = _make_event(markets=markets)
        assert build_price_curve(ev) is None


# ---------------------------------------------------------------------------
# Task 5: Coin Detection & Directional Scoring
# ---------------------------------------------------------------------------

class TestCoinAndDirection:
    def test_detect_bitcoin_from_title(self):
        from polymarket import detect_coins
        assert "BTC" in detect_coins("Bitcoin ETF approval?")

    def test_detect_ethereum_from_question(self):
        from polymarket import detect_coins
        assert "ETH" in detect_coins("Will ETH reach $5k?")

    def test_directional_bullish_simple(self):
        from polymarket import bullish_probability
        m = _make_market(question="Will Bitcoin reach $100k?", yes_prob=0.72)
        assert bullish_probability(m) == pytest.approx(0.72, abs=0.01)

    def test_directional_bearish_inverted(self):
        from polymarket import bullish_probability
        m = _make_market(question="Will Bitcoin crash below $50k?", yes_prob=0.60)
        assert bullish_probability(m) == pytest.approx(0.40, abs=0.01)

    def test_aggregate_directional_signal(self):
        from polymarket import compute_signal
        events = [
            _make_event(
                markets=[
                    _make_market(question="Will BTC reach $100k?", yes_prob=0.80),
                    _make_market(question="Will BTC reach $120k?", yes_prob=0.60),
                ]
            ),
        ]
        sig = compute_signal(events)
        assert sig["signal"] == "bullish"
        assert sig["avg_bullish"] > 0.6


# ---------------------------------------------------------------------------
# Task 6: Confidence Scoring
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_high_edge_high_confidence(self):
        from polymarket import compute_confidence
        score = compute_confidence(
            signal_edge=0.80, liquidity=500000, volume24hr=2000000,
            n_markets=15, median_days_to_expiry=5,
        )
        assert score >= 60

    def test_neutral_low_confidence(self):
        from polymarket import compute_confidence
        score = compute_confidence(
            signal_edge=0.05, liquidity=1000, volume24hr=1000,
            n_markets=2, median_days_to_expiry=180,
        )
        assert score <= 40

    def test_volume_boosts_confidence(self):
        from polymarket import compute_confidence
        low_vol = compute_confidence(0.5, 100000, 1000, 5, 10)
        high_vol = compute_confidence(0.5, 100000, 3000000, 5, 10)
        assert high_vol > low_vol

    def test_time_decay_reduces_confidence(self):
        from polymarket import compute_confidence
        near = compute_confidence(0.5, 100000, 100000, 5, 3)
        far = compute_confidence(0.5, 100000, 100000, 5, 300)
        assert near > far

    def test_confidence_always_in_range(self):
        from polymarket import compute_confidence
        for edge in [0, 0.2, 0.5, 0.8, 1.0]:
            for liq in [0, 1000, 1000000]:
                for vol in [0, 1000, 5000000]:
                    score = compute_confidence(edge, liq, vol, 5, 30)
                    assert 15 <= score <= 100


# ---------------------------------------------------------------------------
# Task 7: End-to-End & CLI
# ---------------------------------------------------------------------------

class TestEndToEnd:
    @patch("urllib.request.urlopen")
    def test_main_outputs_valid_signal_json(self, mock_urlopen, capsys, tmp_path, monkeypatch):
        mock_urlopen.return_value = _mock_urlopen(SAMPLE_EVENTS)

        import polymarket
        monkeypatch.setattr(polymarket, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(polymarket, "CACHE_FILE", tmp_path / "events.json")

        sys.argv = ["polymarket", "--limit", "10"]
        polymarket.main()

        output = json.loads(capsys.readouterr().out)
        assert output["schema"] == "signal/v1"
        assert output["signal"] in ("bullish", "bearish", "neutral")
        assert 15 <= output["confidence"] <= 100
        assert "count" in output["data"]
        assert "analytics" in output

    @patch("urllib.request.urlopen")
    def test_main_with_horizon_filter(self, mock_urlopen, capsys, tmp_path, monkeypatch):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        far = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        events = [
            _make_event(id="1", title="Daily BTC", endDate=tomorrow, volume24hr=5000),
            _make_event(id="2", title="Structural BTC", endDate=far, volume24hr=5000),
        ]
        mock_urlopen.return_value = _mock_urlopen(json.dumps(events).encode())

        import polymarket
        monkeypatch.setattr(polymarket, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(polymarket, "CACHE_FILE", tmp_path / "events.json")

        sys.argv = ["polymarket", "--horizon", "daily"]
        polymarket.main()

        output = json.loads(capsys.readouterr().out)
        assert output["data"]["horizon_breakdown"]["structural"] == 0

    @patch("urllib.request.urlopen")
    def test_main_with_coin_filter(self, mock_urlopen, capsys, tmp_path, monkeypatch):
        events = [
            _make_event(id="1", title="Bitcoin prediction", markets=[_make_market(question="Will Bitcoin reach $100k?")]),
            _make_event(id="2", title="Ethereum prediction", markets=[_make_market(question="Will Ethereum reach $5k?")]),
        ]
        mock_urlopen.return_value = _mock_urlopen(json.dumps(events).encode())

        import polymarket
        monkeypatch.setattr(polymarket, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(polymarket, "CACHE_FILE", tmp_path / "events.json")

        sys.argv = ["polymarket", "--coins", "ETH"]
        polymarket.main()

        output = json.loads(capsys.readouterr().out)
        # Should only have Ethereum event
        assert output["data"]["count"] == 1

    @patch("urllib.request.urlopen")
    def test_main_with_min_volume(self, mock_urlopen, capsys, tmp_path, monkeypatch):
        events = [
            _make_event(id="1", title="High vol BTC", volume24hr=50000),
            _make_event(id="2", title="Low vol BTC", volume24hr=100),
        ]
        mock_urlopen.return_value = _mock_urlopen(json.dumps(events).encode())

        import polymarket
        monkeypatch.setattr(polymarket, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(polymarket, "CACHE_FILE", tmp_path / "events.json")

        sys.argv = ["polymarket", "--min-volume", "10000"]
        polymarket.main()

        output = json.loads(capsys.readouterr().out)
        assert output["data"]["count"] == 1

    @patch("urllib.request.urlopen")
    def test_main_no_events_neutral(self, mock_urlopen, capsys, tmp_path, monkeypatch):
        mock_urlopen.return_value = _mock_urlopen(b"[]")

        import polymarket
        monkeypatch.setattr(polymarket, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(polymarket, "CACHE_FILE", tmp_path / "events.json")

        sys.argv = ["polymarket"]
        polymarket.main()

        output = json.loads(capsys.readouterr().out)
        assert output["signal"] == "neutral"
        assert output["confidence"] <= 20
